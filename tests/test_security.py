import os

os.environ["VM_MANAGER_SECRET_KEY"] = "test-secret-key-for-unit-tests"

import security as security_mod

security_mod.SECRET_KEY = "test-secret-key-for-unit-tests"

from security import (
    hash_password,
    verify_password,
    create_access_token,
    ALGORITHM,
)
from jose import jwt


def test_password_hashing():
    password = "testpassword"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrong", hashed) is False


def test_token_creation():
    data = {"sub": "admin"}
    token = create_access_token(data)
    decoded = jwt.decode(token, security_mod.SECRET_KEY, algorithms=[ALGORITHM])
    assert decoded["sub"] == "admin"
    assert "exp" in decoded


def test_token_includes_password_version():
    data = {"sub": "admin", "pw_ver": 3}
    token = create_access_token(data)
    decoded = jwt.decode(token, security_mod.SECRET_KEY, algorithms=[ALGORITHM])
    assert decoded["pw_ver"] == 3


def test_secret_key_from_env():
    """Verify that env var takes precedence for secret key."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import database as db_mod

    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    db_mod.Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine)
    db = Session()

    os.environ["VM_MANAGER_SECRET_KEY"] = "env-override-key"
    try:
        from security import get_or_create_secret_key

        key = get_or_create_secret_key(db)
        assert key == "env-override-key"
    finally:
        os.environ["VM_MANAGER_SECRET_KEY"] = "test-secret-key-for-unit-tests"
        db.close()
