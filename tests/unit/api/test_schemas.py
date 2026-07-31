"""Tests for the shared API schemas — paginate() helper and PaginatedResponse."""

from __future__ import annotations

from src.app.api.schemas import PaginatedResponse, paginate

# ---------------------------------------------------------------------------
# paginate() helper
# ---------------------------------------------------------------------------


def test_paginate_basic():
    """paginate() returns correct page, page_size, has_more for a normal case."""
    result = paginate(items=["a", "b", "c"], total=10, offset=0, limit=3)

    assert result.items == ["a", "b", "c"]
    assert result.total == 10
    assert result.page == 1
    assert result.page_size == 3
    assert result.has_more is True


def test_paginate_second_page():
    """paginate() computes page=2 when offset equals limit."""
    result = paginate(items=["d", "e", "f"], total=10, offset=3, limit=3)

    assert result.page == 2
    assert result.page_size == 3
    assert result.has_more is True


def test_paginate_last_page():
    """paginate() sets has_more=False when offset+limit >= total."""
    result = paginate(items=["g", "h"], total=8, offset=6, limit=3)

    assert result.page == 3
    assert result.has_more is False


def test_paginate_exact_boundary():
    """paginate() sets has_more=False when offset+limit equals total exactly."""
    result = paginate(items=["a", "b"], total=4, offset=2, limit=2)

    assert result.page == 2
    assert result.has_more is False


def test_paginate_zero_total():
    """paginate() handles zero total gracefully."""
    result = paginate(items=[], total=0, offset=0, limit=25)

    assert result.items == []
    assert result.total == 0
    assert result.page == 1
    assert result.page_size == 25
    assert result.has_more is False


def test_paginate_zero_limit():
    """paginate() handles zero limit (edge case) without division error."""
    result = paginate(items=[], total=5, offset=0, limit=0)

    # When limit is 0, page defaults to 1
    assert result.page == 1
    assert result.page_size == 0
    # offset + limit = 0 < total=5, so has_more is True
    assert result.has_more is True


def test_paginate_large_offset():
    """paginate() handles offset larger than total."""
    result = paginate(items=[], total=3, offset=100, limit=10)

    assert result.page == 11  # 100 // 10 + 1
    assert result.items == []
    assert result.has_more is False


# ---------------------------------------------------------------------------
# PaginatedResponse model serialisation
# ---------------------------------------------------------------------------


def test_paginated_response_serialization():
    """PaginatedResponse serializes to dict with expected keys."""
    response = PaginatedResponse(
        items=["x", "y"],
        total=5,
        page=1,
        page_size=2,
        has_more=True,
    )
    data = response.model_dump()

    assert data == {
        "items": ["x", "y"],
        "total": 5,
        "page": 1,
        "page_size": 2,
        "has_more": True,
    }


def test_paginated_response_json_roundtrip():
    """PaginatedResponse can be serialized to JSON and back."""
    response = PaginatedResponse(
        items=[1, 2, 3],
        total=3,
        page=1,
        page_size=10,
        has_more=False,
    )
    json_str = response.model_dump_json()
    restored = PaginatedResponse.model_validate_json(json_str)

    assert restored.items == [1, 2, 3]
    assert restored.total == 3
    assert restored.page == 1
    assert restored.page_size == 10
    assert restored.has_more is False
