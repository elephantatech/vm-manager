"""Shared test configuration for all test files that use the FastAPI app."""

import os

import sqlalchemy
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import AsyncMock, MagicMock

# Set environment variables before any app imports
os.environ["TESTING"] = "1"
os.environ["VM_MANAGER_SECRET_KEY"] = "test-secret-key-for-unit-tests"

import database as db_mod
import security as security_mod

# Use IN-MEMORY SQLite for testing with StaticPool
SQLALCHEMY_DATABASE_URL = "sqlite://"
test_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=sqlalchemy.pool.StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Monkey-patch the global engine and session in the database module
db_mod.engine = test_engine
db_mod.SessionLocal = TestingSessionLocal

# Set secret key for tests
security_mod.SECRET_KEY = "test-secret-key-for-unit-tests"

# Create shared mocks
mock_vm_control = MagicMock()
mock_vm_control.get_guest_ip = AsyncMock()
mock_vm_control.get_status = AsyncMock(return_value="stopped")
mock_vm_control.start_vm = AsyncMock(return_value=True)
mock_vm_control.stop_vm = AsyncMock(return_value=True)
mock_vm_control.restart_vm = AsyncMock(return_value=True)
mock_vm_control.scan_for_vms = AsyncMock(return_value=[])
