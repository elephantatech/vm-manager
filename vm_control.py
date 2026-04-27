import asyncio
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
            logger.error({"event": "vmrun_stop_failed", "vmx": vmx_path, "error": stderr})
            return False
        return True

    async def restart_vm(self, vmx_path: str, mode: str = "soft") -> bool:
        returncode, stdout, stderr = await self._run_vmrun(["-T", "ws", "reset", vmx_path, mode])
        if returncode != 0:
            logger.error({"event": "vmrun_reset_failed", "vmx": vmx_path, "error": stderr})
            return False
        return True

    async def get_status(self, vmx_path: str) -> str:
        # vmrun list doesn't take a vmx directly to check status easily, 
        # it lists all running. We check if vmx_path is in the list.
        returncode, stdout, stderr = await self._run_vmrun(["-T", "ws", "list"])
        if returncode == 0:
            if vmx_path.lower() in stdout.lower():
                return "running"
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
