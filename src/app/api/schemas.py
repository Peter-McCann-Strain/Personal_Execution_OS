"""Shared API schemas — pagination, common response models."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse[T](BaseModel):
    """Standard paginated response matching the frontend PaginatedResponse<T> type."""

    items: list[T]
    total: int
    page: int
    page_size: int
    has_more: bool


def paginate(
    items: list[T],
    total: int,
    offset: int,
    limit: int,
) -> PaginatedResponse[T]:
    """Build a PaginatedResponse from items, total count, offset, and limit."""
    page = (offset // limit) + 1 if limit > 0 else 1
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=limit,
        has_more=(offset + limit) < total,
    )
