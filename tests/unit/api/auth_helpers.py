from __future__ import annotations

import uuid

from fastapi import FastAPI

from src.app.api.deps import Principal, get_current_principal


def owner_principal() -> Principal:
    return Principal(
        subject="owner",
        external_subject=None,
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
        account_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        role="owner",
        plan="pro",
        scopes=("admin",),
        auth_method="api_key",
    )


def override_current_principal(app: FastAPI) -> None:
    async def _always_principal() -> Principal:
        return owner_principal()

    app.dependency_overrides[get_current_principal] = _always_principal
