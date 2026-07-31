"""Cost attribution for Anthropic LLM calls.

Loads the latest ``data/prices/anthropic_*.json`` price table and exposes
``estimate_cost`` for use in structlog fields on every ``llm_call_success``.

Design choices:
* **Versioned, git-tracked price tables.** When Anthropic changes pricing (as
  happened silently on 2026-03-06 when the default ephemeral TTL flipped 1h→5m),
  drop a new ``anthropic_YYYY-MM-DD.json`` next to the old one. The most
  recently-dated file wins, old files stay as an audit trail.
* **Fail soft on unknown models.** Returns ``(0.0, 0.0)`` and logs a one-time
  warning. Never raises inside the hot LLM path — cost is observational, not
  load-bearing.
* **No network, no FX fetch.** The GBP conversion factor lives in the JSON file
  and is updated by the same process that refreshes prices. If you need live
  FX, wrap this module with a cache-backed fetcher; do not do it here.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

import structlog

logger = structlog.get_logger()


class _CacheMultipliers(TypedDict):
    write_5m: float
    write_1h: float
    read: float


class _ModelPricing(TypedDict):
    input_per_mtok: float
    output_per_mtok: float


class _PriceTable(TypedDict):
    version: str
    currency_usd_per_gbp: float
    models: dict[str, _ModelPricing]
    cache_multipliers: _CacheMultipliers


_REPO_ROOT = Path(__file__).resolve().parents[3]
_PRICE_DIR = _REPO_ROOT / "data" / "prices"

_MISSING_MODELS_LOGGED: set[str] = set()


@lru_cache(maxsize=1)
def _latest_price_table() -> _PriceTable:
    files = sorted(_PRICE_DIR.glob("anthropic_*.json"))
    if not files:
        raise FileNotFoundError(
            f"No anthropic_*.json price tables in {_PRICE_DIR}. "
            "Add one (see data/prices/README.md) before enabling cost attribution."
        )
    latest = files[-1]
    return json.loads(latest.read_text())


def price_table_version() -> str:
    """Version string of the currently-loaded price table (ISO date)."""
    return _latest_price_table()["version"]


def estimate_cost(
    *,
    model: str,
    fresh_input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_creation_5m_input_tokens: int = 0,
    cache_creation_1h_input_tokens: int = 0,
) -> tuple[float, float]:
    """Return ``(cost_usd, cost_gbp)`` for a single Anthropic call.

    Unknown models return ``(0.0, 0.0)`` — the caller should still log usage so
    the gap is visible in aggregation.
    """
    table = _latest_price_table()
    model_price = table["models"].get(model)
    if model_price is None:
        if model not in _MISSING_MODELS_LOGGED:
            _MISSING_MODELS_LOGGED.add(model)
            logger.warning(
                "llm_pricing_model_missing",
                model=model,
                price_table_version=table["version"],
                hint="Add this model to data/prices/anthropic_*.json",
            )
        return 0.0, 0.0

    mult = table["cache_multipliers"]
    input_rate = model_price["input_per_mtok"] / 1_000_000
    output_rate = model_price["output_per_mtok"] / 1_000_000

    cost_usd = (
        fresh_input_tokens * input_rate
        + output_tokens * output_rate
        + cache_creation_5m_input_tokens * input_rate * mult["write_5m"]
        + cache_creation_1h_input_tokens * input_rate * mult["write_1h"]
        + cache_read_input_tokens * input_rate * mult["read"]
    )
    gbp = cost_usd * table["currency_usd_per_gbp"]
    return round(cost_usd, 6), round(gbp, 6)
