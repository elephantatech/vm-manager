import os
import secrets
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt

from logger_config import logger

PWD_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Mutable module-level secret key — set during app startup via init_secret_key()
SECRET_KEY: str = ""


def get_or_create_secret_key(db_session) -> str:
    """Resolve the JWT secret key: env var > DB > generate new."""
    from database import Setting

    env_key = os.environ.get("VM_MANAGER_SECRET_KEY")
    if env_key:
        return env_key

    row = db_session.query(Setting).filter(Setting.key == "secret_key").first()
    if row:
        return row.value

    new_key = secrets.token_hex(64)
    db_session.add(Setting(key="secret_key", value=new_key))
    db_session.commit()
    logger.info(
        {
            "event": "secret_key_generated",
            "message": "New JWT secret key persisted to DB",
        }
    )
    return new_key


def init_secret_key(db_session):
    """Called after init_db() to set the module-level SECRET_KEY."""
    global SECRET_KEY
    SECRET_KEY = get_or_create_secret_key(db_session)


def hash_password(password: str) -> str:
    return PWD_CONTEXT.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return PWD_CONTEXT.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
