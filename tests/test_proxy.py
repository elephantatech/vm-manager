import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from proxy import PortRegistry, TCPProxy, ProxyManager

def test_port_registry_logic():
    with patch("socket.socket") as mock_sock:
        registry = PortRegistry()
        # Test successful registration
        assert registry.register(8080) is True
        assert 8080 in registry.used_ports
        
        # Test duplicate registration
        assert registry.register(8080) is False
        
        # Test unregistration
        registry.unregister(8080)
        assert 8080 not in registry.used_ports

@pytest.mark.asyncio
async def test_tcp_proxy_start_stop():
    get_ip = AsyncMock(return_value="192.168.1.100")
    proxy = TCPProxy(8080, "vm1", 80, get_ip)
    
    with patch("asyncio.start_server", new_callable=AsyncMock) as mock_start_server, \
         patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
        
        mock_shell.return_value.communicate.return_value = (b"", b"")
        await proxy.start()
        
        assert proxy._running is True
        mock_start_server.assert_called_once()
        # Check firewall rule was added
        mock_shell.assert_called_once()
        assert "add rule" in mock_shell.call_args[0][0]
        
        await proxy.stop()
        assert proxy._running is False

@pytest.mark.asyncio
async def test_proxy_manager():
    get_ip = AsyncMock(return_value="192.168.1.100")
    manager = ProxyManager(get_ip)
    
    with patch("proxy.TCPProxy.start", new_callable=AsyncMock) as mock_start, \
         patch("proxy.PortRegistry.register", return_value=True):
        
        success = await manager.start_proxy(8080, "vm1", 80)
        assert success is True
        assert 8080 in manager.proxies
        
        with patch("proxy.TCPProxy.stop", new_callable=AsyncMock) as mock_stop:
            await manager.stop_proxy(8080)
            assert 8080 not in manager.proxies
            mock_stop.assert_called_once()
