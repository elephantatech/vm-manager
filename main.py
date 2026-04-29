import os
import uuid
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel
from jose import jwt

from logger_config import logger
from security import (
    verify_password,
    hash_password,
    create_access_token,
    SECRET_KEY,
    ALGORITHM,
)
from vm_control import VMControl
from proxy import ProxyManager
import database as db_mod

# --- Constants & Permissions ---

PERMISSIONS = {
    "all": "*",
    "vm_read": "vm:read",
    "vm_add": "vm:add",
    "vm_scan": "vm:scan",
    "vm_delete": "vm:delete",
    "vm_start": "vm:start",
    "vm_stop": "vm:stop",
    "vm_restart": "vm:restart",
    "proxy_create": "proxy:create",
    "proxy_delete": "proxy:delete",
    "proxy_toggle": "proxy:toggle",
    "user_manage": "user:manage",
}

GROUPS = {
    "admin": "*",
    "vm_operator": "vm:read,vm:start,vm:stop,vm:restart,proxy:toggle",
    "vm_manager": "vm:read,vm:start,vm:stop,vm:restart,vm:add,vm:scan,proxy:toggle,proxy:create,proxy:delete",
    "viewer": "vm:read",
}


# --- Models ---


class UserCreate(BaseModel):
    username: str
    password: str
    permissions: str


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


# --- App Setup ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Restore all enabled proxies
    db = db_mod.SessionLocal()
    try:
        enabled_proxies = db.query(db_mod.Proxy).filter(db_mod.Proxy.enabled).all()
        for p in enabled_proxies:
            logger.info({"event": "restoring_proxy", "port": p.host_port})
            vm_path = p.vm.path if p.vm else None
            await proxy_manager.start_proxy(
                p.host_port, p.vm_port, db, vm_path=vm_path, target_host=p.target_host
            )
    finally:
        db.close()
    yield
    # Shutdown: Cleanup
    ports = list(proxy_manager.proxies.keys())
    for port in ports:
        await proxy_manager.stop_proxy(port)


app = FastAPI(title="VMware Web Manager", lifespan=lifespan)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def get_db():
    db = db_mod.SessionLocal()
    try:
        yield db
    finally:
        db.close()


db_mod.init_db()

_init_db = db_mod.SessionLocal()
setting = (
    _init_db.query(db_mod.Setting).filter(db_mod.Setting.key == "vmrun_path").first()
)
vmrun_path = (
    setting.value
    if setting
    else r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe"
)
_init_db.close()

vm_control = VMControl(vmrun_path)
proxy_manager = ProxyManager(vm_control.get_guest_ip)


# --- Auth & Helpers ---


def bootstrap_admin(db: Session):
    if db.query(db_mod.User).count() == 0:
        logger.info({"event": "bootstrapping_admin_user"})
        db.add(
            db_mod.User(
                username="admin",
                hashed_password=hash_password("admin"),
                permissions="*",
            )
        )
        db.commit()


_boot_db = db_mod.SessionLocal()
bootstrap_admin(_boot_db)
_boot_db.close()


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> db_mod.User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401)
    except Exception:
        raise HTTPException(status_code=401)
    user = db.query(db_mod.User).filter(db_mod.User.username == username).first()
    if not user:
        raise HTTPException(status_code=401)
    return user


def check_perms(user: db_mod.User, req: str):
    if user.permissions == "*" or req in user.permissions.split(","):
        return True
    raise HTTPException(status_code=403, detail=f"Missing: {req}")


@app.middleware("http")
async def lan_middleware(request: Request, call_next):
    client_ip = request.client.host
    is_private = (
        client_ip in ["127.0.0.1", "::1", "testclient"]
        or client_ip.startswith(("192.168.", "10."))
        or (client_ip.startswith("172.") and 16 <= int(client_ip.split(".")[1]) <= 31)
    )
    if not is_private:
        return JSONResponse(status_code=403, content={"detail": "LAN only"})
    return await call_next(request)


