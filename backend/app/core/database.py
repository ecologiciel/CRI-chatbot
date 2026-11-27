"""Async SQLAlchemy engine and session factory.

Usage in services:
    async with get_async_session() as session:
        result = await session.execute(select(Model))

Tenant-scoped sessions set a transaction-local search path on every begin.
"""

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


@event.listens_for(Session, "after_begin")
def _set_transaction_tenant(session: Session, transaction, connection) -> None:
    """Apply the tenant for every transaction, including after commit/rollback."""
    schema = session.info.get("tenant_schema")
    if schema:
        connection.execute(
            text("SELECT set_config('search_path', :path, true)"),
            # Shared models explicitly name public. Including public here
            # silently falls back to a shared table if a tenant table is
            # absent, potentially crossing data boundaries.
            {"path": schema},
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
