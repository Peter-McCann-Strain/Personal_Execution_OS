"""Alembic environment configuration — async PostgreSQL."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.app.config import get_settings
from src.app.persistence.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Get database URL from application settings."""
    settings = get_settings()
    return settings.database_url.get_secret_value()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL without connecting."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    settings = get_settings()
    connect_args = {"statement_cache_size": 0} if settings.db_pgbouncer_mode else {}
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    # Use an owning transaction. Executing SET on a plain ``connect()`` starts
    # an implicit transaction before Alembic's context can own it, which means
    # closing the connection rolls every migration back, including the version
    # table update.
    async with connectable.begin() as connection:
        # Managed PostgreSQL defaults can cancel long-running DDL such as
        # ALTER TABLE or CREATE INDEX before it completes.
        await connection.exec_driver_sql("SET statement_timeout = 0")
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations online.

    If a pre-existing Connection was injected via `alembic_cfg.attributes['connection']`
    (e.g. from the integration test fixture), migrate against that connection
    directly - sync - rather than spinning a new async engine. This lets tests
    reuse their testcontainers engine without depending on Settings.
    """
    injected = config.attributes.get("connection", None)
    if injected is not None:
        do_run_migrations(injected)
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
