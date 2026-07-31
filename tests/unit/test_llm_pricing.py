"""Unit tests for src.app.core.llm_pricing."""

from __future__ import annotations

from src.app.core import llm_pricing


def _reset_pricing_cache() -> None:
    """The module caches the loaded JSON via lru_cache; drop it between tests."""
    llm_pricing._latest_price_table.cache_clear()
    llm_pricing._MISSING_MODELS_LOGGED.clear()


class TestPriceTableVersion:
    def test_returns_iso_date(self) -> None:
        _reset_pricing_cache()
        version = llm_pricing.price_table_version()
        # Matches YYYY-MM-DD pattern
        assert len(version) == 10
        assert version[4] == "-"
        assert version[7] == "-"


class TestEstimateCost:
    def test_known_model_basic_input_output(self) -> None:
        _reset_pricing_cache()
        usd, gbp = llm_pricing.estimate_cost(
            model="claude-sonnet-4-6",
            fresh_input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # Sonnet 4.6 per the fixture: $3/M input + $15/M output = $18
        assert usd == 18.0
        # GBP conversion approx: 18 * 0.79 = 14.22
        assert gbp > 14.0
        assert gbp < 15.0

    def test_cache_read_applies_10pct_multiplier(self) -> None:
        _reset_pricing_cache()
        # 1M cache-read tokens on Sonnet at $3/M * 0.10 = $0.30
        usd, _ = llm_pricing.estimate_cost(
            model="claude-sonnet-4-6",
            fresh_input_tokens=0,
            output_tokens=0,
            cache_read_input_tokens=1_000_000,
        )
        assert abs(usd - 0.30) < 1e-6

    def test_cache_write_5m_applies_1_25x_multiplier(self) -> None:
        _reset_pricing_cache()
        # 1M cache-write-5m tokens on Sonnet at $3/M * 1.25 = $3.75
        usd, _ = llm_pricing.estimate_cost(
            model="claude-sonnet-4-6",
            fresh_input_tokens=0,
            output_tokens=0,
            cache_creation_5m_input_tokens=1_000_000,
        )
        assert abs(usd - 3.75) < 1e-6

    def test_cache_write_1h_applies_2x_multiplier(self) -> None:
        _reset_pricing_cache()
        # 1M cache-write-1h tokens on Sonnet at $3/M * 2.0 = $6.00
        usd, _ = llm_pricing.estimate_cost(
            model="claude-sonnet-4-6",
            fresh_input_tokens=0,
            output_tokens=0,
            cache_creation_1h_input_tokens=1_000_000,
        )
        assert abs(usd - 6.00) < 1e-6

    def test_unknown_model_returns_zero(self) -> None:
        _reset_pricing_cache()
        usd, gbp = llm_pricing.estimate_cost(
            model="claude-imaginary-99",
            fresh_input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        assert usd == 0.0
        assert gbp == 0.0

    def test_unknown_model_logs_only_once(self) -> None:
        _reset_pricing_cache()
        llm_pricing.estimate_cost(
            model="claude-imaginary-99",
            fresh_input_tokens=10,
            output_tokens=10,
        )
        assert "claude-imaginary-99" in llm_pricing._MISSING_MODELS_LOGGED
        # Second call should not re-log (the set is the idempotency guard)
        size_before = len(llm_pricing._MISSING_MODELS_LOGGED)
        llm_pricing.estimate_cost(
            model="claude-imaginary-99",
            fresh_input_tokens=10,
            output_tokens=10,
        )
        assert len(llm_pricing._MISSING_MODELS_LOGGED) == size_before

    def test_combined_usage(self) -> None:
        _reset_pricing_cache()
        # Realistic shape: 500 fresh input, 2000 cache read, 1000 cache 5m write, 200 output.
        # Sonnet at $3/M input, $15/M output:
        # fresh:   500 * 3e-6 = 0.0015
        # read:    2000 * 3e-6 * 0.10 = 0.0006
        # write5m: 1000 * 3e-6 * 1.25 = 0.00375
        # output:  200 * 15e-6 = 0.003
        # total = 0.00885
        usd, _ = llm_pricing.estimate_cost(
            model="claude-sonnet-4-6",
            fresh_input_tokens=500,
            output_tokens=200,
            cache_read_input_tokens=2000,
            cache_creation_5m_input_tokens=1000,
        )
        assert abs(usd - 0.00885) < 1e-6
