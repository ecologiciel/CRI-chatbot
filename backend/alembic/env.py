"""Alembic environment configuration.

Supports:
- Async migrations via asyncpg
- Multi-schema: set ALEMBIC_SCHEMA env var to target a specific tenant schema
- Default: migrates 'public' schema (shared tables)

Usage:
    cd backend
    alembic upgrade head                          # migrate public schema
    ALEMBIC_SCHEMA=tenant_rabat alembic upgrade head  # migrate a tenant schema
"""

import asyncio
import os
import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings

# Import models package — triggers all model registrations on Base.metadata
from app.models import Base  # noqa: F401

config = context.config
settings = get_settings()

# Override sqlalchemy.url with actual database URL (async driver)
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Schema to migrate (default: public)
target_schema = os.getenv("ALEMBIC_SCHEMA", "public")

# Validate schema name against SQL injection
if not re.match(r"^[a-z_][a-z0-9_]*$", target_schema):
    msg = f"Invalid schema name: {target_schema!r}. Must match [a-z_][a-z0-9_]*"
    raise ValueError(msg)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=target_schema,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """Run migrations with schema support."""
    # Set search_path so unqualified table names resolve to target schema
    connection.execute(text(f"SET search_path TO {target_schema}, public"))

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=target_schema,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
