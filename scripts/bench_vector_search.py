"""Benchmark IVFFLAT vs HNSW on a synthetic 768-d corpus.

Seeds ``N`` random unit vectors into a disposable pgvector container,
builds both index types, runs ``QUERIES`` top-k queries against each,
and reports:

* p50 / p95 latency per index
* recall@k vs an exact nearest-neighbour baseline (seq-scan, no index)

Writes a Markdown report to::

    data/evaluation/reports/vector_bench_YYYY-MM-DD.md

The script is self-contained — no app imports. It uses
``testcontainers[postgres]`` with the pgvector image; if Docker is not
reachable the script prints a clean message and exits 0.

Run::

    uv run python -m scripts.bench_vector_search
    # Optional flags
    uv run python -m scripts.bench_vector_search --rows 5000 --queries 200
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import socket
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

logger = structlog.get_logger()

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REPORT_DIR = _REPO_ROOT / "data" / "evaluation" / "reports"

_DIM = 768
_DEFAULT_ROWS = 1000
_DEFAULT_QUERIES = 100
_K = 10

# HNSW knobs under test — keep in sync with the Alembic migration.
_HNSW_M = 16
_HNSW_EF_CONSTRUCTION = 64
_IVFFLAT_LISTS = 100


@dataclass
class BenchResult:
    index: str
    p50_ms: float
    p95_ms: float
    mean_recall_at_k: float
    queries: int
    note: str = ""


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(0.2)
            sock.connect("/var/run/docker.sock")
    except OSError:
        return bool(os.environ.get("DOCKER_HOST"))
    return True


def _random_unit_vector(rng: random.Random) -> list[float]:
    raw = [rng.gauss(0, 1) for _ in range(_DIM)]
    norm = sum(x * x for x in raw) ** 0.5
    if norm == 0:
        return [1.0] + [0.0] * (_DIM - 1)
    return [x / norm for x in raw]


def _vector_literal(vec: list[float]) -> str:
    # pgvector accepts "[x, y, ...]" as a text literal we can cast.
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1))))
    return ordered[k]


def _time_query(cur, sql: str, params: tuple) -> tuple[list[str], float]:
    start = time.perf_counter()
    cur.execute(sql, params)
    rows = cur.fetchall()
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    ids = [str(r[0]) for r in rows]
    return ids, elapsed_ms


def _build_report(
    rows: int,
    queries: int,
    results: list[BenchResult],
    pgvector_version: str,
) -> str:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    lines = [
        "# Vector index benchmark",
        "",
        f"- Generated: {now}",
        f"- Corpus: {rows} synthetic 768-d unit vectors",
        f"- Queries: {queries} (k = {_K})",
        f"- pgvector version: {pgvector_version}",
        f"- HNSW params: m = {_HNSW_M}, ef_construction = {_HNSW_EF_CONSTRUCTION}",
        f"- IVFFLAT params: lists = {_IVFFLAT_LISTS}",
        "",
        "## Results",
        "",
        "| Index | p50 (ms) | p95 (ms) | recall@10 | note |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r.index} | {r.p50_ms:.2f} | {r.p95_ms:.2f} | {r.mean_recall_at_k:.3f} | {r.note} |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "The exact baseline runs a sequential scan and is used only as the",
        "ground-truth neighbour set for recall@10. Production queries always",
        "go through an index.",
        "",
        "HNSW should beat IVFFLAT on both latency *and* recall at this scale.",
        "If IVFFLAT wins on either, the HNSW parameters are too conservative",
        "(raise `ef_construction` or the per-query `hnsw.ef_search`).",
        "",
    ]
    return "\n".join(lines)


def run(rows: int, queries: int) -> int:
    if not _docker_available():
        print("Docker daemon unavailable — skipping vector benchmark.")
        return 0

    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        print("testcontainers[postgres] is not installed — skipping benchmark.")
        return 0

    try:
        import psycopg
    except ImportError:
        print("psycopg is not installed — skipping benchmark.")
        return 0

    rng = random.Random(0xC0FFEE)  # noqa: S311 — deterministic bench seed, not security-sensitive
    vectors = [_random_unit_vector(rng) for _ in range(rows)]
    query_vectors = [_random_unit_vector(rng) for _ in range(queries)]

    container = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="bench",
        password="bench",
        dbname="bench",
        driver=None,
    ).with_env("POSTGRES_HOST_AUTH_METHOD", "trust")
    container.start()
    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        dsn = f"host={host} port={port} user=bench password=bench dbname=bench"

        with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            row = cur.fetchone()
            pgvector_version = row[0] if row else "unknown"

            cur.execute(
                f"CREATE TABLE bench_vec (  id bigserial PRIMARY KEY,  embedding vector({_DIM}))"
            )

            # Bulk insert. 1k rows is small enough to send row-by-row;
            # COPY is overkill for the default size.
            cur.execute("BEGIN")
            for vec in vectors:
                cur.execute(
                    "INSERT INTO bench_vec (embedding) VALUES (%s::vector)",
                    (_vector_literal(vec),),
                )
            cur.execute("COMMIT")

            # Ground-truth neighbours via exact seq-scan.
            exact_neighbours: list[list[str]] = []
            exact_latencies: list[float] = []
            cur.execute("SET enable_indexscan = off")
            cur.execute("SET enable_bitmapscan = off")
            for qv in query_vectors:
                ids, elapsed = _time_query(
                    cur,
                    "SELECT id FROM bench_vec ORDER BY embedding <=> %s::vector LIMIT %s",
                    (_vector_literal(qv), _K),
                )
                exact_neighbours.append(ids)
                exact_latencies.append(elapsed)
            cur.execute("SET enable_indexscan = on")
            cur.execute("SET enable_bitmapscan = on")

            results: list[BenchResult] = [
                BenchResult(
                    index="exact (seq-scan)",
                    p50_ms=_percentile(exact_latencies, 50),
                    p95_ms=_percentile(exact_latencies, 95),
                    mean_recall_at_k=1.0,
                    queries=queries,
                    note="ground truth",
                ),
            ]

            # --- IVFFLAT ---
            cur.execute("SET maintenance_work_mem = '1GB'")
            cur.execute(
                "CREATE INDEX bench_ivfflat ON bench_vec "
                f"USING ivfflat (embedding vector_cosine_ops) "
                f"WITH (lists = {_IVFFLAT_LISTS})"
            )
            cur.execute("ANALYZE bench_vec")
            cur.execute("SET ivfflat.probes = 10")

            ivf_latencies: list[float] = []
            ivf_recalls: list[float] = []
            for qv, truth in zip(query_vectors, exact_neighbours, strict=True):
                ids, elapsed = _time_query(
                    cur,
                    "SELECT id FROM bench_vec ORDER BY embedding <=> %s::vector LIMIT %s",
                    (_vector_literal(qv), _K),
                )
                ivf_latencies.append(elapsed)
                ivf_recalls.append(len(set(ids) & set(truth)) / float(_K))
            results.append(
                BenchResult(
                    index="ivfflat (pre-migration sim)",
                    p50_ms=_percentile(ivf_latencies, 50),
                    p95_ms=_percentile(ivf_latencies, 95),
                    mean_recall_at_k=statistics.fmean(ivf_recalls),
                    queries=queries,
                    note=f"lists={_IVFFLAT_LISTS}, probes=10",
                ),
            )

            cur.execute("DROP INDEX bench_ivfflat")

            # --- HNSW ---
            cur.execute(
                "CREATE INDEX bench_hnsw ON bench_vec "
                f"USING hnsw (embedding vector_cosine_ops) "
                f"WITH (m = {_HNSW_M}, ef_construction = {_HNSW_EF_CONSTRUCTION})"
            )
            cur.execute("ANALYZE bench_vec")

            # Sweep ef_search against the two production presets.
            # Use psycopg.sql composition so ty's LiteralString check is
            # satisfied even though ef_search is a loop-local integer.
            from psycopg import sql

            for label, ef_search in [("MEMORY", 20), ("DEFAULT", 40), ("RESEARCH", 80)]:
                cur.execute(
                    sql.SQL("SET hnsw.ef_search = {}").format(sql.Literal(ef_search)),
                )
                hnsw_latencies: list[float] = []
                hnsw_recalls: list[float] = []
                for qv, truth in zip(query_vectors, exact_neighbours, strict=True):
                    ids, elapsed = _time_query(
                        cur,
                        "SELECT id FROM bench_vec ORDER BY embedding <=> %s::vector LIMIT %s",
                        (_vector_literal(qv), _K),
                    )
                    hnsw_latencies.append(elapsed)
                    hnsw_recalls.append(len(set(ids) & set(truth)) / float(_K))
                results.append(
                    BenchResult(
                        index=f"hnsw [{label}]",
                        p50_ms=_percentile(hnsw_latencies, 50),
                        p95_ms=_percentile(hnsw_latencies, 95),
                        mean_recall_at_k=statistics.fmean(hnsw_recalls),
                        queries=queries,
                        note=f"ef_search={ef_search}",
                    ),
                )

        report = _build_report(rows, queries, results, pgvector_version)
    finally:
        container.stop()

    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).date().isoformat()
    report_path = _REPORT_DIR / f"vector_bench_{today}.md"
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nReport written to {report_path.relative_to(_REPO_ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=_DEFAULT_ROWS)
    parser.add_argument("--queries", type=int, default=_DEFAULT_QUERIES)
    args = parser.parse_args()
    return run(args.rows, args.queries)


if __name__ == "__main__":
    sys.exit(main())
