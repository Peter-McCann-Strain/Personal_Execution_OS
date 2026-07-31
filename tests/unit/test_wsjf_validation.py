"""Tests for WSJF input validation."""

import pytest

from src.app.agents.specialists.project import calculate_wsjf


def test_business_value_below_range():
    with pytest.raises(ValueError, match="business_value must be between 1 and 10"):
        calculate_wsjf(0, 5, 5, 5)


def test_business_value_above_range():
    with pytest.raises(ValueError, match="business_value must be between 1 and 10"):
        calculate_wsjf(11, 5, 5, 5)


def test_job_size_below_range():
    with pytest.raises(ValueError, match="job_size must be between 1 and 10"):
        calculate_wsjf(5, 5, 5, 0)


def test_all_min_values():
    score = calculate_wsjf(1, 1, 1, 1)
    assert score == 3.0  # (1+1+1)/1


def test_all_max_values():
    score = calculate_wsjf(10, 10, 10, 10)
    assert score == 3.0  # (10+10+10)/10
