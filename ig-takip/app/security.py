"""Token şifreleme. OAuth token'ları veritabanına açık metin olarak yazılmaz."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


def _fernet() -> Fernet:
    key = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None
