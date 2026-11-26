"""Test opt-out/campaign serialization only on a disposable PostgreSQL database."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.database import Base, close_engine, get_engine
from app.core.tenant import TenantContext
from app.models.contact import Contact
from app.models.enums import OptInStatus
from app.workers.campaign import _send_single_recipient


async def main():
    settings = get_settings()
    if (
        settings.environment != "development"
        or settings.postgres_host != "wa-inbox-pg"
        or settings.postgres_db != "wa_inbox_test"
    ):
        raise RuntimeError("Refusing to use a non-disposable database")
    async with get_engine().begin() as conn:
        await conn.execute(text("CREATE SCHEMA tenant_synthetica"))
        await conn.execute(text("SET LOCAL search_path TO tenant_synthetica, public"))
        await conn.run_sync(
            lambda sync: Base.metadata.create_all(sync, tables=[Contact.__table__])
        )
    tenant = TenantContext(uuid.uuid4(), "synthetica", "Synthetic", "active", None)
    contact_id = uuid.uuid4()
    async with tenant.db_session() as session:
        session.add(
            Contact(
                id=contact_id, phone="212600000001", opt_in_status=OptInStatus.opted_in
            )
        )

    entered, release = asyncio.Event(), asyncio.Event()

    async def send(**_kwargs):
        entered.set()
        await release.wait()
        return "synthetic-wamid"

    sender = AsyncMock(side_effect=send)
    service = SimpleNamespace(
        _sender=SimpleNamespace(send_template=sender),
        resolve_variables=MagicMock(return_value=[]),
    )
    campaign = SimpleNamespace(
        id=uuid.uuid4(),
        variable_mapping={},
        template_name="demo",
        template_language="fr",
    )
    recipient = SimpleNamespace(id=uuid.uuid4(), contact_id=contact_id)
    session_mgr = SimpleNamespace(increment_quota=AsyncMock())

    async def opt_out():
        async with tenant.db_session() as session:
            contact = (
                await session.execute(select(Contact).where(Contact.id == contact_id))
            ).scalar_one()
            contact.opt_in_status = OptInStatus.opted_out
            await session.flush()

    with patch("app.workers.campaign._update_recipient_status", new=AsyncMock()):
        first = asyncio.create_task(
            _send_single_recipient(tenant, campaign, recipient, service, session_mgr)
        )
        await asyncio.wait_for(entered.wait(), timeout=10)
        change = asyncio.create_task(opt_out())
        await asyncio.sleep(0.3)
        assert not change.done(), "Consent update bypassed the send lock"
        release.set()
        assert await asyncio.wait_for(first, timeout=10)
        await asyncio.wait_for(change, timeout=10)
        assert not await _send_single_recipient(
            tenant, campaign, recipient, service, session_mgr
        )
        assert sender.await_count == 1
    await close_engine()
    print("ISOLATED_CAMPAIGN_CONSENT_OK", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
