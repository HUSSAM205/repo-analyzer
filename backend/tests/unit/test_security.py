import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_jwt_roundtrip():
    token = create_access_token(subject="user-123")
    payload = decode_access_token(token)
    assert payload["sub"] == "user-123"


def test_jwt_expired_token_rejected():
    token = create_access_token(subject="user-123", expires_minutes=-1)
    with pytest.raises(Exception):
        decode_access_token(token)


def test_generate_api_key_is_unique_and_hashable():
    key1, hash1 = generate_api_key()
    key2, hash2 = generate_api_key()
    assert key1 != key2
    assert key1.startswith("ra_")
    assert hash1 != key1
