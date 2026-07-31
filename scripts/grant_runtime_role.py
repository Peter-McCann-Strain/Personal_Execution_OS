"""Grant the least-privilege application role access to migrated objects."""

from __future__ import annotations

import asyncio

import asyncpg

from scripts.enable_rls import _asyncpg_dsn
from src.app.config import get_settings


async def _run() -> None:
    settings = get_settings()
    dsn = _asyncpg_dsn(settings.database_url.get_secret_value())
    connection = await asyncpg.connect(dsn)
    try:
        await connection.execute(
            """
            GRANT USAGE ON SCHEMA public TO assistant_runtime;
            GRANT SELECT, INSERT, UPDATE, DELETE
              ON ALL TABLES IN SCHEMA public TO assistant_runtime;
            GRANT USAGE, SELECT, UPDATE
              ON ALL SEQUENCES IN SCHEMA public TO assistant_runtime;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public
              GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO assistant_runtime;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public
              GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO assistant_runtime;
            """
        )
    finally:
        await connection.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
