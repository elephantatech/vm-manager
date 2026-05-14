import asyncio
import socket
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

import database as db_mod
from logger_config import logger


class PortRegistry:
    def __init__(self):
        self.active_ports = set()

    def is_port_available(self, port: int, db: Session) -> bool:
        # 1. Check in-memory active proxies
        if port in self.active_ports:
            return False

        # 2. Check Database for persistent reservations/blocks
        reserved = db.query(db_mod.ReservedPort).filter(db_mod.ReservedPort.port == port).first()
        if reserved:
            return False

        # 3. Check if OS port is actually bindable
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("0.0.0.0", port))
            return True
        except socket.error:
            return False

    def register(self, port: int):
        self.active_ports.add(port)

    def unregister(self, port: int):
        if port in self.active_ports:
            self.active_ports.remove(port)


class TCPProxy:
    def __init__(
        self,
        host_port: int,
        target_port: int,
        vm_id: Optional[str] = None,
        target_host: Optional[str] = None,
        get_vm_ip_func=None,
    ):
        self.host_port = host_port
        self.vm_id = vm_id
        self.target_port = target_port
        self.target_host = target_host  # Static host if not a VM
        self.get_vm_ip_func = get_vm_ip_func
        self.server: Optional[asyncio.Server] = None
        self._running = False

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        target_ip = self.target_host

        if self.vm_id and self.get_vm_ip_func:
            target_ip = await self.get_vm_ip_func(self.vm_id)

        if not target_ip:
            logger.error(
                {
                    "event": "proxy_failed_no_target_ip",
                    "vm_id": self.vm_id,
                    "host": self.target_host,
                }
            )
            writer.close()
            await writer.wait_closed()
            return

        try:
            remote_reader, remote_writer = await asyncio.open_connection(
                target_ip, self.target_port
            )
        except Exception as e:
            logger.error(
                {
                    "event": "proxy_remote_connection_failed",
                    "target": f"{target_ip}:{self.target_port}",
                    "error": str(e),
                }
            )
            writer.close()
            await writer.wait_closed()
            return

        async def pipe(local_reader, remote_writer):
            try:
                while True:
                    data = await local_reader.read(4096)
                    if not data:
                        break
                    remote_writer.write(data)
                    await remote_writer.drain()
            except Exception:
                pass
            finally:
                remote_writer.close()
                try:
                    await remote_writer.wait_closed()
                except Exception:
                    pass

        asyncio.create_task(pipe(reader, remote_writer))
        asyncio.create_task(pipe(remote_reader, writer))

    async def start(self):
        if self._running:
            return

        # If the firewall rule cannot be added, the listener would still come up
        # but LAN clients would be silently blocked — exactly the failure mode
        # the system is meant to prevent. Fail loud instead.
        if not await self._add_firewall_rule():
            raise RuntimeError(
                f"Failed to add firewall rule for port {self.host_port} "
                f"(requires administrator privileges)"
            )

        try:
            self.server = await asyncio.start_server(self._handle_client, "0.0.0.0", self.host_port)
            self._running = True
            logger.info(
                {
                    "event": "proxy_started",
                    "port": self.host_port,
                    "target": f"{self.target_host or 'VM'}:{self.target_port}",
                }
            )
            asyncio.create_task(self.server.serve_forever())
        except Exception as e:
            logger.error({"event": "proxy_start_failed", "port": self.host_port, "error": str(e)})
            await self._remove_firewall_rule()
            raise e

    async def stop(self):
        if not self._running:
            return

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        await self._remove_firewall_rule()
        self._running = False
        logger.info({"event": "proxy_stopped", "port": self.host_port})

    async def _add_firewall_rule(self) -> bool:
        rule_name = f"VMProxy_{self.host_port}"
        cmd = f'netsh advfirewall firewall add rule name="{rule_name}" dir=in action=allow protocol=TCP localport={self.host_port} remoteip=localsubnet'
        logger.debug({"event": "firewall_add_rule", "command": cmd})
        process = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            logger.error(
                {
                    "event": "firewall_add_rule_failed",
                    "port": self.host_port,
                    "returncode": process.returncode,
                    "stderr": stderr.decode("utf-8", errors="ignore"),
                }
            )
            return False
        return True

    async def _remove_firewall_rule(self) -> bool:
        rule_name = f"VMProxy_{self.host_port}"
        cmd = f'netsh advfirewall firewall delete rule name="{rule_name}"'
        logger.debug({"event": "firewall_remove_rule", "command": cmd})
        process = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            # Removal failure is non-fatal but worth knowing — usually means the rule
            # was already gone or netsh isn't installed.
            logger.warning(
                {
                    "event": "firewall_remove_rule_failed",
                    "port": self.host_port,
                    "returncode": process.returncode,
                    "stderr": stderr.decode("utf-8", errors="ignore"),
                }
            )
            return False
        return True


