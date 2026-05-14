import pytest
from unittest.mock import MagicMock

from tests.conftest import (
    test_engine,
    TestingSessionLocal,
    mock_vm_control,
)

import database as db_mod
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


main.app.dependency_overrides[main.get_db] = override_get_db
main.app.dependency_overrides[main.get_current_user] = override_get_current_user


@pytest.fixture(autouse=True)
def setup_db():
    db_mod.Base.metadata.create_all(bind=test_engine)
    yield
    db_mod.Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        main.vm_control = mock_vm_control
        main.proxy_manager = mock_proxy_manager
        yield c


def test_localhost_allowed(client):
    """TestClient uses 'testclient' as host which is whitelisted."""
    response = client.get("/api/vms")
    assert response.status_code == 200


def test_lan_middleware_rejects_public_ip():
    """Test that public IPs are rejected by the middleware."""
    import asyncio
    from starlette.requests import Request
    from starlette.datastructures import Address

    async def check():
        mock_request = MagicMock(spec=Request)
        mock_request.client = Address("8.8.8.8", 12345)

        async def mock_call_next(request):
            return MagicMock()

        response = await main.lan_middleware(mock_request, mock_call_next)
        assert response.status_code == 403

    asyncio.get_event_loop().run_until_complete(check())


def test_lan_middleware_accepts_private_ips():
    """Test that various private IPs are accepted."""
    import asyncio
    from starlette.requests import Request
    from starlette.datastructures import Address

    async def check_ip(ip, expected_allowed):
        mock_request = MagicMock(spec=Request)
        mock_request.client = Address(ip, 12345)

        called = False

        async def mock_call_next(request):
            nonlocal called
            called = True
            return MagicMock(status_code=200)

        response = await main.lan_middleware(mock_request, mock_call_next)
        if expected_allowed:
            assert called, f"Expected {ip} to be allowed but it was blocked"
        else:
            assert response.status_code == 403, f"Expected {ip} to be blocked"

    async def run_all():
        # Should be allowed
        await check_ip("127.0.0.1", True)
        await check_ip("192.168.1.1", True)
        await check_ip("10.0.0.1", True)
        await check_ip("172.16.0.1", True)
        await check_ip("172.31.255.255", True)
        # Should be blocked
        await check_ip("8.8.8.8", False)
        await check_ip("172.15.0.1", False)
        await check_ip("172.32.0.1", False)

    asyncio.get_event_loop().run_until_complete(run_all())


def test_lan_middleware_malformed_172_ip():
    """Test that malformed 172.x IPs don't crash the middleware."""
    import asyncio
    from starlette.requests import Request
    from starlette.datastructures import Address

    async def check():
        mock_request = MagicMock(spec=Request)
        mock_request.client = Address("172.abc.0.1", 12345)

        async def mock_call_next(request):
            return MagicMock(status_code=200)

        # Should not raise, should return 403 for unparseable IP
        response = await main.lan_middleware(mock_request, mock_call_next)
        assert response.status_code == 403

    asyncio.get_event_loop().run_until_complete(check())
