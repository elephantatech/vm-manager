from pydantic import BaseModel
from typing import List, Optional


class ProxyConfig(BaseModel):
    id: str
    vm_id: str
    host_port: int
    vm_port: int
    enabled: bool = True


class VMConfig(BaseModel):
    id: str
    name: str
    path: str
    proxies: List[ProxyConfig] = []


class AppConfig(BaseModel):
    vmrun_path: str = r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe"
    vms: List[VMConfig] = []
    auth_hashed_password: Optional[str] = None
    auth_username: Optional[str] = None
