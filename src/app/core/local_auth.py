"""Cryptographic helpers for local-owner password and cookie sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_password_hasher = PasswordHasher()


@dataclass(frozen=True)
class ParsedSessionCookie:
    session_id: uuid.UUID
    token: str


def hash_password(password: str) -> str:
    """Hash a local-owner password with Argon2id."""
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify a password without leaking mismatch details."""
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """Return whether current Argon2 parameters should replace an old hash."""
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def generate_session_secret() -> str:
    return secrets.token_urlsafe(48)


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def build_session_cookie(
    session_id: uuid.UUID,
    token: str,
    *,
    signing_secret: str,
) -> str:
    """Build a signed, opaque cookie value."""
    payload = f"{session_id}.{token}"
    signature = hmac.new(
        signing_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}.{signature}"


def parse_session_cookie(
    value: str,
    *,
    signing_secret: str,
) -> ParsedSessionCookie | None:
    """Validate a signed cookie and return its opaque session components."""
    if not value or len(value) > 512:
        return None
    try:
        session_id_raw, token, signature = value.split(".", 2)
        session_id = uuid.UUID(session_id_raw)
    except (ValueError, AttributeError):
        return None
    payload = f"{session_id}.{token}"
    expected = hmac.new(
        signing_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    return ParsedSessionCookie(session_id=session_id, token=token)
