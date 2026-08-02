"""Shared analytics helpers for aggregating episode metrics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import fsum, isfinite
from numbers import Real


def average_metric(
    episodes: Iterable[Mapping[str, object]],
    key: str,
) -> float | None:
    """Compute the average of a numeric field across episodes, ignoring nulls.

    Returns None if no non-null values are found. Malformed and non-finite
    values are rejected instead of being silently included in review metrics.

    >>> average_metric([{"mood_score": 7}, {"mood_score": 5}, {"mood_score": None}], "mood_score")
    6.0
    >>> average_metric([{"mood_score": None}], "mood_score") is None
    True
    """
    values: list[float] = []
    for index, episode in enumerate(episodes):
        value = episode[key]
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError(
                f"{key} at row {index} must be a number or None, got {type(value).__name__}"
            )
        normalized = float(value)
        if not isfinite(normalized):
            raise ValueError(f"{key} at row {index} must be finite")
        values.append(normalized)

    if not values:
        return None
    return fsum(values) / len(values)
