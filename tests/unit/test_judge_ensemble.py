"""Tests for the judge ensemble (P4.8)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import structlog.contextvars as ctxvars

from src.app.core.auto_judge import AutoJudgeScores
from src.app.core.judge_ensemble import (
    JudgeConfig,
    aggregate_mean,
    aggregate_median,
    ensemble_score,
    majority_verdict,
)


def _mk_scores(
    relevance: float = 0.8,
    actionability: float = 0.8,
    tone: float = 0.8,
    conciseness: float = 0.8,
    reasoning: str = "ok",
) -> AutoJudgeScores:
    return AutoJudgeScores(
        relevance=relevance,
        actionability=actionability,
        tone=tone,
        conciseness=conciseness,
        reasoning=reasoning,
    )


# ---------------------------------------------------------------------------
# aggregate_median (self-consistency)
# ---------------------------------------------------------------------------


def test_aggregate_median_picks_middle_of_three() -> None:
    # relevance values 0.3, 0.8, 0.9 → median 0.8.
    scores = [
        _mk_scores(relevance=0.3, actionability=0.5, tone=0.4, conciseness=0.6),
        _mk_scores(relevance=0.8, actionability=0.7, tone=0.6, conciseness=0.7),
        _mk_scores(relevance=0.9, actionability=0.9, tone=0.8, conciseness=0.8),
    ]
    agg = aggregate_median(scores)
    assert agg.relevance == pytest.approx(0.8)
    assert agg.actionability == pytest.approx(0.7)
    assert agg.tone == pytest.approx(0.6)
    assert agg.conciseness == pytest.approx(0.7)


def test_aggregate_median_single_sample() -> None:
    agg = aggregate_median([_mk_scores(relevance=0.5)])
    assert agg.relevance == pytest.approx(0.5)


def test_aggregate_median_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        aggregate_median([])


def test_aggregate_median_reasoning_concatenates_members() -> None:
    scores = [_mk_scores(reasoning="a"), _mk_scores(reasoning="b")]
    agg = aggregate_median(scores)
    assert "a" in agg.reasoning
    assert "b" in agg.reasoning
    assert "median" in agg.reasoning


# ---------------------------------------------------------------------------
# aggregate_mean (jury)
# ---------------------------------------------------------------------------


def test_aggregate_mean_of_three_scores() -> None:
    scores = [
        _mk_scores(relevance=0.4),
        _mk_scores(relevance=0.6),
        _mk_scores(relevance=0.8),
    ]
    agg = aggregate_mean(scores)
    assert agg.relevance == pytest.approx(0.6)


def test_aggregate_mean_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        aggregate_mean([])


# ---------------------------------------------------------------------------
# majority_verdict
# ---------------------------------------------------------------------------


def test_majority_verdict_3_pass_agreement() -> None:
    scores = [_mk_scores(0.9, 0.9, 0.9, 0.9)] * 3
    verdict, disagreement = majority_verdict(scores, pass_threshold=0.7)
    assert verdict == "pass"
    assert disagreement is False


def test_majority_verdict_3_fail_agreement() -> None:
    scores = [_mk_scores(0.3, 0.3, 0.3, 0.3)] * 3
    verdict, disagreement = majority_verdict(scores, pass_threshold=0.7)
    assert verdict == "fail"
    assert disagreement is False


def test_majority_verdict_2_pass_1_fail_split() -> None:
    scores = [
        _mk_scores(0.9, 0.9, 0.9, 0.9),
        _mk_scores(0.9, 0.9, 0.9, 0.9),
        _mk_scores(0.3, 0.3, 0.3, 0.3),
    ]
    verdict, disagreement = majority_verdict(scores, pass_threshold=0.7)
    assert verdict == "pass"
    assert disagreement is True


def test_majority_verdict_tied_returns_neutral() -> None:
    scores = [
        _mk_scores(0.9, 0.9, 0.9, 0.9),
        _mk_scores(0.3, 0.3, 0.3, 0.3),
    ]
    verdict, disagreement = majority_verdict(scores, pass_threshold=0.7)
    assert verdict == "neutral"
    assert disagreement is True


def test_majority_verdict_empty_returns_neutral() -> None:
    assert majority_verdict([]) == ("neutral", False)


# ---------------------------------------------------------------------------
# ensemble_score — integration (mocked auto-judge)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensemble_score_rejects_zero_members() -> None:
    client = AsyncMock()
    with pytest.raises(ValueError, match="at least one member"):
        await ensemble_score(
            client,
            user_message="hi",
            response_content="hello",
            specialist="diary",
            mode="jury",
            members=[],
        )


@pytest.mark.asyncio
async def test_ensemble_jury_averages_three_different_scores(monkeypatch) -> None:
    """Jury mode: 3 members produce different scores → mean + verdict."""
    calls = []

    async def fake_score_interaction(client, *, model, max_tokens, **kwargs):
        calls.append(model)
        # Return different scores per model for observable averaging.
        if model == "a":
            return _mk_scores(0.9, 0.9, 0.9, 0.9, "strong")
        if model == "b":
            return _mk_scores(0.6, 0.6, 0.6, 0.6, "medium")
        return _mk_scores(0.3, 0.3, 0.3, 0.3, "weak")

    monkeypatch.setattr(
        "src.app.core.judge_ensemble.score_interaction",
        fake_score_interaction,
    )

    client = AsyncMock()
    members = [
        JudgeConfig(model="a", temperature=0.1, label="a"),
        JudgeConfig(model="b", temperature=0.3, label="b"),
        JudgeConfig(model="c", temperature=0.1, label="c"),
    ]
    result = await ensemble_score(
        client,
        user_message="hello",
        response_content="world",
        specialist="diary",
        mode="jury",
        members=members,
        pass_threshold=0.7,
    )
    assert result.mode == "jury"
    assert len(result.per_member_scores) == 3
    # Mean of (0.9, 0.6, 0.3) = 0.6 per dimension.
    assert result.aggregated is not None
    assert result.aggregated.relevance == pytest.approx(0.6)
    # 1 pass (0.9) + 2 fails (0.6, 0.3 below 0.7) → majority is fail, disagreement=True.
    assert result.verdict == "fail"
    assert result.disagreement is True
    # All three models were called.
    assert set(calls) == {"a", "b", "c"}


@pytest.mark.asyncio
async def test_ensemble_self_consistency_takes_median(monkeypatch) -> None:
    """Self-consistency: 3 samples of same model → median per dimension."""
    sequence = iter(
        [
            _mk_scores(0.3, 0.3, 0.3, 0.3, "low"),
            _mk_scores(0.8, 0.8, 0.8, 0.8, "mid"),
            _mk_scores(0.95, 0.95, 0.95, 0.95, "high"),
        ]
    )

    async def fake_score_interaction(client, **kwargs):
        return next(sequence)

    monkeypatch.setattr(
        "src.app.core.judge_ensemble.score_interaction",
        fake_score_interaction,
    )

    client = AsyncMock()
    members = [JudgeConfig(model="m", temperature=0.3, label=f"s{i}") for i in range(3)]
    result = await ensemble_score(
        client,
        user_message="u",
        response_content="r",
        specialist="memory",
        mode="self_consistency",
        members=members,
        pass_threshold=0.7,
    )
    assert result.mode == "self_consistency"
    # Median of [0.3, 0.8, 0.95] = 0.8.
    assert result.aggregated is not None
    assert result.aggregated.relevance == pytest.approx(0.8)
    # Aggregate mean 0.8 > threshold 0.7 → pass.
    assert result.verdict == "pass"
    # Members disagree at the member level (0.3 vs 0.95) → disagreement flag set.
    assert result.disagreement is True


@pytest.mark.asyncio
async def test_ensemble_self_consistency_all_agree_no_disagreement(monkeypatch) -> None:
    async def fake(client, **kwargs):
        return _mk_scores(0.85, 0.85, 0.85, 0.85, "steady")

    monkeypatch.setattr("src.app.core.judge_ensemble.score_interaction", fake)
    client = AsyncMock()
    members = [JudgeConfig(model="m", temperature=0.3, label=f"s{i}") for i in range(3)]
    result = await ensemble_score(
        client,
        user_message="u",
        response_content="r",
        specialist="diary",
        mode="self_consistency",
        members=members,
        pass_threshold=0.7,
    )
    assert result.verdict == "pass"
    assert result.disagreement is False


@pytest.mark.asyncio
async def test_ensemble_score_binds_evaluation_purpose_contextvar(monkeypatch) -> None:
    """Cost-alerts (P4.10) relies on structlog `purpose="evaluation"` context."""
    seen_context: dict[str, object] = {}

    async def fake(client, **kwargs):
        # Snapshot structlog contextvars at call time.
        snap = ctxvars.get_contextvars()
        seen_context.update(snap)
        return _mk_scores(0.8, 0.8, 0.8, 0.8, "ok")

    monkeypatch.setattr("src.app.core.judge_ensemble.score_interaction", fake)

    client = AsyncMock()
    members = [JudgeConfig(model="m", label="s1")]
    await ensemble_score(
        client,
        user_message="u",
        response_content="r",
        specialist="diary",
        mode="jury",
        members=members,
    )
    assert seen_context.get("purpose") == "evaluation"
    assert seen_context.get("ensemble_mode") == "jury"
    # Context is unbound after the call.
    after = ctxvars.get_contextvars()
    assert "purpose" not in after