class ProxyManager:
    def __init__(self, get_vm_ip_func):
        self.proxies: Dict[int, TCPProxy] = {}
        self.registry = PortRegistry()
        self.get_vm_ip_func = get_vm_ip_func

    async def start_proxy(
        self,
        host_port: int,
        target_port: int,
        db: Session,
        vm_path: Optional[str] = None,
        target_host: Optional[str] = None,
    ):
        if host_port in self.proxies:
            return False

        if not self.registry.is_port_available(host_port, db):
            logger.error({"event": "port_availability_check_failed", "port": host_port})
            return False

        proxy = TCPProxy(
            host_port,
            target_port,
            vm_id=vm_path,
            target_host=target_host,
            get_vm_ip_func=self.get_vm_ip_func,
        )
        try:
            await proxy.start()
            self.proxies[host_port] = proxy
            self.registry.register(host_port)
            return True
        except Exception as e:
            logger.error(
                {
                    "event": "start_proxy_failed",
                    "port": host_port,
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
            )
            return False

    async def stop_proxy(self, host_port: int):
        if host_port in self.proxies:
            await self.proxies[host_port].stop()
            del self.proxies[host_port]
            self.registry.unregister(host_port)
            return True
        return False

    async def scan_host_listening_ports(self) -> List[Dict]:
        cmd_ports = "$conns = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue; $results = @(); foreach ($c in $conns) { $pName = 'Unknown Process'; if ($c.OwningProcess -gt 0) { $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue; if ($p) { $pName = $p.ProcessName } }; $results += [PSCustomObject]@{ Port = $c.LocalPort; Description = 'Process: ' + $pName } }; $fwRules = Get-NetFirewallRule -Action Allow -Direction Inbound -Enabled True -ErrorAction SilentlyContinue; foreach ($r in $fwRules) { $portFilter = $r | Get-NetFirewallPortFilter -ErrorAction SilentlyContinue; if ($portFilter -and $portFilter.LocalPort -match '^\\d+$') { $results += [PSCustomObject]@{ Port = [int]$portFilter.LocalPort; Description = 'Firewall Rule: ' + $r.DisplayName } } }; @($results | Select-Object -Property Port, Description -Unique) | ConvertTo-Json -Compress"
        process = await asyncio.create_subprocess_shell(
            f'powershell.exe -Command "{cmd_ports}"',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()

        ports_info = []
        if process.returncode == 0 and stdout:
            import json

            try:
                data = json.loads(stdout.decode("utf-8", errors="ignore"))
                if isinstance(data, list):
                    ports_info = data
                elif isinstance(data, dict):
                    ports_info = [data]
            except Exception as e:
                logger.error({"event": "scan_ports_json_error", "error": str(e)})

        # Deduplicate and combine descriptions by port
        port_dict = {}
        for item in ports_info:
            p = item.get("Port")
            desc = item.get("Description", "")
            if p:
                if p in port_dict:
                    if desc not in port_dict[p]:
                        port_dict[p] += f" | {desc}"
                else:
                    port_dict[p] = desc

        return [{"port": k, "description": v} for k, v in port_dict.items()]
