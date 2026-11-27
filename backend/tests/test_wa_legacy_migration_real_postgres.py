"""Verify legacy inbox quarantine against an isolated migrated database."""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

URL = os.getenv("TEST_WA_LEGACY_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires seeded disposable migration database")


@pytest.mark.asyncio
async def test_legacy_pending_is_reviewable_without_resending():
    engine = create_async_engine(URL)
    async with engine.connect() as conn:
        assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
        rows = (await conn.execute(text(
            "SELECT provider_message_id, state, sender_fingerprint, attempts "
            "FROM public.whatsapp_inbox_events ORDER BY provider_message_id"
        ))).all()
        assert rows == [
            ("legacy-completed", "completed", None, 1),
            ("legacy-pending", "uncertain", None, 0),
            ("legacy-processing", "processing", None, 1),
        ]
    await engine.dispose()
