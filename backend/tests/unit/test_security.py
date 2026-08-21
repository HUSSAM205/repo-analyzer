import base64

import pytest

from app.core.security import (
    _load_pem,
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


_SAMPLE_PEM = "-----BEGIN PRIVATE KEY-----\nsample\n-----END PRIVATE KEY-----\n"


def test_load_pem_accepts_raw_inline_pem_text(tmp_path):
    unused_file = tmp_path / "unused.pem"
    result = _load_pem(_SAMPLE_PEM, str(unused_file))
    assert result == _SAMPLE_PEM.strip()
    assert not unused_file.exists()  # never touched the file fallback


def test_load_pem_accepts_base64_encoded_inline_pem(tmp_path):
    encoded = base64.b64encode(_SAMPLE_PEM.encode()).decode()
    unused_file = tmp_path / "unused.pem"
    result = _load_pem(encoded, str(unused_file))
    assert result == _SAMPLE_PEM


def test_load_pem_falls_back_to_file_when_inline_value_is_none(tmp_path):
    key_file = tmp_path / "key.pem"
    key_file.write_text(_SAMPLE_PEM)
    result = _load_pem(None, str(key_file))
    assert result == _SAMPLE_PEM


def test_load_pem_falls_back_to_file_when_inline_value_is_empty_string(tmp_path):
    key_file = tmp_path / "key.pem"
    key_file.write_text(_SAMPLE_PEM)
    result = _load_pem("", str(key_file))
    assert result == _SAMPLE_PEM
