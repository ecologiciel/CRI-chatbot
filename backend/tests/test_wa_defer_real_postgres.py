"""Deferred inbox claims preserve ordering in a disposable PostgreSQL."""

import os
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.whatsapp.inbox_leases import claim_next, defer_claim, finish_claim

URL = os.getenv("TEST_WA_ORDER_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable migrated PostgreSQL")


@pytest.mark.asyncio
async def test_deferred_first_event_blocks_its_stream_but_not_others_or_stop():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant, first, second, other, stop = (uuid.uuid4() for _ in range(5))
    slug = "defer_" + tenant.hex
    async with engine.begin() as conn:
        assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
        await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Test',:slug,'Test','active')"), {"id": tenant, "slug": slug})
        await conn.execute(text("""
            INSERT INTO public.whatsapp_inbox_events
                (id,tenant_id,provider_message_id,phone_number_id,ciphertext,key_version,sender_fingerprint,is_opt_out)
            VALUES (:a,:t,'defer-a','123','fixture',1,repeat('a',64),false),
                   (:b,:t,'defer-b','123','fixture',1,repeat('a',64),false),
                   (:c,:t,'defer-c','123','fixture',1,repeat('b',64),false),
                   (:d,:t,'defer-stop','123','fixture',1,repeat('a',64),true)
        """), {"a": first, "b": second, "c": other, "d": stop, "t": tenant})
    try:
        with patch("app.services.whatsapp.inbox_leases.get_session_factory", return_value=factory):
            claim = await claim_next()
            assert claim and claim.id == first
            assert not await defer_claim(first, uuid.uuid4())
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE public.whatsapp_inbox_events SET lease_until=now()-interval '1 second' WHERE id=:id"), {"id": first})
            assert not await defer_claim(first, claim.lease_token)
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE public.whatsapp_inbox_events SET lease_until=now()+interval '2 minutes' WHERE id=:id"), {"id": first})
            assert await defer_claim(first, claim.lease_token)
            assert not await defer_claim(first, claim.lease_token)
            # STOP must bypass the deferred event, another sender can proceed.
            claims = [await claim_next(), await claim_next()]
            assert {c.id for c in claims if c} == {other, stop}
            for item in claims:
                assert item and await finish_claim(item.id, item.lease_token, uncertain=False)
            assert await claim_next() is None
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE public.whatsapp_inbox_events SET not_before=now()-interval '1 second' WHERE id=:id"), {"id": first})
            claim = await claim_next()
            assert claim and claim.id == first
            assert await finish_claim(first, claim.lease_token, uncertain=False)
            claim = await claim_next()
            assert claim and claim.id == second
            assert await finish_claim(second, claim.lease_token, uncertain=False)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM public.tenants WHERE id=:id"), {"id": tenant})
        await engine.dispose()
