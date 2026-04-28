from models import ProxyConfig, VMConfig, AppConfig

def test_proxy_config_validation():
    proxy = ProxyConfig(id="1", vm_id="vm1", host_port=8080, vm_port=80)
    assert proxy.id == "1"
    assert proxy.host_port == 8080
    assert proxy.enabled is True

def test_vm_config_validation():
    vm = VMConfig(id="vm1", name="Ubuntu", path="/path/to/vmx")
    assert vm.name == "Ubuntu"
    assert vm.proxies == []

def test_app_config_defaults():
    config = AppConfig()
    assert "vmrun.exe" in config.vmrun_path
    assert config.vms == []
    assert config.auth_username is None
