"""Async SQLAlchemy engine and session factory.

Usage in services:
    async with get_async_session() as session:
        result = await session.execute(select(Model))

Tenant-scoped sessions set a transaction-local search path on every begin.
"""

import re
from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


class TenantDatabaseIsolationError(RuntimeError):
    """A connection cannot safely be used for tenant-scoped queries."""


def _tenant_search_path(schema: str) -> str:
    if not re.fullmatch(r"tenant_[a-z0-9][a-z0-9_]{0,49}", schema):
        raise TenantDatabaseIsolationError("Invalid tenant schema")
    # Listing pg_temp explicitly puts it after the tenant schema instead of
    # PostgreSQL's implicit first position. A connection that already has a
    # temporary schema is rejected separately, before any tenant query.
    return f"pg_catalog, {schema}, pg_temp"


async def set_tenant_search_path(session: AsyncSession, schema: str) -> None:
    """Switch an existing transaction to a tenant without reusing temp objects."""
    path = _tenant_search_path(schema)
    if await session.scalar(text("SELECT pg_catalog.pg_my_temp_schema()")):
        await session.invalidate()
        raise TenantDatabaseIsolationError("Temporary schema on tenant connection")
    await session.execute(text("SELECT pg_catalog.set_config('search_path', :path, true)"), {"path": path})


@event.listens_for(Session, "after_begin")
def _set_transaction_tenant(session: Session, transaction, connection) -> None:
    """Apply the tenant for every transaction, including after commit/rollback."""
    schema = session.info.get("tenant_schema")
    if schema:
        path = _tenant_search_path(schema)
        if connection.scalar(text("SELECT pg_catalog.pg_my_temp_schema()")):
            # Never return this physical connection to the pool: its temporary
            # objects may belong to a different institution.
            connection.invalidate()
            raise TenantDatabaseIsolationError("Temporary schema on tenant connection")
        connection.execute(
            text("SELECT pg_catalog.set_config('search_path', :path, true)"),
            # Shared models explicitly name public. Including public here
            # silently falls back to a shared table if a tenant table is
            # absent, potentially crossing data boundaries.
            {"path": path},
        )


def get_engine() -> AsyncEngine:
    """Get or create the async SQLAlchemy engine."""
    global _engine  # noqa: PLW0603
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
            connect_args={"server_settings": {"search_path": "public"}},
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory."""
    global _session_factory  # noqa: PLW0603
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_async_session() -> AsyncGenerator[AsyncSession]:
    """Yield an async session. Use as FastAPI dependency."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_engine() -> None:
    """Dispose the engine. Called on app shutdown."""
    global _engine, _session_factory  # noqa: PLW0603
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
