import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import database as db_mod
from proxy import PortRegistry, ProxyManager

# Setup test DB
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db():
    db_mod.Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    db_mod.Base.metadata.drop_all(bind=engine)


def test_port_registry_database_check(db):
    registry = PortRegistry()

    # 1. Test available
    with patch("socket.socket"):
        assert registry.is_port_available(9000, db) is True

    # 2. Test blocked in DB
    db.add(db_mod.ReservedPort(port=9000, description="Blocked"))
    db.commit()
    assert registry.is_port_available(9000, db) is False

    # 3. Test active in memory
    registry.register(9001)
    assert registry.is_port_available(9001, db) is False


@pytest.mark.asyncio
async def test_proxy_manager_generic_proxy(db):
    manager = ProxyManager(AsyncMock())

    with patch("proxy.TCPProxy.start", new_callable=AsyncMock), patch("socket.socket"):
        # Test starting a generic host proxy
        success = await manager.start_proxy(8080, 80, db, target_host="127.0.0.1")
        assert success is True
        assert 8080 in manager.proxies
        assert manager.proxies[8080].target_host == "127.0.0.1"


@pytest.mark.asyncio
async def test_scan_host_listening_ports_format(db):
    manager = ProxyManager(AsyncMock())
    with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
        # Mock powershell returning a JSON array of 1 object
        mock_shell.return_value.returncode = 0
        mock_shell.return_value.communicate.return_value = (
            b'[{"Port":80,"Description":"Process: nginx"}]',
            b"",
        )

        results = await manager.scan_host_listening_ports()
        assert len(results) == 1
        assert results[0]["port"] == 80
        assert "nginx" in results[0]["description"]
