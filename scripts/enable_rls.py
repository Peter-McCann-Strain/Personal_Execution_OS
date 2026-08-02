"""Check account-scoped PostgreSQL tables for effective RLS policies.

RLS policy creation belongs in Alembic migrations. This command is deliberately
read-only so an operational check cannot lock tables by enabling RLS without
the correct table-specific policy.
"""

from __future__ import annotations

import asyncio
import sys

import asyncpg

from src.app.config import get_settings


def _asyncpg_dsn(database_url: str) -> str:
    """Normalise a SQLAlchemy URL to a DSN accepted by asyncpg."""
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
        if database_url.startswith(prefix):
            return "postgresql://" + database_url[len(prefix) :]
    return database_url


async def _fetch_unprotected(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        """
        WITH required AS (
          SELECT DISTINCT c.oid, c.relname, c.relrowsecurity
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
          LEFT JOIN pg_attribute a
            ON a.attrelid = c.oid
           AND a.attname = 'account_id'
           AND NOT a.attisdropped
          WHERE n.nspname = 'public'
            AND c.relkind = 'r'
            AND (a.attname IS NOT NULL OR c.relname IN ('accounts', 'users'))
        )
        SELECT relname
        FROM required
        WHERE NOT relrowsecurity
           OR NOT EXISTS (
                SELECT 1
                FROM pg_policy p
                WHERE p.polrelid = required.oid
                  AND p.polname = 'app_account_isolation'
           )
        ORDER BY relname
        """
    )
    return [row["relname"] for row in rows]


async def _check(conn: asyncpg.Connection) -> int:
    unprotected = await _fetch_unprotected(conn)
    if not unprotected:
        print("OK: all required account-scoped public tables have RLS and isolation policy.")
        return 0
    print(f"FAIL: {len(unprotected)} tables without RLS:")
    for table in unprotected:
        print(f"  - {table}")
    return 1


async def _run() -> int:
    settings = get_settings()
    dsn = _asyncpg_dsn(settings.database_url.get_secret_value())
    conn = await asyncpg.connect(dsn)
    try:
        return await _check(conn)
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args not in ([], ["--check"]):
        print("Usage: python -m scripts.enable_rls [--check]", file=sys.stderr)
        return 2
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
