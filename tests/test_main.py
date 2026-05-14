import pytest
from unittest.mock import AsyncMock, patch

from tests.conftest import (
    test_engine,
    TestingSessionLocal,
    mock_vm_control,
)

import database as db_mod
import security as security_mod
import main

from proxy import ProxyManager

mock_proxy_manager = ProxyManager(mock_vm_control.get_guest_ip)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_get_current_user():
    return db_mod.User(username="admin", permissions="*", password_version=0)


# Override the app's dependencies
main.app.dependency_overrides[main.get_db] = override_get_db
main.app.dependency_overrides[main.get_current_user] = override_get_current_user


@pytest.fixture(autouse=True)
def setup_db():
    # Force schema creation in the shared in-memory DB
    db_mod.Base.metadata.create_all(bind=test_engine)
    # Reset rate limiter between tests
    main.login_attempts.clear()
    with patch("proxy.ProxyManager.start_proxy", new_callable=AsyncMock) as mock:
        mock.return_value = True
        yield
    db_mod.Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        # Re-apply mocks after lifespan has run (lifespan overwrites globals)
        main.vm_control = mock_vm_control
        main.proxy_manager = mock_proxy_manager
        yield c


# --- Existing Tests ---


def test_api_vms_empty(client):
    response = client.get("/api/vms")
    assert response.status_code == 200
    assert response.json() == []


def test_port_blocking_api(client):
    response = client.post("/api/registry/block", json={"port": 9999, "description": "Test"})
    assert response.status_code == 200

    response = client.get("/api/registry")
    assert any(p["port"] == 9999 and p["status"] == "blocked" for p in response.json())

    response = client.delete("/api/registry/block/9999")
    assert response.status_code == 200


@patch("proxy.ProxyManager.start_proxy", new_callable=AsyncMock)
def test_create_generic_proxy_api(mock_start, client):
    mock_start.return_value = True
    response = client.post(
        "/api/proxies",
        json={"host_port": 7000, "target_port": 7001, "target_host": "127.0.0.1"},
    )
    assert response.status_code == 200


@patch("proxy.ProxyManager.scan_host_listening_ports", new_callable=AsyncMock)
def test_scan_registry_api_auto_block(mock_scan, client):
    mock_scan.return_value = [{"port": 5432, "description": "Process: postgres"}]

    response = client.post("/api/registry/scan")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["port"] == 5432

    # Verify it was auto-blocked in the DB
    response = client.get("/api/registry")
    assert any(
        p["port"] == 5432 and p["status"] == "blocked" and "postgres" in p["target"]
        for p in response.json()
    )


# --- New Tests: Login Flow ---


def test_login_success(client):
    # Create a user directly in DB
    db = TestingSessionLocal()
    db.add(
        db_mod.User(
            username="testlogin",
            hashed_password=security_mod.hash_password("testpass"),
            permissions="vm:read",
            password_version=0,
        )
    )
    db.commit()
    db.close()

    # Remove get_current_user override to test real login
    old_override = main.app.dependency_overrides.get(main.get_current_user)
    main.app.dependency_overrides.pop(main.get_current_user, None)
    try:
        response = client.post("/token", data={"username": "testlogin", "password": "testpass"})
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["permissions"] == "vm:read"
        assert "must_change_password" in data
    finally:
        if old_override:
            main.app.dependency_overrides[main.get_current_user] = old_override


def test_login_invalid_credentials(client):
    db = TestingSessionLocal()
    db.add(
        db_mod.User(
            username="testlogin2",
            hashed_password=security_mod.hash_password("correct"),
            permissions="vm:read",
        )
    )
    db.commit()
    db.close()

    response = client.post("/token", data={"username": "testlogin2", "password": "wrong"})
    assert response.status_code == 400


# --- New Tests: Rate Limiting ---


def test_rate_limiting_on_login(client):
    db = TestingSessionLocal()
    db.add(
        db_mod.User(
            username="ratelimit_user",
            hashed_password=security_mod.hash_password("pass"),
            permissions="vm:read",
        )
    )
    db.commit()
    db.close()

    # Exceed rate limit with bad passwords
    for i in range(5):
        client.post("/token", data={"username": "ratelimit_user", "password": "wrong"})

    # 6th attempt should be rate limited
    response = client.post("/token", data={"username": "ratelimit_user", "password": "pass"})
    assert response.status_code == 429


# --- New Tests: Password Change ---


