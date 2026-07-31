"""Spaced repetition — SM-2 algorithm for key insights.

Surfaces important notes at optimal review intervals.
"""

from datetime import UTC, datetime, timedelta

import structlog

logger = structlog.get_logger()

# SM-2 algorithm defaults
MIN_EASINESS = 1.3


def calculate_next_review(
    quality: int,
    repetitions: int,
    easiness: float,
    interval: int,
) -> dict:
    """Calculate next review date using SM-2 algorithm.

    Args:
        quality: 0-5 rating of recall quality
        repetitions: number of successful reviews
        easiness: current easiness factor (≥1.3)
        interval: current interval in days

    Returns:
        dict with: next_interval, repetitions, easiness, next_review_date

    Raises:
        ValueError: If quality is not in the range 0-5.
    """
    if not (0 <= quality <= 5):
        raise ValueError(f"quality must be 0-5, got {quality}")

    if quality < 3:
        # Failed recall — reset
        return {
            "interval": 1,
            "repetitions": 0,
            "easiness": max(easiness - 0.2, MIN_EASINESS),
            "next_review_date": datetime.now(UTC) + timedelta(days=1),
        }

    # Successful recall
    if repetitions == 0:
        next_interval = 1
    elif repetitions == 1:
        next_interval = 6
    else:
        next_interval = round(interval * easiness)

    new_easiness = easiness + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_easiness = max(new_easiness, MIN_EASINESS)

    return {
        "interval": next_interval,
        "repetitions": repetitions + 1,
        "easiness": round(new_easiness, 2),
        "next_review_date": datetime.now(UTC) + timedelta(days=next_interval),
    }
