from __future__ import annotations

import pytest
from pydantic import SecretStr

from src.app.core.secret_box import SecretBoxError, decrypt_secret, encrypt_secret
from src.app.domain.services import connector_sync

_STRONG_KEY = "".join(("0123456789abcdef",) * 4)
_OTHER_STRONG_KEY = "".join(("fedcba9876543210",) * 4)


def test_secret_box_round_trips_without_plaintext_leak() -> None:
    encrypted = encrypt_secret("refresh-token", key=SecretStr(_STRONG_KEY))

    assert encrypted.startswith("v1:")
    assert "refresh-token" not in encrypted
    assert decrypt_secret(encrypted, key=SecretStr(_STRONG_KEY)) == "refresh-token"


def test_secret_box_rejects_wrong_key() -> None:
    encrypted = encrypt_secret("refresh-token", key=SecretStr(_STRONG_KEY))

    with pytest.raises(SecretBoxError):
        decrypt_secret(encrypted, key=SecretStr(_OTHER_STRONG_KEY))


@pytest.mark.parametrize("weak_key", ["", "vault-key", "a" * 64])
def test_secret_box_rejects_missing_or_weak_keys(weak_key: str) -> None:
    with pytest.raises(SecretBoxError, match="random value"):
        encrypt_secret("refresh-token", key=SecretStr(weak_key))


def test_connector_sync_prefers_account_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    encrypted = encrypt_secret("account-refresh", key=SecretStr(_STRONG_KEY))

    class Settings:
        connector_token_encryption_key = SecretStr(_STRONG_KEY)
        google_refresh_token = SecretStr("global-refresh")

    class Account:
        encrypted_refresh_token = encrypted

    monkeypatch.setattr(connector_sync, "get_settings", lambda: Settings())

    assert connector_sync._connector_refresh_token(Account()) == "account-refresh"


def test_connector_sync_falls_back_to_global_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    class Settings:
        connector_token_encryption_key = SecretStr("")
        google_refresh_token = SecretStr("global-refresh")

    class Account:
        encrypted_refresh_token = None

    monkeypatch.setattr(connector_sync, "get_settings", lambda: Settings())

    assert connector_sync._connector_refresh_token(Account()) == "global-refresh"
