import pytest
from fastapi import HTTPException
from app.core.security import hash_password, verify_password, create_access_token, decode_token

def test_hash_roundtrip():
    h = hash_password("s3cret")
    assert h != "s3cret" and verify_password("s3cret", h) and not verify_password("wrong", h)

def test_token_roundtrip():
    t = create_access_token(1, "admin")
    d = decode_token(t)
    assert d["sub"] == "1" and d["role"] == "admin"

def test_bad_token_none():
    assert decode_token("garbage") is None
