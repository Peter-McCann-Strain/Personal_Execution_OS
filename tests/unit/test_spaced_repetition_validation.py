"""Tests for SM-2 input validation and timezone awareness."""

from datetime import UTC

import pytest

from src.app.second_brain.spaced_repetition import calculate_next_review


def test_quality_below_zero_raises():
    with pytest.raises(ValueError, match="quality must be 0-5"):
        calculate_next_review(quality=-1, repetitions=0, easiness=2.5, interval=0)


def test_quality_above_five_raises():
    with pytest.raises(ValueError, match="quality must be 0-5"):
        calculate_next_review(quality=6, repetitions=0, easiness=2.5, interval=0)


def test_next_review_date_is_timezone_aware():
    result = calculate_next_review(quality=4, repetitions=0, easiness=2.5, interval=0)
    assert result["next_review_date"].tzinfo is not None
    assert result["next_review_date"].tzinfo == UTC
