"""Presence and backlog tests against explicitly disposable PostgreSQL and Redis."""

import os
import uuid
from unittest.mock import MagicMock, patch

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.whatsapp_operations import availability
from app.core.tenant import TenantContext
from app.services.whatsapp import worker_presence

DB_URL = os.getenv("TEST_WA_MONITOR_DB_URL")
REDIS_URL = os.getenv("TEST_WA_MONITOR_REDIS_URL")
pytestmark = pytest.mark.skipif(not DB_URL or not REDIS_URL, reason="requires disposable services")


@pytest.mark.asyncio
async def test_presence_and_backlog_are_tenant_scoped_and_fail_honestly():
    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    a, b = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        assert (await conn.execute(text("SELECT current_database()"))).scalar_one().startswith("ragtest_")
        await conn.execute(text("CREATE TABLE public.whatsapp_inbox_events (tenant_id uuid, state text, created_at timestamptz)"))
        await conn.execute(text("CREATE TABLE public.whatsapp_status_events (tenant_id uuid, state text)"))
        await conn.execute(text("INSERT INTO public.whatsapp_inbox_events VALUES (:a, 'pending', now()-interval '2 minutes'), (:a, 'uncertain', now()), (:b, 'pending', now())"), {"a": a, "b": b})
        await conn.execute(text("INSERT INTO public.whatsapp_status_events VALUES (:a, 'follow_up'), (:b, 'uncertain')"), {"a": a, "b": b})
    tenant = TenantContext(a, "alpha", "Alpha", "active", None)
    try:
        with (
            patch("app.services.whatsapp.worker_presence.get_session_factory", return_value=factory),
            patch("app.services.whatsapp.worker_presence.get_redis", return_value=redis),
            patch("app.api.v1.whatsapp_operations.get_session_factory", return_value=factory),
            patch("app.api.v1.whatsapp_operations.get_redis", return_value=redis),
            patch("app.api.v1.whatsapp_operations.get_settings", return_value=MagicMock(whatsapp_durable_inbox_enabled=True)),
        ):
            await worker_presence.publish_presence()
            assert 0 < await redis.ttl(worker_presence.HEARTBEAT_KEY) <= 45
            result = await availability(tenant=tenant, _admin=MagicMock())
            assert result["worker_seen"] is True
            assert result["pending_messages"] == 1
            assert 120 <= result["oldest_pending_seconds"] < 180
            assert result["review_messages"] == result["review_statuses"] == 1
            await redis.delete(worker_presence.HEARTBEAT_KEY)
            assert (await availability(tenant=tenant, _admin=MagicMock()))["worker_seen"] is False
            with patch("app.api.v1.whatsapp_operations.get_redis", side_effect=RuntimeError("offline")):
                assert (await availability(tenant=tenant, _admin=MagicMock()))["worker_seen"] is None
    finally:
        await redis.aclose()
        await engine.dispose()
