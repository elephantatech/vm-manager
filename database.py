from sqlalchemy import create_engine, Column, String, Integer, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

DATABASE_URL = "sqlite:///./vm_manager.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    permissions = Column(String, default="vm:read") # Comma separated permissions

class VM(Base):
    __tablename__ = "vms"
    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    path = Column(String)
    proxies = relationship("Proxy", back_populates="vm", cascade="all, delete-orphan")

class Proxy(Base):
    __tablename__ = "proxies"
    id = Column(String, primary_key=True, index=True)
    vm_id = Column(String, ForeignKey("vms.id"))
    host_port = Column(Integer)
    vm_port = Column(Integer)
    enabled = Column(Boolean, default=True)
    vm = relationship("VM", back_populates="proxies")

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True, index=True)
    value = Column(String)

def init_db():
    Base.metadata.create_all(bind=engine)
