from sqlalchemy import create_engine, Column, String, Integer, Boolean, ForeignKey, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, relationship

from logger_config import logger

DATABASE_URL = "sqlite:///./vm_manager.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    permissions = Column(String, default="vm:read")  # Comma separated permissions
    must_change_password = Column(Boolean, default=False)
    password_version = Column(Integer, default=0)


class VM(Base):
    __tablename__ = "vms"
    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    path = Column(String)
    proxies = relationship("Proxy", back_populates="vm", cascade="all, delete-orphan")


class Proxy(Base):
    __tablename__ = "proxies"
    id = Column(String, primary_key=True, index=True)
    vm_id = Column(String, ForeignKey("vms.id"), nullable=True)
    target_host = Column(String, nullable=True)  # For non-VM targets like 127.0.0.1
    host_port = Column(Integer)
    vm_port = Column(Integer)
    enabled = Column(Boolean, default=True)
    vm = relationship("VM", back_populates="proxies")


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True, index=True)
    value = Column(String)


class ReservedPort(Base):
    __tablename__ = "reserved_ports"
    port = Column(Integer, primary_key=True, index=True)
    description = Column(String, nullable=True)


def _run_migrations(engine):
    """Add new columns to existing tables for SQLite (no Alembic needed)."""
    migrations = [
        ("users", "must_change_password", "BOOLEAN DEFAULT 0"),
        ("users", "password_version", "INTEGER DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in migrations:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                conn.commit()
                logger.info(
                    {
                        "event": "migration_applied",
                        "table": table,
                        "column": column,
                    }
                )
            except Exception:
                # Column already exists — expected on subsequent runs
                conn.rollback()


def init_db():
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
