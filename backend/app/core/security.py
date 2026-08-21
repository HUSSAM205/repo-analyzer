import base64
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


def _load_pem(inline_value: str | None, file_path: str) -> str:
    """Loads a PEM key from an inline env var if set (see
    Settings.jwt_private_key/jwt_public_key), falling back to a file path.
    The inline value can be the raw PEM text or a base64 encoding of it."""
    if inline_value:
        stripped = inline_value.strip()
        if stripped.startswith("-----BEGIN"):
            return stripped
        return base64.b64decode(stripped).decode("utf-8")
    return (BACKEND_ROOT / file_path).read_text()


@lru_cache
def _private_key() -> str:
    return _load_pem(settings.jwt_private_key, settings.jwt_private_key_path)


@lru_cache
def _public_key() -> str:
    return _load_pem(settings.jwt_public_key, settings.jwt_public_key_path)


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
