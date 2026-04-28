import pytest
from unittest.mock import AsyncMock, patch
from vm_control import VMControl

@pytest.fixture
def vm_control():
    return VMControl("fake/vmrun.exe")

@pytest.mark.asyncio
async def test_start_vm_success(vm_control):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0
        mock_exec.return_value = mock_process
        
        success = await vm_control.start_vm("test.vmx")
        assert success is True
        mock_exec.assert_called_once()

@pytest.mark.asyncio
async def test_start_vm_failure(vm_control):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"Some error")
        mock_process.returncode = 1
        mock_exec.return_value = mock_process
        
        success = await vm_control.start_vm("test.vmx")
        assert success is False

@pytest.mark.asyncio
async def test_get_status_running(vm_control):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"Total running VMs: 1\ntest.vmx", b"")
        mock_process.returncode = 0
        mock_exec.return_value = mock_process
        
        status = await vm_control.get_status("test.vmx")
        assert status == "running"

@pytest.mark.asyncio
async def test_get_guest_ip(vm_control):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"192.168.1.100", b"")
        mock_process.returncode = 0
        mock_exec.return_value = mock_process
        
        ip = await vm_control.get_guest_ip("test.vmx")
        assert ip == "192.168.1.100"
