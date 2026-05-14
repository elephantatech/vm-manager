from sqlalchemy import create_engine, Column, String, Integer, Boolean, ForeignKey, text
from sqlalchemy.exc import OperationalError
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
    must_change_password = Column(Boolean, nullable=False, default=False, server_default="0")
    # Incremented on password change to invalidate every existing JWT for this user.
    password_version = Column(Integer, nullable=False, default=0, server_default="0")


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


# SQLite error fragments emitted when ALTER TABLE ADD COLUMN hits an existing column.
# We must distinguish this expected case from real failures (disk full, locked DB,
# permission errors) — otherwise a broken upgrade silently looks like success.
_DUPLICATE_COLUMN_FRAGMENTS = ("duplicate column name", "already exists")


def _run_migrations(engine):
    """Add new columns to existing tables for SQLite (no Alembic needed).

    SQLite lacks portable column introspection across versions, so we try the
    ALTER TABLE and treat only the "column already exists" error as success.
    """
    migrations = [
        ("users", "must_change_password", "BOOLEAN NOT NULL DEFAULT 0"),
        ("users", "password_version", "INTEGER NOT NULL DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in migrations:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                conn.commit()
                logger.info({"event": "migration_applied", "table": table, "column": column})
            except OperationalError as e:
                conn.rollback()
                msg = str(e).lower()
                if not any(frag in msg for frag in _DUPLICATE_COLUMN_FRAGMENTS):
                    logger.error(
                        {
                            "event": "migration_failed",
                            "table": table,
                            "column": column,
                            "error": str(e),
                        }
                    )
                    raise

        # Backfill NULLs that may exist from pre-migration databases where the
        # column was added with a non-enforced default.
        for col in ("must_change_password", "password_version"):
            try:
                conn.execute(text(f"UPDATE users SET {col} = 0 WHERE {col} IS NULL"))
                conn.commit()
            except OperationalError:
                conn.rollback()


def init_db():
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
