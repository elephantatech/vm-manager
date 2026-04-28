import os
import ctypes
import getpass
import uuid
import sys
from typing import Optional, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel

from logger_config import logger
from security import verify_password, hash_password, create_access_token
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
    "user_manage": "user:manage"
}

# Grouped Permissions
GROUPS = {
    "admin": "*",
    "vm_operator": "vm:read,vm:start,vm:stop,vm:restart,proxy:toggle",
    "vm_manager": "vm:read,vm:start,vm:stop,vm:restart,vm:add,vm:scan,proxy:toggle,proxy:create,proxy:delete",
    "viewer": "vm:read"
}

# --- Models for API ---

class UserCreate(BaseModel):
    username: str
    password: str
    permissions: str # comma separated or group name

class PasswordChange(BaseModel):
    old_password: str
    new_password: str

# --- Application Setup ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    db = db_mod.SessionLocal()
    try:
        vms = db.query(db_mod.VM).all()
        for vm in vms:
            for p in vm.proxies:
                if p.enabled:
                    logger.info({"event": "restoring_proxy", "port": p.host_port})
                    await proxy_manager.start_proxy(p.host_port, vm.path, p.vm_port)
    finally:
        db.close()
    yield
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

# Initialize DB schema before global queries
db_mod.init_db()

_init_db = db_mod.SessionLocal()
setting = _init_db.query(db_mod.Setting).filter(db_mod.Setting.key == "vmrun_path").first()
vmrun_path = setting.value if setting else r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe"
_init_db.close()

vm_control = VMControl(vmrun_path)
proxy_manager = ProxyManager(vm_control.get_guest_ip)

# --- Auth & RBAC Logic ---

def bootstrap_admin(db: Session):
    # Only bootstrap if there are NO users at all
    user_count = db.query(db_mod.User).count()
    if user_count == 0:
        logger.info({"event": "bootstrapping_admin_user"})
        hashed_pwd = hash_password("admin")
        db.add(db_mod.User(username="admin", hashed_password=hashed_pwd, permissions="*"))
        db.commit()

# Pre-flight
if os.environ.get("TESTING") != "1":
    _boot_db = db_mod.SessionLocal()
    bootstrap_admin(_boot_db)
    _boot_db.close()

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

if os.environ.get("TESTING") != "1" and not is_admin():
    logger.critical({"event": "admin_check_failed", "message": "Script must be run as Administrator."})
    print("WARNING: Not running as Administrator. Firewall management will fail.")

