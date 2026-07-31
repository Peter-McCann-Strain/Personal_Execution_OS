"""Shared analytics helpers for aggregating episode metrics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def average_metric(
    episodes: list[Mapping[str, Any]],
    key: str,
) -> float | None:
    """Compute the average of a numeric field across episodes, ignoring nulls.

    Returns None if no non-null values are found.

    >>> average_metric([{"mood_score": 7}, {"mood_score": 5}, {"mood_score": None}], "mood_score")
    6.0
    >>> average_metric([{"mood_score": None}], "mood_score") is None
    True
    """
    values = [e[key] for e in episodes if e[key] is not None]
    if not values:
        return None
    return sum(values) / len(values)
