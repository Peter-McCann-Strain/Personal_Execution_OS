"""Small encrypted-at-rest helper for customer connector tokens."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

_PREFIX = "v1:"


class SecretBoxError(RuntimeError):
    """Raised when a secret cannot be encrypted or decrypted."""


def validate_secret_box_key(raw_key: str | SecretStr) -> str:
    """Return a usable installation key or fail with actionable guidance."""
    key_value = raw_key.get_secret_value() if isinstance(raw_key, SecretStr) else raw_key
    normalized = key_value.strip()
    weak_markers = ("change-me", "placeholder", "example", "test-key", "vault-key")
    if (
        len(normalized.encode("utf-8")) < 32
        or len(set(normalized)) < 8
        or any(marker in normalized.casefold() for marker in weak_markers)
    ):
        msg = (
            "connector token encryption key must be a random value of at least "
            "32 bytes (for example, 64 hexadecimal characters)"
        )
        raise SecretBoxError(msg)
    return normalized


def _fernet(raw_key: str | SecretStr) -> Fernet:
    key_value = validate_secret_box_key(raw_key)
    digest = hashlib.sha256(key_value.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str, *, key: str | SecretStr) -> str:
    if not value:
        msg = "cannot encrypt an empty secret"
        raise SecretBoxError(msg)
    token = _fernet(key).encrypt(value.encode("utf-8")).decode("ascii")
    return f"{_PREFIX}{token}"


def decrypt_secret(value: str, *, key: str | SecretStr) -> str:
    if not value:
        msg = "cannot decrypt an empty secret"
        raise SecretBoxError(msg)
    token = value.removeprefix(_PREFIX)
    try:
        return _fernet(key).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        msg = "encrypted secret could not be decrypted"
        raise SecretBoxError(msg) from exc
