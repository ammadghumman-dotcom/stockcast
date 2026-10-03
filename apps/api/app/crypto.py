"""Symmetric encryption for channel credentials (Fernet)."""

import base64
import hashlib

from cryptography.fernet import Fernet

from app.config import settings


def _fernet() -> Fernet:
    # Accept any string as the key: derive 32 url-safe base64 bytes from it.
    digest = hashlib.sha256(settings.credentials_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
