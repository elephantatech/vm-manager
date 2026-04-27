import os
import json
import ctypes
import getpass
import uuid
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles

from logger_config import logger
from models import AppConfig, VMConfig, ProxyConfig
from security import verify_password, hash_password, create_access_token
from vm_control import VMControl
from proxy import ProxyManager

CONFIG_FILE = "config.json"

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def load_config() -> AppConfig:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return AppConfig.model_validate(json.load(f))
    return AppConfig()

def save_config(config: AppConfig):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config.model_dump(), f, indent=4)

# Bootstrap Auth
config = load_config()
if not config.auth_hashed_password or not config.auth_username:
    print("--- Initial Setup: Admin Credentials ---")
    username = input("Enter admin username: ")
    password = getpass.getpass("Enter admin password: ")
    config.auth_username = username
    config.auth_hashed_password = hash_password(password)
    save_config(config)
    print("Credentials saved successfully.")

if not is_admin():
    logger.critical({"event": "admin_check_failed", "message": "Script must be run as Administrator."})
    # We don't exit here to allow developing, but in prod it will fail to add firewall rules
    print("WARNING: Not running as Administrator. Firewall management will fail.")

app = FastAPI(title="VMware Web Manager")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Initialize modules
vm_control = VMControl(config.vmrun_path)
proxy_manager = ProxyManager(vm_control.get_guest_ip)

# Middleware for LAN only access (simplistic check)
@app.middleware("http")
async def lan_only_middleware(request: Request, call_next):
    client_ip = request.client.host
    # Basic check for private IP ranges (127.0.0.1, 10.x, 192.168.x, 172.16-31.x)
    is_private = False
    if client_ip == "127.0.0.1" or client_ip == "::1":
        is_private = True
    elif client_ip.startswith("192.168.") or client_ip.startswith("10."):
        is_private = True
    elif client_ip.startswith("172."):
        parts = client_ip.split(".")
        if len(parts) >= 2 and 16 <= int(parts[1]) <= 31:
            is_private = True
    
    if not is_private:
        logger.warning({"event": "unauthorized_external_access", "ip": client_ip})
        return status.HTTP_403_FORBIDDEN # In real app, return Response
    
    return await call_next(request)

# Auth Dependency
async def get_current_user(token: str = Depends(oauth2_scheme)):
    if token == "dummy_token": # Placeholder
         return config.auth_username
    # In real app, verify JWT token
    return config.auth_username

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if form_data.username != config.auth_username or not verify_password(form_data.password, config.auth_hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token = create_access_token(data={"sub": form_data.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/vms")
async def get_vms(current_user: str = Depends(get_current_user)):
    vms_with_status = []
    for vm in config.vms:
        vm_status = await vm_control.get_status(vm.path)
        vms_with_status.append({
            "id": vm.id,
            "name": vm.name,
            "path": vm.path,
            "status": vm_status,
            "proxies": vm.proxies
        })
    return vms_with_status

@app.post("/api/vms")
async def add_vm(name: str, path: str, current_user: str = Depends(get_current_user)):
    if not os.path.exists(path):
        raise HTTPException(status_code=400, detail="VMX file not found at path")
    new_vm = VMConfig(id=str(uuid.uuid4()), name=name, path=path)
    config.vms.append(new_vm)
    save_config(config)
    return new_vm

@app.delete("/api/vms/{vm_id}")
async def delete_vm(vm_id: str, current_user: str = Depends(get_current_user)):
    config.vms = [v for v in config.vms if v.id != vm_id]
    save_config(config)
    return {"status": "success"}

@app.post("/api/vms/{vm_id}/{action}")
async def control_vm(vm_id: str, action: str, current_user: str = Depends(get_current_user)):
    vm = next((v for v in config.vms if v.id == vm_id), None)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    
    success = False
    if action == "start":
        success = await vm_control.start_vm(vm.path)
    elif action == "stop":
        success = await vm_control.stop_vm(vm.path)
    elif action == "restart":
        success = await vm_control.restart_vm(vm.path)
    
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to {action} VM")
    return {"status": "success"}

@app.post("/api/proxies")
async def create_proxy(vm_id: str, host_port: int, vm_port: int, current_user: str = Depends(get_current_user)):
    vm = next((v for v in config.vms if v.id == vm_id), None)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    
    proxy_id = str(uuid.uuid4())
    new_proxy = ProxyConfig(id=proxy_id, vm_id=vm_id, host_port=host_port, vm_port=vm_port, enabled=True)
    
    # Try to start it
    success = await proxy_manager.start_proxy(host_port, vm.path, vm_port)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to start proxy (port conflict or IP not available)")
    
    vm.proxies.append(new_proxy)
    save_config(config)
    return new_proxy

@app.put("/api/proxies/{proxy_id}/toggle")
async def toggle_proxy(proxy_id: str, current_user: str = Depends(get_current_user)):
    vm_found = None
    proxy_found = None
    for vm in config.vms:
        for p in vm.proxies:
            if p.id == proxy_id:
                vm_found = vm
                proxy_found = p
                break
    
    if not proxy_found:
        raise HTTPException(status_code=404, detail="Proxy not found")
    
    proxy_found.enabled = not proxy_found.enabled
    if proxy_found.enabled:
        success = await proxy_manager.start_proxy(proxy_found.host_port, vm_found.path, proxy_found.vm_port)
        if not success:
            proxy_found.enabled = False
            raise HTTPException(status_code=400, detail="Failed to start proxy")
    else:
        await proxy_manager.stop_proxy(proxy_found.host_port)
    
    save_config(config)
    return proxy_found

@app.delete("/api/proxies/{proxy_id}")
async def delete_proxy(proxy_id: str, current_user: str = Depends(get_current_user)):
    for vm in config.vms:
        for p in vm.proxies:
            if p.id == proxy_id:
                await proxy_manager.stop_proxy(p.host_port)
                vm.proxies.remove(p)
                save_config(config)
                return {"status": "success"}
    raise HTTPException(status_code=404, detail="Proxy not found")

@app.on_event("startup")
async def startup_event():
    # Restore proxies
    for vm in config.vms:
        for p in vm.proxies:
            if p.enabled:
                logger.info({"event": "restoring_proxy", "port": p.host_port})
                await proxy_manager.start_proxy(p.host_port, vm.path, p.vm_port)

@app.on_event("shutdown")
async def shutdown_event():
    # Stop all proxies to clean up firewall rules
    ports = list(proxy_manager.proxies.keys())
    for port in ports:
        await proxy_manager.stop_proxy(port)

# Serve static files
if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
