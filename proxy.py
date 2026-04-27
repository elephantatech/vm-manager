import asyncio
import socket
from typing import Dict, Optional
from logger_config import logger

class PortRegistry:
    def __init__(self):
        self.used_ports = set()

    def register(self, port: int) -> bool:
        if port in self.used_ports:
            return False
        # Check if port is actually available on the system
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', port))
            self.used_ports.add(port)
            return True
        except socket.error:
            return False

    def unregister(self, port: int):
        if port in self.used_ports:
            self.used_ports.remove(port)

class TCPProxy:
    def __init__(self, host_port: int, vm_id: str, vm_port: int, get_vm_ip_func):
        self.host_port = host_port
        self.vm_id = vm_id
        self.vm_port = vm_port
        self.get_vm_ip_func = get_vm_ip_func
        self.server: Optional[asyncio.Server] = None
        self._running = False

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        vm_ip = await self.get_vm_ip_func(self.vm_id)
        if not vm_ip:
            logger.error({"event": "proxy_failed_no_vm_ip", "vm_id": self.vm_id})
            writer.close()
            await writer.wait_closed()
            return

        try:
            remote_reader, remote_writer = await asyncio.open_connection(vm_ip, self.vm_port)
        except Exception as e:
            logger.error({"event": "proxy_remote_connection_failed", "vm_ip": vm_ip, "port": self.vm_port, "error": str(e)})
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
        
        # Add Firewall Rule
        await self._add_firewall_rule()

        try:
            self.server = await asyncio.start_server(self._handle_client, '0.0.0.0', self.host_port)
            self._running = True
            logger.info({"event": "proxy_started", "port": self.host_port, "vm_id": self.vm_id, "vm_port": self.vm_port})
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

    async def _add_firewall_rule(self):
        rule_name = f"VMProxy_{self.host_port}"
        cmd = f'netsh advfirewall firewall add rule name="{rule_name}" dir=in action=allow protocol=TCP localport={self.host_port} remoteip=localsubnet'
        logger.info({"event": "firewall_add_rule", "command": cmd})
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()

    async def _remove_firewall_rule(self):
        rule_name = f"VMProxy_{self.host_port}"
        cmd = f'netsh advfirewall firewall delete rule name="{rule_name}"'
        logger.info({"event": "firewall_remove_rule", "command": cmd})
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()

class ProxyManager:
    def __init__(self, get_vm_ip_func):
        self.proxies: Dict[int, TCPProxy] = {}
        self.registry = PortRegistry()
        self.get_vm_ip_func = get_vm_ip_func

    async def start_proxy(self, host_port: int, vm_id: str, vm_port: int):
        if host_port in self.proxies:
            return False
        
        if not self.registry.register(host_port):
            logger.error({"event": "port_registration_failed", "port": host_port})
            return False
        
        proxy = TCPProxy(host_port, vm_id, vm_port, self.get_vm_ip_func)
        try:
            await proxy.start()
            self.proxies[host_port] = proxy
            return True
        except Exception:
            self.registry.unregister(host_port)
            return False

    async def stop_proxy(self, host_port: int):
        if host_port in self.proxies:
            await self.proxies[host_port].stop()
            del self.proxies[host_port]
            self.registry.unregister(host_port)
            return True
        return False
