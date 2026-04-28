from database import VM, Proxy, User

def test_vm_model_creation():
    vm = VM(id="vm1", name="Ubuntu", path="/path/to/vmx")
    assert vm.name == "Ubuntu"
    assert vm.id == "vm1"

def test_proxy_model_creation():
    proxy = Proxy(id="p1", vm_id="vm1", host_port=8080, vm_port=80, enabled=True)
    assert proxy.host_port == 8080
    assert proxy.enabled is True

def test_user_model_permissions():
    user = User(username="admin", permissions="*")
    assert user.permissions == "*"
