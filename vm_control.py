import asyncio
import os
from typing import Optional, List
from logger_config import logger

class VMControl:
    def __init__(self, vmrun_path: str):
        self.vmrun_path = vmrun_path

    async def _run_vmrun(self, args: List[str]) -> tuple[int, str, str]:
        logger.info({"event": "vmrun_command", "args": args})
        process = await asyncio.create_subprocess_exec(
            self.vmrun_path,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        return process.returncode, stdout.decode().strip(), stderr.decode().strip()

    async def start_vm(self, vmx_path: str, mode: str = "nogui") -> bool:
        returncode, stdout, stderr = await self._run_vmrun(["-T", "ws", "start", vmx_path, mode])
        if returncode != 0:
            logger.error({"event": "vmrun_start_failed", "vmx": vmx_path, "error": stderr})
            return False
        return True

    async def stop_vm(self, vmx_path: str, mode: str = "soft") -> bool:
        returncode, stdout, stderr = await self._run_vmrun(["-T", "ws", "stop", vmx_path, mode])
        if returncode != 0:
            logger.warning({"event": "vmrun_soft_stop_failed", "vmx": vmx_path, "error": stderr, "message": "Retrying with hard stop..."})
            # Fallback to hard power off if soft fails
            returncode, stdout, stderr = await self._run_vmrun(["-T", "ws", "stop", vmx_path, "hard"])
            if returncode != 0:
                logger.error({"event": "vmrun_hard_stop_failed", "vmx": vmx_path, "error": stderr})
                return False
        return True

    async def restart_vm(self, vmx_path: str, mode: str = "soft") -> bool:
        returncode, stdout, stderr = await self._run_vmrun(["-T", "ws", "reset", vmx_path, mode])
        if returncode != 0:
            logger.warning({"event": "vmrun_soft_reset_failed", "vmx": vmx_path, "error": stderr, "message": "Retrying with hard reset..."})
            # Fallback to hard reset if soft fails (e.g. VMware Tools not running)
            returncode, stdout, stderr = await self._run_vmrun(["-T", "ws", "reset", vmx_path, "hard"])
            if returncode != 0:
                logger.error({"event": "vmrun_hard_reset_failed", "vmx": vmx_path, "error": stderr})
                return False
        return True

    async def get_status(self, vmx_path: str) -> str:
        returncode, stdout, stderr = await self._run_vmrun(["-T", "ws", "list"])
        if returncode == 0:
            target_norm = os.path.normpath(os.path.abspath(vmx_path)).lower()
            lines = stdout.splitlines()
            # Skip the "Total running VMs" header
            for line in lines[1:]:
                if not line.strip():
                    continue
                line_norm = os.path.normpath(os.path.abspath(line.strip())).lower()
                if target_norm == line_norm:
                    return "running"
        
        logger.debug({"event": "status_check_stopped", "vmx": vmx_path, "stdout": stdout})
        return "stopped"

    async def get_guest_ip(self, vmx_path: str) -> Optional[str]:
        returncode, stdout, stderr = await self._run_vmrun(["-T", "ws", "getGuestIPAddress", vmx_path])
        if returncode == 0 and stdout:
            # Sometimes it returns multiple lines or extra text
            lines = stdout.splitlines()
            if lines:
                ip = lines[-1].strip()
                if ip and not ip.startswith("Error"):
                    return ip
        logger.warning({"event": "vmrun_get_ip_failed", "vmx": vmx_path, "error": stderr, "stdout": stdout})
        return None

    async def scan_for_vms(self) -> List[str]:
        found_vms = []
        logger.info({"event": "scan_started"})
        
        # 1. Check currently running VMs via vmrun list (Live)
        returncode, stdout, stderr = await self._run_vmrun(["-T", "ws", "list"])
        if returncode == 0:
            lines = stdout.splitlines()
            if len(lines) > 1:
                for path in lines[1:]:
                    clean_path = path.strip()
                    if clean_path and os.path.exists(clean_path):
                        found_vms.append(os.path.abspath(clean_path))
            logger.info({"event": "live_scan_completed", "count": len(found_vms)})
        else:
            logger.warning({"event": "live_scan_failed", "error": stderr})

        # 2. Check VMware's official inventory file in all user profiles
        users_dir = "C:\\Users"
        if os.path.exists(users_dir):
            try:
                user_folders = os.listdir(users_dir)
            except Exception as e:
                logger.error({"event": "users_dir_list_failed", "error": str(e)})
                user_folders = []

            for user_folder in user_folders:
                inventory_file = os.path.join(users_dir, user_folder, "AppData", "Roaming", "VMware", "inventory.vmls")
                if os.path.exists(inventory_file):
                    logger.info({"event": "reading_inventory", "path": inventory_file})
                    try:
                        with open(inventory_file, "r", encoding="utf-8", errors="ignore") as f:
                            for line in f:
                                if ".config =" in line:
                                    path = line.split("=", 1)[1].strip().strip('"')
                                    if path and path.lower().endswith(".vmx") and os.path.exists(path):
                                        found_vms.append(os.path.abspath(path))
                    except Exception as e:
                        logger.error({"event": "inventory_read_failed", "path": inventory_file, "error": str(e)})

        # 3. Search common fallback paths in all user profiles
        search_subpaths = [
            os.path.join("Documents", "Virtual Machines"),
            os.path.join("Documents", "Shared Virtual Machines"),
        ]
        
        for user_folder in user_folders:
            for subpath in search_subpaths:
                try:
                    base_path = os.path.join(users_dir, user_folder, subpath)
                    if not os.path.exists(base_path):
                        continue
                    
                    logger.info({"event": "scanning_directory", "path": base_path})
                    for root, dirs, files in os.walk(base_path):
                        for file in files:
                            if file.lower().endswith(".vmx"):
                                found_vms.append(os.path.abspath(os.path.join(root, file)))
                except Exception as e:
                    logger.warning({"event": "directory_scan_failed", "user": user_folder, "error": str(e)})
        
        results = list(set(found_vms))
        logger.info({"event": "scan_completed", "total_found": len(results)})
        return results
