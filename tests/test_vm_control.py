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
        mock_process.communicate.return_value = (
            b"Total running VMs: 1\ntest.vmx",
            b"",
        )
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


# --- New: stop_vm soft->hard fallback ---


@pytest.mark.asyncio
async def test_stop_vm_soft_success(vm_control):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        success = await vm_control.stop_vm("test.vmx")
        assert success is True
        # Should only be called once (soft stop succeeded)
        assert mock_exec.call_count == 1


@pytest.mark.asyncio
async def test_stop_vm_soft_fails_hard_succeeds(vm_control):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        soft_fail = AsyncMock()
        soft_fail.communicate.return_value = (b"", b"VMware Tools not running")
        soft_fail.returncode = 1

        hard_success = AsyncMock()
        hard_success.communicate.return_value = (b"", b"")
        hard_success.returncode = 0

        mock_exec.side_effect = [soft_fail, hard_success]

        success = await vm_control.stop_vm("test.vmx")
        assert success is True
        assert mock_exec.call_count == 2


@pytest.mark.asyncio
async def test_stop_vm_both_fail(vm_control):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        fail_process = AsyncMock()
        fail_process.communicate.return_value = (b"", b"Error")
        fail_process.returncode = 1
        mock_exec.return_value = fail_process

        success = await vm_control.stop_vm("test.vmx")
        assert success is False


# --- New: restart_vm soft->hard fallback ---


@pytest.mark.asyncio
async def test_restart_vm_soft_success(vm_control):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        success = await vm_control.restart_vm("test.vmx")
        assert success is True
        assert mock_exec.call_count == 1


@pytest.mark.asyncio
async def test_restart_vm_soft_fails_hard_succeeds(vm_control):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        soft_fail = AsyncMock()
        soft_fail.communicate.return_value = (b"", b"Failed")
        soft_fail.returncode = 1

        hard_success = AsyncMock()
        hard_success.communicate.return_value = (b"", b"")
        hard_success.returncode = 0

        mock_exec.side_effect = [soft_fail, hard_success]

        success = await vm_control.restart_vm("test.vmx")
        assert success is True
        assert mock_exec.call_count == 2


@pytest.mark.asyncio
async def test_restart_vm_both_fail(vm_control):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        fail_process = AsyncMock()
        fail_process.communicate.return_value = (b"", b"Error")
        fail_process.returncode = 1
        mock_exec.return_value = fail_process

        success = await vm_control.restart_vm("test.vmx")
        assert success is False


# --- New: scan_for_vms three-layer discovery ---


@pytest.mark.asyncio
async def test_scan_for_vms_live_only(vm_control):
    """Test layer 1: live running VMs via vmrun list."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (
            b"Total running VMs: 1\nC:\\VMs\\test.vmx",
            b"",
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.abspath", side_effect=lambda x: x.strip()),
        ):
            results = await vm_control.scan_for_vms()
            assert len(results) >= 1


@pytest.mark.asyncio
async def test_scan_for_vms_no_users_dir(vm_control):
    """Test graceful handling when C:\\Users doesn't exist."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"Total running VMs: 0", b"")
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        with patch("os.path.exists", return_value=False):
            results = await vm_control.scan_for_vms()
            assert results == []