# --- Endpoints ---


@app.post("/token")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = (
        db.query(db_mod.User).filter(db_mod.User.username == form_data.username).first()
    )
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid credentials")
    return {
        "access_token": create_access_token({"sub": user.username}),
        "token_type": "bearer",
        "permissions": user.permissions,
    }


@app.post("/api/user/change-password")
async def change_pwd(
    data: PasswordChange,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(data.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Wrong old password")
    current_user.hashed_password = hash_password(data.new_password)
    db.commit()
    return {"status": "success"}


@app.post("/api/users")
async def create_user(
    data: UserCreate,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "user:manage")
    perms = GROUPS.get(data.permissions, data.permissions)
    db.add(
        db_mod.User(
            username=data.username,
            hashed_password=hash_password(data.password),
            permissions=perms,
        )
    )
    db.commit()
    return {"status": "success"}


@app.get("/api/vms")
async def get_vms(
    current_user: db_mod.User = Depends(get_current_user), db: Session = Depends(get_db)
):
    check_perms(current_user, "vm:read")
    res = []
    for vm in db.query(db_mod.VM).all():
        res.append(
            {
                "id": vm.id,
                "name": vm.name,
                "path": vm.path,
                "status": await vm_control.get_status(vm.path),
                "proxies": [
                    {
                        "id": p.id,
                        "host_port": p.host_port,
                        "vm_port": p.vm_port,
                        "enabled": p.enabled,
                    }
                    for p in vm.proxies
                ],
            }
        )
    return res


@app.post("/api/vms/scan")
async def scan_vms(
    current_user: db_mod.User = Depends(get_current_user), db: Session = Depends(get_db)
):
    check_perms(current_user, "vm:scan")
    found = await vm_control.scan_for_vms()
    existing = {v.path.lower() for v in db.query(db_mod.VM).all()}
    return [
        {"name": os.path.splitext(os.path.basename(p))[0], "path": p}
        for p in found
        if p.lower() not in existing
    ]


@app.post("/api/vms")
async def add_vm(
    name: str,
    path: str,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "vm:add")
    if not os.path.exists(path):
        raise HTTPException(status_code=400, detail="VMX not found")
    db.add(db_mod.VM(id=str(uuid.uuid4()), name=name, path=path))
    db.commit()
    return {"status": "success"}


@app.delete("/api/vms/{vm_id}")
async def delete_vm(
    vm_id: str,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "vm:delete")
    vm = db.query(db_mod.VM).filter(db_mod.VM.id == vm_id).first()
    if vm:
        db.delete(vm)
        db.commit()
    return {"status": "success"}


@app.post("/api/vms/{vm_id}/{action}")
async def control_vm(
    vm_id: str,
    action: str,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, f"vm:{action}")
    vm = db.query(db_mod.VM).filter(db_mod.VM.id == vm_id).first()
    if not vm:
        raise HTTPException(status_code=404)
    success = False
    if action == "start":
        success = await vm_control.start_vm(vm.path)
    elif action == "stop":
        success = await vm_control.stop_vm(vm.path)
    elif action == "restart":
        success = await vm_control.restart_vm(vm.path)
    if not success:
        raise HTTPException(status_code=500)
    return {"status": "success"}


@app.get("/api/registry")
async def get_registry(
    current_user: db_mod.User = Depends(get_current_user), db: Session = Depends(get_db)
):
    active = [
        {
            "port": p.host_port,
            "target": f"{p.target_host or 'VM'}:{p.vm_port}",
            "type": "VM" if p.vm_id else "Host",
            "status": "active",
        }
        for p in proxy_manager.proxies.values()
    ]
    reserved = db.query(db_mod.ReservedPort).all()
    blocked = [
        {
            "port": r.port,
            "target": r.description,
            "type": "Blocked",
            "status": "blocked",
        }
        for r in reserved
    ]
    return active + blocked


@app.get("/api/proxies")
async def get_all_proxies(
    current_user: db_mod.User = Depends(get_current_user), db: Session = Depends(get_db)
):
    # Returns all stored proxy configurations (not just active ones)
    proxies = db.query(db_mod.Proxy).all()
    return [
        {
            "id": p.id,
            "vm_id": p.vm_id,
            "target_host": p.target_host,
            "host_port": p.host_port,
            "vm_port": p.vm_port,
            "enabled": p.enabled,
        }
        for p in proxies
    ]


@app.post("/api/registry/scan")
async def scan_registry(
    current_user: db_mod.User = Depends(get_current_user), db: Session = Depends(get_db)
):
    check_perms(current_user, "proxy:create")
    found_ports_info = await proxy_manager.scan_host_listening_ports()

    # Filter out ports we already know about
    active_ports = set(proxy_manager.proxies.keys())
    blocked_ports = {r.port for r in db.query(db_mod.ReservedPort).all()}

    new_occupied = []
    for info in found_ports_info:
        port = info["port"]
        desc = info["description"]
        if port not in active_ports and port not in blocked_ports:
            # Auto-block in registry
            db.add(db_mod.ReservedPort(port=port, description=f"Auto-blocked: {desc}"))
            new_occupied.append({"port": port, "description": desc})

    if new_occupied:
        db.commit()

    return new_occupied


@app.post("/api/registry/block")
async def block_port(
    port: int,
    description: str,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "proxy:create")
    if port in proxy_manager.proxies:
        raise HTTPException(status_code=400, detail="Port active")
    db.add(db_mod.ReservedPort(port=port, description=description))
    db.commit()
    return {"status": "success"}


@app.delete("/api/registry/block/{port}")
async def unblock_port(
    port: int,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "proxy:delete")
    res = db.query(db_mod.ReservedPort).filter(db_mod.ReservedPort.port == port).first()
    if res:
        db.delete(res)
        db.commit()
    return {"status": "success"}


@app.post("/api/proxies")
async def create_proxy(
    host_port: int,
    target_port: int,
    vm_id: Optional[str] = None,
    target_host: Optional[str] = None,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "proxy:create")
    vm_path = None
    if vm_id:
        vm = db.query(db_mod.VM).filter(db_mod.VM.id == vm_id).first()
        if not vm:
            raise HTTPException(status_code=404)
        vm_path = vm.path
    if not await proxy_manager.start_proxy(
        host_port, target_port, db, vm_path=vm_path, target_host=target_host
    ):
        raise HTTPException(status_code=400, detail="Port unavailable")
    db.add(
        db_mod.Proxy(
            id=str(uuid.uuid4()),
            vm_id=vm_id,
            target_host=target_host,
            host_port=host_port,
            vm_port=target_port,
            enabled=True,
        )
    )
    db.commit()
    return {"status": "success"}


@app.put("/api/proxies/{proxy_id}/toggle")
async def toggle_proxy(
    proxy_id: str,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "proxy:toggle")
    proxy = db.query(db_mod.Proxy).filter(db_mod.Proxy.id == proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404)
    proxy.enabled = not proxy.enabled
    if proxy.enabled:
        if not await proxy_manager.start_proxy(
            proxy.host_port,
            proxy.vm_port,
            db,
            vm_path=(proxy.vm.path if proxy.vm else None),
            target_host=proxy.target_host,
        ):
            proxy.enabled = False
            db.commit()
            raise HTTPException(status_code=400, detail="Failed to start")
    else:
        await proxy_manager.stop_proxy(proxy.host_port)
    db.commit()
    return {"enabled": proxy.enabled}


@app.delete("/api/proxies/{proxy_id}")
async def delete_proxy(
    proxy_id: str,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "proxy:delete")
    proxy = db.query(db_mod.Proxy).filter(db_mod.Proxy.id == proxy_id).first()
    if proxy:
        await proxy_manager.stop_proxy(proxy.host_port)
        db.delete(proxy)
        db.commit()
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Proxy not found")


if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
