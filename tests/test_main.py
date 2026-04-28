import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import AsyncMock, patch

# Set TESTING environment variable
os.environ["TESTING"] = "1"

import database as db_mod
from main import app, get_db, get_current_user

# Use in-memory SQLite for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

def override_get_current_user():
    return db_mod.User(username="admin", permissions="*")

app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_current_user] = override_get_current_user

@pytest.fixture
def client():
    db_mod.Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    db_mod.Base.metadata.drop_all(bind=engine)

def test_api_vms_empty(client):
    response = client.get("/api/vms")
    assert response.status_code == 200
    assert response.json() == []

@patch("vm_control.VMControl.get_status", new_callable=AsyncMock)
def test_get_vms_with_data(mock_status, client):
    mock_status.return_value = "running"
    db = TestingSessionLocal()
    db.add(db_mod.VM(id="1", name="Test VM", path="test.vmx"))
    db.commit()
    db.close()
    
    response = client.get("/api/vms")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["name"] == "Test VM"
    assert data[0]["status"] == "running"
