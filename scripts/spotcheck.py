"""Weekly human spot-check CLI.

Three subcommands:

- ``pending``: list unfilled spotcheck queue files (``*_queue.md`` without a
  sibling ``*_done.md``).
- ``score <queue>``: TTY loop reading each interaction from the embedded
  payload in the queue file, prompting ✓ / ✗ / edit per row. Writes
  ``<YYYY-MM-DD>_done.md``.
- ``weekly-summary``: aggregate the last 4 weeks' ``*_done.md`` files and
  report mismatch rate per agent.

The queue file format matches what ``src/app/workers/spotcheck.py`` writes —
a markdown table followed by a ``<!-- spotcheck-data ... -->`` JSON block
containing the full records. This way the CLI doesn't need DB access.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

SPOTCHECK_DIR = Path("data/evaluation/spotcheck")
_PAYLOAD_RE = re.compile(
    r"<!-- spotcheck-data\s*(?P<payload>.*?)\s*-->",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


@dataclass
class _ScoreIO:
    reader: Callable[[str], str]
    writer: Callable[[str], None]


def _default_io() -> _ScoreIO:
    return _ScoreIO(reader=input, writer=lambda s: print(s))


def _load_queue_records(queue_path: Path) -> list[dict]:
    """Extract the JSON payload from the markdown queue file."""
    content = queue_path.read_text(encoding="utf-8")
    match = _PAYLOAD_RE.search(content)
    if match is None:
        return []
    try:
        return json.loads(match.group("payload"))
    except json.JSONDecodeError:
        return []


def _done_path_for(queue_path: Path) -> Path:
    """Return the sibling ``*_done.md`` path for a queue file."""
    return queue_path.with_name(queue_path.name.replace("_queue.md", "_done.md"))


# ---------------------------------------------------------------------------
# pending
# ---------------------------------------------------------------------------


def _cmd_pending(_: argparse.Namespace) -> None:
    if not SPOTCHECK_DIR.exists():
        print("No spotcheck queue directory yet.")
        return

    queues = sorted(SPOTCHECK_DIR.glob("*_queue.md"))
    pending = [q for q in queues if not _done_path_for(q).exists()]

    if not pending:
        print("No pending spot-check queues.")
        return

    print(f"Pending spot-check queues ({len(pending)}):")
    for path in pending:
        records = _load_queue_records(path)
        print(f"  {path}  ({len(records)} records)")


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------


def _prompt_verdict(io: _ScoreIO) -> tuple[str, str]:
    """Return (mark, note) for one record. mark is one of ✓/✗/edit."""
    while True:
        raw = io.reader("  ✓ / ✗ / edit / skip: ").strip().lower()
        if raw in ("✓", "y", "ok", "check"):
            return "✓", io.reader("  note (optional): ").strip()
        if raw in ("✗", "n", "x", "no"):
            return "✗", io.reader("  note: ").strip()
        if raw.startswith("e"):
            return "edit", io.reader("  note (what you'd change): ").strip()
        if raw.startswith("s"):
            return "skip", ""
        io.writer("  invalid — enter ✓ / ✗ / edit / skip")


def _score_loop(
    records: Iterable[dict],
    *,
    io: _ScoreIO | None = None,
) -> list[dict]:
    """Walk records, collect verdicts, return rows for the ``_done.md`` file."""
    ioc = io or _default_io()
    rows: list[dict] = []
    for record in records:
        ioc.writer("")
        ioc.writer("=" * 72)
        ioc.writer(f"[{record.get('agent', '?')}] id={record.get('id', '?')}")
        ioc.writer(f"USER: {(record.get('user_message') or '')[:500]}")
        ioc.writer(f"ASSISTANT: {(record.get('response') or '')[:1000]}")
        auto = record.get("auto_mean_5pt")
        ioc.writer(
            f"AUTO MEAN: {auto if auto is not None else 'N/A'}/5",
        )

        mark, note = _prompt_verdict(ioc)
        rows.append(
            {
                "id": record.get("id"),
                "agent": record.get("agent"),
                "mark": mark,
                "note": note,
                "auto_mean_5pt": auto,
                "reviewed_at": datetime.now(UTC).isoformat(),
            },
        )
    return rows


def _build_done_markdown(queue_path: Path, rows: list[dict]) -> str:
    date_str = queue_path.stem.replace("_queue", "")
    lines = [
        f"# Spot-check — {date_str} — DONE",
        "",
        f"Completed at: {datetime.now(UTC).isoformat()}",
        f"Records reviewed: {sum(1 for r in rows if r['mark'] != 'skip')}",
        "",
        "| ID | Agent | Auto /5 | Mark | Note |",
        "|----|-------|---------|------|------|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("id", ""))[:8],
                    row.get("agent", ""),
                    (
                        f"{row['auto_mean_5pt']:.2f}"
                        if row.get("auto_mean_5pt") is not None
                        else "N/A"
                    ),
                    row.get("mark", ""),
                    (row.get("note") or "").replace("|", "/"),
                ]
            )
            + " |",
        )
    lines.extend(["", "<!-- spotcheck-done", json.dumps(rows), "-->", ""])
    return "\n".join(lines)


def _cmd_score(args: argparse.Namespace) -> None:
    queue_path = Path(args.queue)
    if not queue_path.exists():
        print(f"Queue file not found: {queue_path}")
        sys.exit(1)

    records = _load_queue_records(queue_path)
    if not records:
        print("Queue file contains no records.")
        sys.exit(1)

    rows = _score_loop(records)
    if not rows:
        print("No rows scored.")
        return

    done_path = _done_path_for(queue_path)
    done_path.write_text(_build_done_markdown(queue_path, rows), encoding="utf-8")
    print(f"\nWrote {done_path}")


# ---------------------------------------------------------------------------
# weekly-summary
# ---------------------------------------------------------------------------


def _load_done_rows(path: Path) -> list[dict]:
    content = path.read_text(encoding="utf-8")
    match = re.search(r"<!-- spotcheck-done\s*(?P<payload>.*?)\s*-->", content, re.DOTALL)
    if match is None:
        return []
    try:
        return json.loads(match.group("payload"))
    except json.JSONDecodeError:
        return []


def _weekly_summary(*, weeks: int = 4, now: datetime | None = None) -> dict:
    """Aggregate the last ``weeks`` weeks of done files into mismatch rates."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=weeks * 7)

    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "mismatch": 0, "edit": 0, "ok": 0},
    )

    if not SPOTCHECK_DIR.exists():
        return {"weeks": weeks, "per_agent": {}, "files_considered": 0}

    files = 0
    for path in sorted(SPOTCHECK_DIR.glob("*_done.md")):
        date_stem = path.stem.replace("_done", "")
        try:
            file_date = datetime.strptime(date_stem, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            continue
        if file_date < cutoff:
            continue
        files += 1
        for row in _load_done_rows(path):
            agent = row.get("agent") or "unknown"
            mark = row.get("mark") or ""
            if mark == "skip":
                continue
            counts[agent]["total"] += 1
            if mark == "✓":
                counts[agent]["ok"] += 1
            elif mark == "✗":
                counts[agent]["mismatch"] += 1
            elif mark == "edit":
                counts[agent]["edit"] += 1
                counts[agent]["mismatch"] += 1  # edits count as a mismatch signal

    per_agent = {
        agent: {
            **vals,
            "mismatch_rate": (vals["mismatch"] / vals["total"] if vals["total"] else 0.0),
        }
        for agent, vals in counts.items()
    }
    return {"weeks": weeks, "per_agent": per_agent, "files_considered": files}


def _cmd_weekly_summary(args: argparse.Namespace) -> None:
    summary = _weekly_summary(weeks=args.weeks)
    per_agent = summary["per_agent"]
    if not per_agent:
        print(f"No completed spot-checks in the last {summary['weeks']} weeks.")
        return

    print(
        f"Spot-check summary — last {summary['weeks']} weeks "
        f"({summary['files_considered']} done files)",
    )
    print()
    print("| Agent | Reviewed | ✓ | ✗ | Edit | Mismatch rate |")
    print("|-------|----------|---|---|------|---------------|")
    for agent in sorted(per_agent):
        vals = per_agent[agent]
        print(
            f"| {agent} | {vals['total']} | {vals['ok']} | "
            f"{vals['mismatch'] - vals['edit']} | {vals['edit']} | "
            f"{vals['mismatch_rate']:.0%} |",
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly spot-check CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pending", help="List unfilled spot-check queues")

    score_p = sub.add_parser("score", help="Score a queue file interactively")
    score_p.add_argument("queue", help="Path to *_queue.md")

    summary_p = sub.add_parser("weekly-summary", help="Aggregate last N weeks")
    summary_p.add_argument("--weeks", type=int, default=4, help="Weeks to include")

    args = parser.parse_args()

    if args.command == "pending":
        _cmd_pending(args)
    elif args.command == "score":
        _cmd_score(args)
    elif args.command == "weekly-summary":
        _cmd_weekly_summary(args)


if __name__ == "__main__":
    main()
