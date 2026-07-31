"""Golden-dataset promotion CLI (Phase 4.5).

Usage:
    uv run python -m scripts.dataset_promote review <proposal_file.jsonl>

TTY loop: for each proposed example the reviewer sees prompt / response /
cluster / reason and presses [y]es / [n]o / [e]dit / [q]uit. Approved rows
get ``human_verified=true`` and are appended to the agent's golden dataset
under a new version, e.g. ``memory.v1.json`` -> ``memory.v2.json``.

Augment-don't-replace: the existing dataset cases are kept by default and
new verified rows are appended. No row is ever deleted unless the reviewer
explicitly passes ``--prune``.

File lifecycle (atomic, PR-friendly):
    data/evaluation/datasets/memory.v1.json  ->  (archived, untouched)
    data/evaluation/datasets/memory.v2.json  <-  NEW, augmented
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Exit codes
_EXIT_OK = 0
_EXIT_USER_ABORT = 2
_EXIT_BAD_ARGS = 3


# ---------- file discovery helpers ----------


_VERSION_RE = re.compile(r"^(?P<agent>[a-z0-9_]+)\.v(?P<n>\d+)\.json$")


def _find_latest_version(datasets_dir: Path, agent: str) -> tuple[Path, int]:
    """Return (path, version_number) for the highest-versioned file for agent."""
    best_n = -1
    best_path: Path | None = None
    for p in datasets_dir.glob(f"{agent}.v*.json"):
        m = _VERSION_RE.match(p.name)
        if not m:
            continue
        if m.group("agent") != agent:
            continue
        n = int(m.group("n"))
        if n > best_n:
            best_n = n
            best_path = p
    if best_path is None or best_n < 0:
        raise FileNotFoundError(
            f"No dataset file found matching {agent}.v*.json in {datasets_dir}. "
            "Create the v1 file first — curation augments rather than bootstraps."
        )
    return best_path, best_n


def _agent_from_proposal(proposal_path: Path) -> str:
    """Infer agent name from ``<agent>_<date>.jsonl`` filename."""
    stem = proposal_path.stem
    # stem is like 'memory_2026-04-20'; split off the date suffix.
    m = re.match(r"^(?P<agent>[a-z0-9_]+?)_(\d{4}-\d{2}-\d{2})$", stem)
    if not m:
        raise ValueError(f"Proposal filename must match '<agent>_YYYY-MM-DD.jsonl', got {stem!r}.")
    return m.group("agent")


# ---------- proposal loading ----------


def load_proposals(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL proposal file into a list of dicts."""
    if not path.is_file():
        raise FileNotFoundError(f"Proposal file not found: {path}")
    proposals: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            proposals.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no} is not valid JSON: {exc}") from exc
    return proposals


# ---------- TTY review loop ----------


def _render_proposal(proposal: dict[str, Any], idx: int, total: int) -> str:
    """Build the preview text shown to the reviewer."""
    score = proposal.get("auto_judge_final")
    score_text = f"{score:.2f}" if isinstance(score, (int, float)) else "unscored"
    return (
        f"\n=== [{idx}/{total}] {proposal.get('agent', '?')} ===\n"
        f"  source_interaction_id: {proposal.get('source_interaction_id')}\n"
        f"  cluster_id: {proposal.get('cluster_id')}\n"
        f"  reason: {proposal.get('reason')}\n"
        f"  auto_judge_final: {score_text}\n"
        f"  rubric_version: {proposal.get('rubric_version')}\n"
        f"  -- prompt --\n  {proposal.get('prompt', '')}\n"
        f"  -- response --\n  {proposal.get('response', '')}\n"
    )


def review_proposals(
    proposals: list[dict[str, Any]],
    *,
    input_fn=input,
    output=sys.stdout,
) -> list[dict[str, Any]]:
    """Interactive approval loop. Returns the list of approved (verified) rows.

    ``input_fn`` / ``output`` are injected so tests can drive the loop
    without a real TTY.
    """
    approved: list[dict[str, Any]] = []
    total = len(proposals)
    for idx, proposal in enumerate(proposals, start=1):
        output.write(_render_proposal(proposal, idx, total))
        output.flush()
        while True:
            ans = (input_fn("  approve? [y]es / [n]o / [e]dit / [q]uit: ") or "").strip().lower()
            if ans in {"y", "yes"}:
                approved.append(_promote_proposal(proposal))
                break
            if ans in {"n", "no"}:
                output.write("  rejected.\n")
                break
            if ans in {"e", "edit"}:
                new_prompt = input_fn("  new prompt (blank to keep): ").strip()
                new_response = input_fn("  new response (blank to keep): ").strip()
                edited = dict(proposal)
                if new_prompt:
                    edited["prompt"] = new_prompt
                if new_response:
                    edited["response"] = new_response
                approved.append(_promote_proposal(edited))
                break
            if ans in {"q", "quit"}:
                output.write("  quitting review.\n")
                return approved
            output.write("  please answer y/n/e/q.\n")
    return approved


