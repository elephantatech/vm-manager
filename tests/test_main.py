import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

# Set TESTING environment variable before importing main
os.environ["TESTING"] = "1"
from main import app, config

from models import VMConfig

@pytest.fixture
def client():
    # Use a dummy token as allowed by get_current_user logic in main.py
    return TestClient(app)

def test_lan_only_middleware_allowed(client):
    # Mocking client IP is tricky with TestClient, but by default it uses localhost
    response = client.get("/api/vms", headers={"Authorization": "Bearer dummy_token"})
    # Since status check for VMs takes time and might be mocked later, 
    # we just check if we get a 200 list (even if empty)
    assert response.status_code == 200
    assert isinstance(response.json(), list)

@patch("vm_control.VMControl.get_status", new_callable=AsyncMock)
def test_get_vms_mocked(mock_status, client):
    mock_status.return_value = "running"
    config.vms = [VMConfig(id="1", name="Test VM", path="test.vmx", proxies=[])]
    
    response = client.get("/api/vms", headers={"Authorization": "Bearer dummy_token"})
    assert response.status_code == 200
    data = response.json()
    assert data[0]["name"] == "Test VM"
    assert data[0]["status"] == "running"

def test_token_endpoint(client):
    config.auth_username = "admin"
    # We won't test full bcrypt here, just the structure
    with patch("main.verify_password", return_value=True):
        response = client.post("/token", data={"username": "admin", "password": "any"})
        assert response.status_code == 200
        assert "access_token" in response.json()
