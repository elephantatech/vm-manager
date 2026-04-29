import os
import pytest
import sqlalchemy
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import AsyncMock, patch

# Set TESTING environment variable before anything else
os.environ["TESTING"] = "1"

import database as db_mod
import main

# Use IN-MEMORY SQLite for testing
SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=sqlalchemy.pool.StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Monkey-patch the global engine and session in the database module
db_mod.engine = engine
db_mod.SessionLocal = TestingSessionLocal


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_get_current_user():
    return db_mod.User(username="admin", permissions="*")


# Crucial: Override the app's dependencies
main.app.dependency_overrides[main.get_db] = override_get_db
main.app.dependency_overrides[main.get_current_user] = override_get_current_user


@pytest.fixture(autouse=True)
def setup_db():
    # Force schema creation in the shared in-memory DB
    db_mod.Base.metadata.create_all(bind=engine)
    # Also patch the global proxy_manager's start_proxy to avoid side effects during lifespan
    with patch("proxy.ProxyManager.start_proxy", new_callable=AsyncMock) as mock:
        mock.return_value = True
        yield
    db_mod.Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    # We use a context manager to trigger lifespan events
    with TestClient(main.app) as c:
        yield c


def test_api_vms_empty(client):
    response = client.get("/api/vms")
    assert response.status_code == 200
    assert response.json() == []


def test_port_blocking_api(client):
    response = client.post("/api/registry/block?port=9999&description=Test")
    assert response.status_code == 200

    response = client.get("/api/registry")
    assert any(p["port"] == 9999 and p["status"] == "blocked" for p in response.json())

    response = client.delete("/api/registry/block/9999")
    assert response.status_code == 200


@patch("proxy.ProxyManager.start_proxy", new_callable=AsyncMock)
def test_create_generic_proxy_api(mock_start, client):
    mock_start.return_value = True
    response = client.post(
        "/api/proxies?host_port=7000&target_port=7001&target_host=127.0.0.1"
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