def _promote_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    """Flip ``human_verified`` on a copy of the proposal."""
    promoted = dict(proposal)
    promoted["human_verified"] = True
    promoted["promoted_at"] = datetime.now(UTC).isoformat()
    return promoted


# ---------- dataset writing (augment, never replace) ----------


def _proposal_to_case(proposal: dict[str, Any], existing_ids: set[str]) -> dict[str, Any] | None:
    """Convert an approved proposal into a golden-dataset case row.

    Returns None if a case with the same source_interaction_id already
    exists in the dataset (idempotent reruns).
    """
    source_id = proposal.get("source_interaction_id")
    case_id = f"curated_{source_id}"
    if case_id in existing_ids:
        return None
    return {
        "id": case_id,
        "prompt": proposal.get("prompt", ""),
        "expected_response": proposal.get("response", ""),
        "provenance": {
            "source_interaction_id": source_id,
            "promoted_at": proposal.get("promoted_at"),
            "rubric_version": proposal.get("rubric_version"),
            "human_verified": bool(proposal.get("human_verified", False)),
            "cluster_id": proposal.get("cluster_id"),
            "reason": proposal.get("reason"),
        },
    }


def augment_dataset(
    *,
    datasets_dir: Path,
    agent: str,
    approved: Iterable[dict[str, Any]],
    prune: bool = False,
) -> Path:
    """Write a new dataset version with verified rows appended.

    The old version file is left in place (archived by name). A brand
    new ``<agent>.v<N+1>.json`` file is written. Never mutates prior
    versions — that's what git history is for.
    """
    src_path, n = _find_latest_version(datasets_dir, agent)
    data = json.loads(src_path.read_text(encoding="utf-8"))
    existing_cases: list[dict[str, Any]] = list(data.get("cases", []))
    existing_ids = {case.get("id") for case in existing_cases if case.get("id")}

    new_cases: list[dict[str, Any]] = []
    for proposal in approved:
        case = _proposal_to_case(proposal, existing_ids=existing_ids)
        if case is None:
            continue
        new_cases.append(case)
        existing_ids.add(case["id"])

    if prune:
        # Explicit opt-in: drop any case marked with a legacy 'deprecated' flag.
        existing_cases = [c for c in existing_cases if not c.get("deprecated")]

    merged_cases = existing_cases + new_cases
    new_version = n + 1
    new_data = {
        **data,
        "version": f"v{new_version}",
        "dataset_id": data.get("dataset_id", "").rsplit("-", 1)[0] + f"-v{new_version}"
        if data.get("dataset_id")
        else f"{agent}-v{new_version}",
        "cases": merged_cases,
    }
    out_path = datasets_dir / f"{agent}.v{new_version}.json"
    # Atomic write: temp file + rename.
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(new_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    shutil.move(str(tmp_path), str(out_path))
    return out_path


# ---------- CLI entry point ----------


def _cmd_review(args: argparse.Namespace) -> int:
    proposal_path = Path(args.proposal_file).resolve()
    agent = _agent_from_proposal(proposal_path)
    datasets_dir = Path(args.datasets_dir).resolve()

    proposals = load_proposals(proposal_path)
    if not proposals:
        sys.stdout.write(f"No proposals in {proposal_path}. Nothing to do.\n")
        return _EXIT_OK

    approved = review_proposals(proposals)
    if not approved:
        sys.stdout.write("No proposals approved.\n")
        return _EXIT_USER_ABORT

    out_path = augment_dataset(
        datasets_dir=datasets_dir,
        agent=agent,
        approved=approved,
        prune=args.prune,
    )
    sys.stdout.write(
        f"Wrote {len(approved)} new verified case(s) to {out_path}.\n"
        f"Prior version left in place for audit.\n"
    )
    return _EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dataset_promote",
        description="Promote auto-curated dataset proposals into a new golden-dataset version.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    review = sub.add_parser("review", help="Interactive y/n/e/q review over a proposal JSONL.")
    review.add_argument("proposal_file", help="Path to <agent>_<date>.jsonl produced by curation.")
    review.add_argument(
        "--datasets-dir",
        default="data/evaluation/datasets",
        help="Directory containing <agent>.vN.json files.",
    )
    review.add_argument(
        "--prune",
        action="store_true",
        help="Also drop any case flagged 'deprecated'. Off by default (augment only).",
    )
    review.set_defaults(func=_cmd_review)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return _EXIT_BAD_ARGS


if __name__ == "__main__":
    raise SystemExit(main())
