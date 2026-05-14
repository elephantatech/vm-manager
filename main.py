import os
import uuid
import time
import asyncio
from typing import Optional, Dict
from collections import defaultdict
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
    init_secret_key,
    ALGORITHM,
)
import security as security_mod
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

VALID_VM_ACTIONS = {"start", "stop", "restart"}

# Per-VM operation locks to prevent race conditions
vm_locks: Dict[str, asyncio.Lock] = {}

# Rate limiting for login: ip -> list of timestamps
login_attempts: Dict[str, list] = defaultdict(list)
LOGIN_RATE_LIMIT = 5
LOGIN_RATE_WINDOW = 60  # seconds

# Module-level variables set during lifespan
vm_control: Optional[VMControl] = None
proxy_manager: Optional[ProxyManager] = None

# --- Pydantic Request Models ---


class UserCreate(BaseModel):
    username: str
    password: str
    permissions: str


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


class VMCreate(BaseModel):
    name: str
    path: str


class ProxyCreate(BaseModel):
    host_port: int
    target_port: int
    vm_id: Optional[str] = None
    target_host: Optional[str] = None


class PortBlock(BaseModel):
    port: int
    description: str


# --- App Setup ---


async def cleanup_stale_firewall_rules():
    """Removes all rules starting with VMProxy_ to ensure a clean slate."""
    logger.info({"event": "firewall_cleanup_started"})
    cmd = 'netsh advfirewall firewall show rule name=all | Select-String "VMProxy_"'
    process = await asyncio.create_subprocess_shell(
        f'powershell.exe -Command "{cmd}"',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()

    if process.returncode == 0:
        lines = stdout.decode().splitlines()
        for line in lines:
            if "VMProxy_" in line:
                # Extract rule name (basic parse)
                rule_name = line.split(":", 1)[-1].strip()
                if rule_name:
                    logger.debug({"event": "cleanup_rule", "rule": rule_name})
                    del_cmd = f'netsh advfirewall firewall delete rule name="{rule_name}"'
                    await asyncio.create_subprocess_shell(del_cmd)


def bootstrap_admin(db: Session):
    if db.query(db_mod.User).count() == 0:
        logger.info({"event": "bootstrapping_admin_user"})
        db.add(
            db_mod.User(
                username="admin",
                hashed_password=hash_password("admin"),
                permissions="*",
                must_change_password=True,
            )
        )
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global vm_control, proxy_manager

    # Startup: Initialize DB
    db_mod.init_db()

    # Initialize secret key (must be after init_db)
    boot_db = db_mod.SessionLocal()
    try:
        init_secret_key(boot_db)

        # Resolve vmrun path from DB or default
        setting = boot_db.query(db_mod.Setting).filter(db_mod.Setting.key == "vmrun_path").first()
        vmrun_path = (
            setting.value
            if setting
            else r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe"
        )

        # Initialize VM control and proxy manager
        vm_control = VMControl(vmrun_path)
        proxy_manager = ProxyManager(vm_control.get_guest_ip)

        # Bootstrap admin user
        bootstrap_admin(boot_db)
    finally:
        boot_db.close()

    # Cleanup stale firewall rules from previous ungraceful shutdowns
    await cleanup_stale_firewall_rules()

    # Restore all enabled proxies
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

    # Log SSL warning
    if not os.environ.get("SSL_CERTFILE"):
        logger.warning(
            {
                "event": "no_ssl",
                "message": "Running without SSL. Set SSL_CERTFILE and SSL_KEYFILE for HTTPS.",
            }
        )

    yield

    # Shutdown: Cleanup active proxies
    if proxy_manager:
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


# --- Auth & Helpers ---


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> db_mod.User:
    try:
        payload = jwt.decode(token, security_mod.SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401)
    except Exception:
        raise HTTPException(status_code=401)
    user = db.query(db_mod.User).filter(db_mod.User.username == username).first()
    if not user:
        raise HTTPException(status_code=401)
    # Check password version matches token
    token_pw_ver = payload.get("pw_ver", 0)
    if token_pw_ver != (user.password_version or 0):
        raise HTTPException(status_code=401, detail="Token revoked")
    return user


def check_perms(user: db_mod.User, req: str):
    if user.permissions == "*" or req in user.permissions.split(","):
        return True
    raise HTTPException(status_code=403, detail=f"Missing: {req}")


def require_password_changed(user: db_mod.User):
    """Block access if user must change their password first."""
    if user.must_change_password:
        raise HTTPException(
            status_code=403,
            detail="Password change required before accessing this resource",
        )


@app.middleware("http")
async def lan_middleware(request: Request, call_next):
    client_ip = request.client.host
    try:
        is_private = client_ip in ["127.0.0.1", "::1", "testclient"] or (
            client_ip.startswith(("192.168.", "10."))
        )
        if not is_private and client_ip.startswith("172."):
            try:
                second_octet = int(client_ip.split(".")[1])
                is_private = 16 <= second_octet <= 31
            except (IndexError, ValueError):
                is_private = False
    except Exception:
        is_private = False
    if not is_private:
        return JSONResponse(status_code=403, content={"detail": "LAN only"})
    return await call_next(request)


# --- Endpoints ---


@app.post("/token")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    # Rate limiting
    client_ip = request.client.host
    now = time.time()
    # Clean old entries
    login_attempts[client_ip] = [
        t for t in login_attempts[client_ip] if now - t < LOGIN_RATE_WINDOW
    ]
    if len(login_attempts[client_ip]) >= LOGIN_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many login attempts")

    user = db.query(db_mod.User).filter(db_mod.User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        login_attempts[client_ip].append(now)
        raise HTTPException(status_code=400, detail="Invalid credentials")

    return {
        "access_token": create_access_token(
            {"sub": user.username, "pw_ver": user.password_version or 0}
        ),
        "token_type": "bearer",
        "permissions": user.permissions,
        "must_change_password": bool(user.must_change_password),
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
    current_user.must_change_password = False
    current_user.password_version = (current_user.password_version or 0) + 1
    db.commit()
    return {
        "status": "success",
        "access_token": create_access_token(
            {"sub": current_user.username, "pw_ver": current_user.password_version}
        ),
    }


@app.get("/api/users")
async def list_users(
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "user:manage")
    require_password_changed(current_user)
    users = db.query(db_mod.User).all()
    return [{"id": u.id, "username": u.username, "permissions": u.permissions} for u in users]


@app.post("/api/users")
async def create_user(
    data: UserCreate,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "user:manage")
    require_password_changed(current_user)
    if db.query(db_mod.User).filter(db_mod.User.username == data.username).first():
        raise HTTPException(status_code=400, detail="User already exists")
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


@app.delete("/api/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "user:manage")
    require_password_changed(current_user)
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete self")
    user = db.query(db_mod.User).filter(db_mod.User.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()
    return {"status": "success"}


@app.get("/api/vms")
async def get_vms(
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "vm:read")
    require_password_changed(current_user)
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
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "vm:scan")
    require_password_changed(current_user)
    found = await vm_control.scan_for_vms()
    existing = {v.path.lower() for v in db.query(db_mod.VM).all()}
    return [
        {"name": os.path.splitext(os.path.basename(p))[0], "path": p}
        for p in found
        if p.lower() not in existing
    ]


@app.post("/api/vms")
async def add_vm(
    data: VMCreate,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "vm:add")
    require_password_changed(current_user)
    if not os.path.exists(data.path):
        raise HTTPException(status_code=400, detail="VMX not found")
    if db.query(db_mod.VM).filter(db_mod.VM.path == data.path).first():
        raise HTTPException(status_code=400, detail="VM already exists")
    db.add(db_mod.VM(id=str(uuid.uuid4()), name=data.name, path=data.path))
    db.commit()
    return {"status": "success"}


@app.delete("/api/vms/{vm_id}")
async def delete_vm(
    vm_id: str,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "vm:delete")
    require_password_changed(current_user)
    vm = db.query(db_mod.VM).filter(db_mod.VM.id == vm_id).first()
    if vm:
        # Stop all active proxies for this VM before deleting it
        for proxy in vm.proxies:
            await proxy_manager.stop_proxy(proxy.host_port)
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
    # Validate action before checking permissions
    if action not in VALID_VM_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    check_perms(current_user, f"vm:{action}")
    require_password_changed(current_user)
    vm = db.query(db_mod.VM).filter(db_mod.VM.id == vm_id).first()
    if not vm:
        raise HTTPException(status_code=404)

    # Concurrency Lock per VM
    if vm_id not in vm_locks:
        vm_locks[vm_id] = asyncio.Lock()

    async with vm_locks[vm_id]:
        success = False
        if action == "start":
            success = await vm_control.start_vm(vm.path)
        elif action == "stop":
            success = await vm_control.stop_vm(vm.path)
        elif action == "restart":
            success = await vm_control.restart_vm(vm.path)
        if not success:
            raise HTTPException(status_code=500, detail=f"Operation {action} failed.")

    return {"status": "success"}


@app.get("/api/registry")
async def get_registry(
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "vm:read")
    require_password_changed(current_user)
    active = [
        {
            "port": p.host_port,
            "target": f"{p.target_host or 'VM'}:{p.vm_port}",
            "type": "VM" if p.vm_id else "Host",
            "status": "active",
        }
        for p in proxy_manager.proxies.values()
    ]
    blocked = [
        {
            "port": r.port,
            "target": r.description,
            "type": "Blocked",
            "status": "blocked",
        }
        for r in db.query(db_mod.ReservedPort).all()
    ]
    return active + blocked


@app.get("/api/proxies")
async def get_all_proxies(
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "vm:read")
    require_password_changed(current_user)
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
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "proxy:create")
    require_password_changed(current_user)
    found_ports_info = await proxy_manager.scan_host_listening_ports()

    active_ports = set(proxy_manager.proxies.keys())
    blocked_ports = {r.port for r in db.query(db_mod.ReservedPort).all()}

    new_occupied = []
    for info in found_ports_info:
        port = info["port"]
        desc = info["description"]
        if port not in active_ports and port not in blocked_ports:
            db.add(db_mod.ReservedPort(port=port, description=f"Auto-blocked: {desc}"))
            new_occupied.append({"port": port, "description": desc})

    if new_occupied:
        db.commit()

    return new_occupied


@app.post("/api/registry/block")
async def block_port(
    data: PortBlock,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "proxy:create")
    require_password_changed(current_user)
    if data.port in proxy_manager.proxies:
        raise HTTPException(status_code=400, detail="Port active")
    db.add(db_mod.ReservedPort(port=data.port, description=data.description))
    db.commit()
    return {"status": "success"}


@app.delete("/api/registry/block/{port}")
async def unblock_port(
    port: int,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "proxy:delete")
    require_password_changed(current_user)
    res = db.query(db_mod.ReservedPort).filter(db_mod.ReservedPort.port == port).first()
    if res:
        db.delete(res)
        db.commit()
    return {"status": "success"}


@app.post("/api/proxies")
async def create_proxy(
    data: ProxyCreate,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "proxy:create")
    require_password_changed(current_user)
    vm_path = None
    if data.vm_id:
        vm = db.query(db_mod.VM).filter(db_mod.VM.id == data.vm_id).first()
        if not vm:
            raise HTTPException(status_code=404)
        vm_path = vm.path
    if not await proxy_manager.start_proxy(
        data.host_port,
        data.target_port,
        db,
        vm_path=vm_path,
        target_host=data.target_host,
    ):
        raise HTTPException(status_code=400, detail="Port unavailable")
    try:
        db.add(
            db_mod.Proxy(
                id=str(uuid.uuid4()),
                vm_id=data.vm_id,
                target_host=data.target_host,
                host_port=data.host_port,
                vm_port=data.target_port,
                enabled=True,
            )
        )
        db.commit()
    except Exception:
        # Clean up the running proxy if DB insert fails
        await proxy_manager.stop_proxy(data.host_port)
        raise
    return {"status": "success"}


@app.put("/api/proxies/{proxy_id}/toggle")
async def toggle_proxy(
    proxy_id: str,
    current_user: db_mod.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_perms(current_user, "proxy:toggle")
    require_password_changed(current_user)
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
    require_password_changed(current_user)
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

    ssl_certfile = os.environ.get("SSL_CERTFILE")
    ssl_keyfile = os.environ.get("SSL_KEYFILE")
    uvicorn_kwargs = {"host": "0.0.0.0", "port": 8000}
    if ssl_certfile and ssl_keyfile:
        uvicorn_kwargs["ssl_certfile"] = ssl_certfile
        uvicorn_kwargs["ssl_keyfile"] = ssl_keyfile
    uvicorn.run(app, **uvicorn_kwargs)
