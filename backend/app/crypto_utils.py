"""
Minimal symmetric encryption helpers for storing tenant secrets.
"""
from __future__ import annotations

import base64
import hashlib
import os

from fastapi import HTTPException

PASSPHRASE_ENV = "TENANT_SECRET_PASSPHRASE"


def _get_key() -> bytes:
    value = os.getenv(PASSPHRASE_ENV)
    if not value:
        raise HTTPException(
            status_code=500,
            detail="TENANT_SECRET_PASSPHRASE must be set to store credentials securely",
        )
    return hashlib.sha256(value.encode("utf-8")).digest()


def encrypt_secret(secret: str) -> str:
    key = _get_key()
    data = secret.encode("utf-8")
    encrypted = bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])
    return base64.urlsafe_b64encode(encrypted).decode("utf-8")


def decrypt_secret(token: str) -> str:
    key = _get_key()
    data = base64.urlsafe_b64decode(token.encode("utf-8"))
    decrypted = bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])
    return decrypted.decode("utf-8")