def test_password_change(client):
    # Override get_current_user with a real user that exists in DB
    db = TestingSessionLocal()
    user = db_mod.User(
        username="changepw",
        hashed_password=security_mod.hash_password("oldpass"),
        permissions="*",
        password_version=0,
    )
    db.add(user)
    db.commit()
    user_id = user.id
    db.close()

    def override():
        db2 = TestingSessionLocal()
        u = db2.query(db_mod.User).filter(db_mod.User.id == user_id).first()
        return u

    main.app.dependency_overrides[main.get_current_user] = override
    try:
        response = client.post(
            "/api/user/change-password",
            json={"old_password": "oldpass", "new_password": "newpass"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "access_token" in data
    finally:
        main.app.dependency_overrides[main.get_current_user] = override_get_current_user


# --- New Tests: User CRUD ---


def test_create_and_list_users(client):
    response = client.post(
        "/api/users",
        json={"username": "newuser", "password": "pass123", "permissions": "viewer"},
    )
    assert response.status_code == 200

    response = client.get("/api/users")
    assert response.status_code == 200
    users = response.json()
    assert any(u["username"] == "newuser" for u in users)


def test_create_duplicate_user(client):
    client.post(
        "/api/users",
        json={"username": "dupuser", "password": "pass", "permissions": "viewer"},
    )
    response = client.post(
        "/api/users",
        json={"username": "dupuser", "password": "pass", "permissions": "viewer"},
    )
    assert response.status_code == 400


def test_delete_user(client):
    client.post(
        "/api/users",
        json={"username": "delme", "password": "pass", "permissions": "viewer"},
    )
    users = client.get("/api/users").json()
    user = next(u for u in users if u["username"] == "delme")
    response = client.delete(f"/api/users/{user['id']}")
    assert response.status_code == 200


# --- New Tests: VM Action Validation ---


def test_invalid_vm_action(client):
    db = TestingSessionLocal()
    import uuid

    vm_id = str(uuid.uuid4())
    db.add(db_mod.VM(id=vm_id, name="Test", path="C:\\test.vmx"))
    db.commit()
    db.close()

    response = client.post(f"/api/vms/{vm_id}/destroy")
    assert response.status_code == 400
    assert "Invalid action" in response.json()["detail"]


def test_valid_vm_actions(client):
    db = TestingSessionLocal()
    import uuid

    vm_id = str(uuid.uuid4())
    db.add(db_mod.VM(id=vm_id, name="TestVM", path="C:\\test.vmx"))
    db.commit()
    db.close()

    for action in ["start", "stop", "restart"]:
        response = client.post(f"/api/vms/{vm_id}/{action}")
        assert response.status_code == 200


# --- New Tests: VM Delete with Proxy Cascade ---


def test_vm_delete_stops_proxies(client):
    import uuid

    db = TestingSessionLocal()
    vm_id = str(uuid.uuid4())
    proxy_id = str(uuid.uuid4())
    db.add(db_mod.VM(id=vm_id, name="TestVM", path="C:\\test.vmx"))
    db.add(db_mod.Proxy(id=proxy_id, vm_id=vm_id, host_port=5000, vm_port=80, enabled=True))
    db.commit()
    db.close()

    # Patch on the actual instance
    with patch.object(main.proxy_manager, "stop_proxy", new_callable=AsyncMock) as mock_stop:
        response = client.delete(f"/api/vms/{vm_id}")
        assert response.status_code == 200
        mock_stop.assert_called()


# --- New Tests: Proxy Toggle ---


def test_proxy_toggle(client):
    import uuid

    db = TestingSessionLocal()
    proxy_id = str(uuid.uuid4())
    db.add(
        db_mod.Proxy(
            id=proxy_id,
            vm_id=None,
            target_host="127.0.0.1",
            host_port=6000,
            vm_port=80,
            enabled=True,
        )
    )
    db.commit()
    db.close()

    with patch.object(main.proxy_manager, "stop_proxy", new_callable=AsyncMock):
        response = client.put(f"/api/proxies/{proxy_id}/toggle")
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False


# --- New Tests: Add VM with Request Body ---


@patch("os.path.exists", return_value=True)
def test_add_vm_with_body(mock_exists, client):
    response = client.post("/api/vms", json={"name": "BodyVM", "path": "C:\\body.vmx"})
    assert response.status_code == 200

    vms = client.get("/api/vms").json()
    assert any(v["name"] == "BodyVM" for v in vms)


# --- New Tests: Block Port with Request Body ---


def test_block_port_with_body(client):
    response = client.post("/api/registry/block", json={"port": 8888, "description": "Test block"})
    assert response.status_code == 200

    registry = client.get("/api/registry").json()
    assert any(p["port"] == 8888 for p in registry)


# --- New Tests: Forced Password Change Blocks Other Endpoints ---


def _override_with_user(user_id):
    """Build a get_current_user override that pulls the user from the SAME
    request-scoped db session the endpoint uses — otherwise mutations on the
    returned object would be attached to a different session and never persist."""
    from fastapi import Depends

    def _get(db=Depends(main.get_db)):
        return db.query(db_mod.User).filter(db_mod.User.id == user_id).first()

    return _get


def test_must_change_password_blocks_endpoints(client):
    """Endpoints (except /token and change-password) must 403 while
    must_change_password=True."""
    db = TestingSessionLocal()
    user = db_mod.User(
        username="forced",
        hashed_password=security_mod.hash_password("pw"),
        permissions="*",
        password_version=0,
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    user_id = user.id
    db.close()

    main.app.dependency_overrides[main.get_current_user] = _override_with_user(user_id)
    try:
        for path, method in [
            ("/api/vms", "GET"),
            ("/api/users", "GET"),
            ("/api/registry", "GET"),
            ("/api/proxies", "GET"),
        ]:
            response = client.request(method, path)
            assert response.status_code == 403, (
                f"{method} {path} should 403 while must_change_password=True"
            )
            assert "Password change required" in response.json()["detail"]

        # change-password should still work
        response = client.post(
            "/api/user/change-password",
            json={"old_password": "pw", "new_password": "newpw"},
        )
        assert response.status_code == 200
    finally:
        main.app.dependency_overrides[main.get_current_user] = override_get_current_user


def test_password_change_increments_version(client):
    """Changing password must bump password_version so old tokens are revoked."""
    db = TestingSessionLocal()
    user = db_mod.User(
        username="pwbump",
        hashed_password=security_mod.hash_password("old"),
        permissions="*",
        password_version=2,
    )
    db.add(user)
    db.commit()
    user_id = user.id
    db.close()

    main.app.dependency_overrides[main.get_current_user] = _override_with_user(user_id)
    try:
        response = client.post(
            "/api/user/change-password",
            json={"old_password": "old", "new_password": "newpw"},
        )
        assert response.status_code == 200

        db = TestingSessionLocal()
        refreshed = db.query(db_mod.User).filter(db_mod.User.id == user_id).first()
        assert refreshed.password_version == 3
        assert refreshed.must_change_password is False
        db.close()
    finally:
        main.app.dependency_overrides[main.get_current_user] = override_get_current_user


# --- New Tests: Token Revocation via Stale pw_ver ---


def test_token_with_stale_pw_ver_rejected(client):
    """A token issued at pw_ver=0 must be rejected after the user's
    password_version is incremented."""
    from security import create_access_token

    db = TestingSessionLocal()
    user = db_mod.User(
        username="revoke",
        hashed_password=security_mod.hash_password("pw"),
        permissions="*",
        password_version=5,
    )
    db.add(user)
    db.commit()
    db.close()

    # Issue a token with a stale pw_ver
    stale_token = create_access_token({"sub": "revoke", "pw_ver": 0})

    # Remove the override so the real get_current_user runs
    main.app.dependency_overrides.pop(main.get_current_user, None)
    try:
        response = client.get("/api/vms", headers={"Authorization": f"Bearer {stale_token}"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Token revoked"

        # Current token should work
        current = create_access_token({"sub": "revoke", "pw_ver": 5})
        response = client.get("/api/vms", headers={"Authorization": f"Bearer {current}"})
        assert response.status_code == 200
    finally:
        main.app.dependency_overrides[main.get_current_user] = override_get_current_user


# --- New Tests: ProxyCreate Validator ---


def test_proxy_create_rejects_neither_target(client):
    """ProxyCreate must reject {vm_id=None, target_host=None}."""
    response = client.post("/api/proxies", json={"host_port": 9000, "target_port": 80})
    assert response.status_code == 422
    body = response.json()
    assert any("vm_id or target_host" in str(err).lower() for err in body["detail"])


def test_proxy_create_rejects_both_targets(client):
    """ProxyCreate must reject when both vm_id and target_host are set."""
    response = client.post(
        "/api/proxies",
        json={
            "host_port": 9000,
            "target_port": 80,
            "vm_id": "some-id",
            "target_host": "127.0.0.1",
        },
    )
    assert response.status_code == 422


def test_proxy_create_rejects_invalid_port(client):
    """ProxyCreate must reject ports outside 1-65535."""
    response = client.post(
        "/api/proxies",
        json={"host_port": 0, "target_port": 80, "target_host": "127.0.0.1"},
    )
    assert response.status_code == 422

    response = client.post(
        "/api/proxies",
        json={"host_port": 70000, "target_port": 80, "target_host": "127.0.0.1"},
    )
    assert response.status_code == 422
