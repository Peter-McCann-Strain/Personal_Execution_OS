"""Tests for SM-2 spaced repetition algorithm."""

from src.app.second_brain.spaced_repetition import calculate_next_review


def test_failed_recall_resets():
    """Quality < 3 should reset to interval=1 and reduce easiness."""
    result = calculate_next_review(quality=2, repetitions=5, easiness=2.5, interval=30)
    assert result["interval"] == 1
    assert result["repetitions"] == 0
    assert result["easiness"] < 2.5


def test_first_successful_review():
    """First success should set interval to 1."""
    result = calculate_next_review(quality=4, repetitions=0, easiness=2.5, interval=0)
    assert result["interval"] == 1
    assert result["repetitions"] == 1


def test_second_successful_review():
    """Second success should set interval to 6."""
    result = calculate_next_review(quality=4, repetitions=1, easiness=2.5, interval=1)
    assert result["interval"] == 6
    assert result["repetitions"] == 2


def test_subsequent_review_multiplies():
    """Third+ success should multiply interval by easiness."""
    result = calculate_next_review(quality=4, repetitions=2, easiness=2.5, interval=6)
    assert result["interval"] == 15  # 6 * 2.5 = 15
    assert result["repetitions"] == 3


def test_perfect_recall_increases_easiness():
    """Quality=5 should increase easiness factor."""
    result = calculate_next_review(quality=5, repetitions=2, easiness=2.5, interval=6)
    assert result["easiness"] > 2.5


def test_minimum_easiness_enforced():
    """Easiness should never go below 1.3."""
    result = calculate_next_review(quality=0, repetitions=0, easiness=1.3, interval=1)
    assert result["easiness"] >= 1.3
