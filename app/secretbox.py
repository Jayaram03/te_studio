"""Encrypts secrets (AI provider API keys) saved from the Settings page.

The encryption key comes from the SECRET_KEY environment variable, which never lives in the database. Without
SECRET_KEY, keys can't be saved from the UI and must be given as environment variables instead.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


class SecretError(Exception):
    pass


def _fernet() -> Fernet:
    secret = get_settings().secret_key
    if not secret or len(secret) < 16:
        raise SecretError("Set SECRET_KEY (a long random string) in the environment to save API keys from the app")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def available() -> bool:
    try:
        _fernet()
        return True
    except SecretError:
        return False


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise SecretError("A saved API key can't be read: SECRET_KEY has changed. Enter the key again.")


def hint(value: str | None) -> str | None:
    return f"••••{value[-4:]}" if value and len(value) > 8 else ("••••" if value else None)
