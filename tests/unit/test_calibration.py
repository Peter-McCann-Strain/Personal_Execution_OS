"""Tests for calibration drift rule + judge-model version change detection.

Also covers the interactive-loop logic in ``scripts/calibrate.py`` (with the
TTY mocked out) plus the report-generation markdown.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.app.core.calibration import (
    DRIFT_BLOCK_CONSECUTIVE_MONTHS,
    DRIFT_BLOCK_THRESHOLD,
    judge_model_changed,
    load_judge_model_state,
    save_judge_model_state,
    should_block_prompt_edits,
)

# ---------------------------------------------------------------------------
# Drift rule
# ---------------------------------------------------------------------------


class TestShouldBlockPromptEdits:
    def test_empty_history_does_not_block(self):
        assert should_block_prompt_edits("diary", "relevance", []) is False

    def test_single_month_does_not_block(self):
        # Even a big drift in a single month shouldn't block — noise tolerance.
        assert should_block_prompt_edits("diary", "relevance", [0.8]) is False

    def test_two_consecutive_over_threshold_blocks(self):
        assert (
            should_block_prompt_edits(
                "diary",
                "relevance",
                [0.6, 0.7],
            )
            is True
        )

    def test_two_consecutive_negative_drift_blocks(self):
        # Negative drift (the human scores lower than the judge) also blocks.
        assert (
            should_block_prompt_edits(
                "memory",
                "tone",
                [-0.6, -0.55],
            )
            is True
        )

    def test_at_threshold_does_not_block(self):
        # Boundary — must be strictly greater than threshold.
        assert (
            should_block_prompt_edits(
                "diary",
                "relevance",
                [DRIFT_BLOCK_THRESHOLD, DRIFT_BLOCK_THRESHOLD],
            )
            is False
        )

    def test_older_high_drift_resolved_does_not_block(self):
        # One-month recovery — the tail is below threshold → don't block.
        assert (
            should_block_prompt_edits(
                "diary",
                "relevance",
                [0.8, 0.7, 0.2],
            )
            is False
        )

    def test_only_last_two_months_matter(self):
        # First month was fine, last two are blown — still blocks on tail.
        assert (
            should_block_prompt_edits(
                "diary",
                "relevance",
                [0.1, 0.6, 0.7],
            )
            is True
        )

    def test_consecutive_constant_is_two(self):
        assert DRIFT_BLOCK_CONSECUTIVE_MONTHS == 2


# ---------------------------------------------------------------------------
# Judge-model version tracking
# ---------------------------------------------------------------------------


class TestJudgeModelVersion:
    def test_first_boot_no_state_no_change(self, tmp_path: Path):
        state_path = tmp_path / "state.json"
        changed, info = judge_model_changed(
            current_snapshot="claude-sonnet-4-6",
            pinned_version="",
            state_path=state_path,
        )
        assert changed is False
        assert info["last_seen"] is None

    def test_pinned_version_mismatch_flags_change(self, tmp_path: Path):
        state_path = tmp_path / "state.json"
        changed, info = judge_model_changed(
            current_snapshot="claude-sonnet-4-6.1",
            pinned_version="claude-sonnet-4-6",
            state_path=state_path,
        )
        assert changed is True
        assert info["changed_vs_pin"] is True

    def test_same_snapshot_no_change(self, tmp_path: Path):
        state_path = tmp_path / "state.json"
        save_judge_model_state(
            model_snapshot_seen="claude-sonnet-4-6",
            path=state_path,
        )
        changed, _ = judge_model_changed(
            current_snapshot="claude-sonnet-4-6",
            pinned_version="claude-sonnet-4-6",
            state_path=state_path,
        )
        assert changed is False

    def test_seen_snapshot_change_fires(self, tmp_path: Path):
        state_path = tmp_path / "state.json"
        save_judge_model_state(
            model_snapshot_seen="claude-sonnet-4-6",
            path=state_path,
        )
        changed, info = judge_model_changed(
            current_snapshot="claude-sonnet-4-6.1",
            pinned_version="",
            state_path=state_path,
        )
        assert changed is True
        assert info["changed_vs_seen"] is True

    def test_save_and_load_round_trip(self, tmp_path: Path):
        path = tmp_path / "state.json"
        save_judge_model_state(
            model_snapshot_seen="claude-sonnet-4-6.2",
            path=path,
        )
        loaded = load_judge_model_state(path)
        assert loaded["model_snapshot_seen"] == "claude-sonnet-4-6.2"
        assert "last_seen_at" in loaded

    def test_corrupt_state_file_returns_empty(self, tmp_path: Path):
        path = tmp_path / "state.json"
        path.write_text("not valid json {", encoding="utf-8")
        assert load_judge_model_state(path) == {}

    def test_empty_snapshot_never_changes(self, tmp_path: Path):
        state_path = tmp_path / "state.json"
        save_judge_model_state(
            model_snapshot_seen="anything",
            path=state_path,
        )
        changed, _ = judge_model_changed(
            current_snapshot="",
            pinned_version="anything",
            state_path=state_path,
        )
        assert changed is False


# ---------------------------------------------------------------------------
# calibrate.py — score loop (TTY mocked)
# ---------------------------------------------------------------------------


class TestCalibrateScoreLoop:
    def _make_io(self, answers: list[str]):
        from scripts.calibrate import _ScoreIO

        answers_iter = iter(answers)
        captured: list[str] = []

        def reader(prompt: str) -> str:
            return next(answers_iter)

        def writer(text: str) -> None:
            captured.append(text)

        return _ScoreIO(reader=reader, writer=writer), captured

    def test_score_loop_records_entries(self, tmp_path: Path):
        from scripts.calibrate import _score_loop

        samples = [
            {
                "id": "abc",
                "agent": "diary",
                "user_message": "How was my day?",
                "response": "You had 3 meetings.",
                "auto_scores": {
                    "relevance": 4.0,
                    "actionability": 3.5,
                    "tone": 4.5,
                    "conciseness": 4.0,
                },
                "auto_reasoning": "good",
            },
        ]
        io, _ = self._make_io(
            [
                "4",  # relevance
                "3",  # actionability
                "k",  # tone — keep
                "4.5",  # conciseness
            ],
        )
        out_path = tmp_path / "human.jsonl"
        count = _score_loop(samples, out_path, io=io)
        assert count == 1
        assert out_path.exists()
        row = json.loads(out_path.read_text().strip())
        assert row["id"] == "abc"
        assert row["human_scores"]["relevance"] == 4.0
        assert row["human_scores"]["actionability"] == 3.0
        assert row["human_scores"]["tone"] == 4.5  # kept from auto
        assert row["human_scores"]["conciseness"] == 4.5

    def test_score_loop_rejects_out_of_range_then_accepts(self, tmp_path: Path):
        from scripts.calibrate import _score_loop

        samples = [
            {
                "id": "x",
                "agent": "memory",
                "user_message": "note X",
                "response": "Stored.",
                "auto_scores": {
                    "relevance": 3.0,
                    "actionability": 3.0,
                    "tone": 3.0,
                    "conciseness": 3.0,
                },
            },
        ]
        io, _ = self._make_io(
            [
                "9",  # invalid
                "4",  # relevance
                "abc",  # invalid
                "3",  # actionability
                "2",  # tone
                "1",  # conciseness
            ],
        )
        out_path = tmp_path / "human.jsonl"
        count = _score_loop(samples, out_path, io=io)
        assert count == 1
        row = json.loads(out_path.read_text().strip())
        assert row["human_scores"]["relevance"] == 4.0

    def test_score_loop_skips_already_scored(self, tmp_path: Path):
        from scripts.calibrate import _score_loop

        samples = [
            {
                "id": "already",
                "agent": "diary",
                "user_message": "x",
                "response": "y",
                "auto_scores": {
                    d: 3.0 for d in ("relevance", "actionability", "tone", "conciseness")
                },
            },
        ]
        out_path = tmp_path / "human.jsonl"
        io, _ = self._make_io([])  # no prompts should be consumed
        count = _score_loop(
            samples,
            out_path,
            io=io,
            already_scored_ids={"already"},
        )
        assert count == 0
        # File may be opened in append-mode but must contain no rows.
        if out_path.exists():
            assert out_path.read_text() == ""


# ---------------------------------------------------------------------------
# calibrate.py — report generation
# ---------------------------------------------------------------------------


class TestCalibrateReport:
    def test_compute_drift_calculates_means(self):
        from scripts.calibrate import _compute_drift

        rows = [
            {
                "agent": "diary",
                "human_scores": {"relevance": 4.0, "actionability": 3.5},
                "auto_scores": {"relevance": 3.0, "actionability": 4.0},
            },
            {
                "agent": "diary",
                "human_scores": {"relevance": 5.0, "actionability": 3.0},
                "auto_scores": {"relevance": 3.5, "actionability": 4.5},
            },
        ]
        summary = _compute_drift(rows)
        assert "diary" in summary
        rel = summary["diary"]["relevance"]
        assert rel["n"] == 2
        # drifts: (4-3)=+1.0, (5-3.5)=+1.5 → mean +1.25
        assert rel["mean"] == pytest.approx(1.25)

    def test_report_markdown_contains_agents_and_block_flag(self, tmp_path: Path):
        from scripts.calibrate import _build_report_markdown

        summary = {
            "diary": {
                "relevance": {"mean": 0.6, "p10": 0.4, "p90": 0.8, "n": 5},
                "tone": {"mean": 0.1, "p10": 0.0, "p90": 0.2, "n": 5},
            },
        }
        # Two consecutive months over threshold → block
        drift_series = {
            "diary": {
                "relevance": [0.55, 0.6],
                "tone": [0.1, 0.1],
            },
        }
        md = _build_report_markdown(
            month="2026-04",
            summary=summary,
            drift_series=drift_series,
        )
        assert "# Calibration Report — 2026-04" in md
        assert "| relevance | 5 |" in md
        assert "YES" in md  # block flag fired
        assert "Blocked from prompt edits" in md

    def test_previous_months_wraps_year(self):
        from scripts.calibrate import _previous_months

        assert _previous_months("2026-02", 3) == ["2025-11", "2025-12", "2026-01"]

    def test_to_5pt_conversion(self):
        from scripts.calibrate import _to_5pt

        assert _to_5pt(0.8) == 4.0
        assert _to_5pt(None) is None
        assert _to_5pt(1.0) == 5.0


# ---------------------------------------------------------------------------
# Auto-trigger integration — a smoke that the config flag reaches the
# version-change helper.
# ---------------------------------------------------------------------------


def test_auto_trigger_on_model_change_e2e(tmp_path: Path, monkeypatch):
    state_path = tmp_path / "state.json"

    # First boot: seed state with the pinned version.
    save_judge_model_state(
        model_snapshot_seen="claude-sonnet-4-6",
        path=state_path,
    )

    # Anthropic ships a new snapshot — current != pinned + != last seen.
    changed, info = judge_model_changed(
        current_snapshot="claude-sonnet-4-6.1",
        pinned_version="claude-sonnet-4-6",
        state_path=state_path,
    )
    assert changed
    assert info["changed_vs_pin"]
    assert info["changed_vs_seen"]

    # After the operator acknowledges (we save the new snapshot), further boots
    # with the same snapshot should NOT re-fire the alert.
    save_judge_model_state(
        model_snapshot_seen="claude-sonnet-4-6.1",
        path=state_path,
    )
    changed, _ = judge_model_changed(
        current_snapshot="claude-sonnet-4-6.1",
        pinned_version="claude-sonnet-4-6.1",
        state_path=state_path,
    )
    assert changed is False
