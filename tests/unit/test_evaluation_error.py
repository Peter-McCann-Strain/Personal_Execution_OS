"""Tests for EvaluationError exception and its status mapping."""

import pytest

from src.app.core.exceptions import (
    EXCEPTION_STATUS_MAP,
    AppError,
    EvaluationError,
)


class TestEvaluationError:
    def test_is_app_error_subclass(self):
        """EvaluationError inherits from AppError."""
        assert issubclass(EvaluationError, AppError)

    def test_raises_with_message(self):
        """EvaluationError captures the error message."""
        err = EvaluationError("Auto-judge scoring failed: API error")
        assert "Auto-judge" in str(err)
        assert "API error" in str(err)

    def test_in_exception_status_map(self):
        """EvaluationError is mapped to HTTP 500 with 'evaluation_error' code."""
        assert EvaluationError in EXCEPTION_STATUS_MAP
        status_code, error_code = EXCEPTION_STATUS_MAP[EvaluationError]
        assert status_code == 500
        assert error_code == "evaluation_error"

    def test_catchable_as_app_error(self):
        """EvaluationError can be caught as AppError."""
        with pytest.raises(AppError, match="test"):
            raise EvaluationError("test")
