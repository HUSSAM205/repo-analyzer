import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import jwt
from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pwd_context.verify(password, hashed)


@lru_cache
def _private_key() -> str:
    return (BACKEND_ROOT / settings.jwt_private_key_path).read_text()


@lru_cache
def _public_key() -> str:
    return (BACKEND_ROOT / settings.jwt_public_key_path).read_text()


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes if expires_minutes is not None else settings.jwt_access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, _private_key(), algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, _public_key(), algorithms=[settings.jwt_algorithm])


def generate_api_key() -> tuple[str, str]:
    plaintext = f"ra_{secrets.token_urlsafe(32)}"
    return plaintext, hash_api_key(plaintext)


def hash_api_key(key: str) -> str:
    return _pwd_context.hash(key)