# Middleware for LAN only access
@app.middleware("http")
async def lan_only_middleware(request: Request, call_next):
    client_ip = request.client.host
    is_private = False
    if client_ip in ["127.0.0.1", "::1", "testclient"]:
        is_private = True
    elif client_ip.startswith("192.168.") or client_ip.startswith("10."):
        is_private = True
    elif client_ip.startswith("172."):
        parts = client_ip.split(".")
        if len(parts) >= 2 and 16 <= int(parts[1]) <= 31:
            is_private = True
    
    if not is_private:
        logger.warning({"event": "unauthorized_external_access", "ip": client_ip})
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": "Forbidden: LAN access only"})
    return await call_next(request)

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> db_mod.User:
    from security import ALGORITHM, SECRET_KEY
    from jose import jwt
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    user = db.query(db_mod.User).filter(db_mod.User.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

def check_permissions(user: db_mod.User, required: str):
    if user.permissions == "*":
        return True
    user_perms = set(user.permissions.split(","))
    if required in user_perms:
        return True
    raise HTTPException(status_code=403, detail=f"Missing permission: {required}")

# --- Routes ---

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(db_mod.User).filter(db_mod.User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer", "permissions": user.permissions}

@app.post("/api/user/change-password")
async def change_password(data: PasswordChange, current_user: db_mod.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(data.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect old password")
    current_user.hashed_password = hash_password(data.new_password)
    db.commit()
    return {"status": "success"}

@app.post("/api/users")
async def create_user(data: UserCreate, current_user: db_mod.User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_permissions(current_user, "user:manage")
    if db.query(db_mod.User).filter(db_mod.User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    
    perms = data.permissions
    if perms in GROUPS:
        perms = GROUPS[perms]
        
    new_user = db_mod.User(username=data.username, hashed_password=hash_password(data.password), permissions=perms)
    db.add(new_user)
    db.commit()
    return {"status": "success"}

@app.get("/api/vms")
async def get_vms(current_user: db_mod.User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_permissions(current_user, "vm:read")
    db_vms = db.query(db_mod.VM).all()
    vms_with_status = []
    for vm in db_vms:
        vm_status = await vm_control.get_status(vm.path)
        vms_with_status.append({
            "id": vm.id,
            "name": vm.name,
            "path": vm.path,
            "status": vm_status,
            "proxies": [
                {"id": p.id, "host_port": p.host_port, "vm_port": p.vm_port, "enabled": p.enabled}
                for p in vm.proxies
            ]
        })
    return vms_with_status

@app.post("/api/vms/scan")
async def scan_vms(current_user: db_mod.User = Depends(get_current_user)):
    check_permissions(current_user, "vm:scan")
    found_paths = await vm_control.scan_for_vms()
    existing_paths = {v.path.lower() for v in db_mod.SessionLocal().query(db_mod.VM).all()}
    new_vms = []
    for path in found_paths:
        if path.lower() not in existing_paths:
            name = os.path.splitext(os.path.basename(path))[0]
            new_vms.append({"name": name, "path": path})
    return new_vms

@app.post("/api/vms")
async def add_vm(name: str, path: str, current_user: db_mod.User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_permissions(current_user, "vm:add")
    if not os.path.exists(path):
        raise HTTPException(status_code=400, detail="VMX file not found")
    new_vm = db_mod.VM(id=str(uuid.uuid4()), name=name, path=path)
    db.add(new_vm)
    db.commit()
    return {"id": new_vm.id}

@app.delete("/api/vms/{vm_id}")
async def delete_vm(vm_id: str, current_user: db_mod.User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_permissions(current_user, "vm:delete")
    vm = db.query(db_mod.VM).filter(db_mod.VM.id == vm_id).first()
    if vm:
        db.delete(vm)
        db.commit()
    return {"status": "success"}

@app.post("/api/vms/{vm_id}/{action}")
async def control_vm(vm_id: str, action: str, current_user: db_mod.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if action == "start": check_permissions(current_user, "vm:start")
    elif action == "stop": check_permissions(current_user, "vm:stop")
    elif action == "restart": check_permissions(current_user, "vm:restart")
    
    vm = db.query(db_mod.VM).filter(db_mod.VM.id == vm_id).first()
    if not vm: raise HTTPException(status_code=404, detail="VM not found")
    
    success = False
    if action == "start": success = await vm_control.start_vm(vm.path)
    elif action == "stop": success = await vm_control.stop_vm(vm.path)
    elif action == "restart": success = await vm_control.restart_vm(vm.path)
    
    if not success: raise HTTPException(status_code=500, detail=f"Failed to {action} VM")
    return {"status": "success"}

@app.get("/api/registry")
async def get_port_registry(current_user: db_mod.User = Depends(get_current_user)):
    return {
        "used_ports": list(proxy_manager.registry.used_ports),
        "active_proxies": [
            {"port": p.host_port, "vm_id": p.vm_id, "vm_port": p.vm_port}
            for p in proxy_manager.proxies.values()
        ]
    }

@app.post("/api/proxies")
async def create_proxy(vm_id: str, host_port: int, vm_port: int, current_user: db_mod.User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_permissions(current_user, "proxy:create")
    vm = db_mod.VM # Fixed name collision error
    vm = db.query(db_mod.VM).filter(db_mod.VM.id == vm_id).first()
    if not vm: raise HTTPException(status_code=404, detail="VM not found")
    
    success = await proxy_manager.start_proxy(host_port, vm.path, vm_port)
    if not success: raise HTTPException(status_code=400, detail="Port conflict or IP unavailable")
    
    new_proxy = db_mod.Proxy(id=str(uuid.uuid4()), vm_id=vm_id, host_port=host_port, vm_port=vm_port, enabled=True)
    db.add(new_proxy)
    db.commit()
    return {"id": new_proxy.id}

@app.put("/api/proxies/{proxy_id}/toggle")
async def toggle_proxy(proxy_id: str, current_user: db_mod.User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_permissions(current_user, "proxy:toggle")
    proxy = db.query(db_mod.Proxy).filter(db_mod.Proxy.id == proxy_id).first()
    if not proxy: raise HTTPException(status_code=404, detail="Proxy not found")
    
    proxy.enabled = not proxy.enabled
    if proxy.enabled:
        success = await proxy_manager.start_proxy(proxy.host_port, proxy.vm.path, proxy.vm_port)
        if not success:
            proxy.enabled = False
            db.commit()
            raise HTTPException(status_code=400, detail="Failed to start proxy")
    else:
        await proxy_manager.stop_proxy(proxy.host_port)
    db.commit()
    return {"id": proxy.id, "enabled": proxy.enabled}

@app.delete("/api/proxies/{proxy_id}")
async def delete_proxy(proxy_id: str, current_user: db_mod.User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_permissions(current_user, "proxy:delete")
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
