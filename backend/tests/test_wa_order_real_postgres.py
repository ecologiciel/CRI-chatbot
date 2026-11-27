"""Concurrent claiming and blocking rules against a disposable migrated copy."""

import asyncio
import os
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.whatsapp.inbox_leases import claim_next, finish_claim

URL = os.getenv("TEST_WA_ORDER_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable migrated PostgreSQL")


@pytest.mark.asyncio
async def test_concurrent_claims_preserve_order_and_isolate_conversations():
    engine = create_async_engine(URL, pool_size=20, max_overflow=10)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    a1, a2, b1, c1 = (uuid.uuid4() for _ in range(4))
    async with engine.begin() as conn:
        assert (await conn.execute(text("SELECT current_database()"))).scalar_one().startswith("ragtest_")
        await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:a,'A','fixture_a','Test','active'),(:b,'B','fixture_b','Test','active')"), {"a": t1, "b": t2})
        await conn.execute(text("""
            INSERT INTO public.whatsapp_inbox_events (id,tenant_id,provider_message_id,phone_number_id,ciphertext,key_version,sender_fingerprint)
            VALUES (:a1,:t1,'a1','123','fixture',1,repeat('a',64)),
                   (:a2,:t1,'a2','123','fixture',1,repeat('a',64)),
                   (:b1,:t1,'b1','123','fixture',1,repeat('b',64)),
                   (:c1,:t2,'c1','456','fixture',1,repeat('a',64))
        """), {"a1": a1, "a2": a2, "b1": b1, "c1": c1, "t1": t1, "t2": t2})
    with patch("app.services.whatsapp.inbox_leases.get_session_factory", return_value=factory):
        claims = [c for c in await asyncio.gather(*(claim_next() for _ in range(20))) if c]
        assert {c.id for c in claims} == {a1, b1, c1}
        assert len(claims) == 3
        for claim in claims:
            assert await finish_claim(claim.id, claim.lease_token, uncertain=claim.id == a1)
        assert await claim_next() is None  # uncertain first message blocks only its conversation
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.whatsapp_inbox_events SET state='resolved' WHERE id=:id"), {"id": a1})
        second = await claim_next()
        assert second and second.id == a2
        assert await finish_claim(second.id, second.lease_token, uncertain=False)

        legacy, later, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO public.whatsapp_inbox_events (id,tenant_id,provider_message_id,phone_number_id,ciphertext,key_version,sender_fingerprint)
                VALUES (:legacy,:t1,'legacy','123','fixture',1,NULL),
                       (:later,:t1,'later','123','fixture',1,repeat('c',64)),
                       (:other,:t2,'other','456','fixture',1,repeat('c',64))
            """), {"legacy": legacy, "later": later, "other": other, "t1": t1, "t2": t2})
        claim = await claim_next()
        assert claim and claim.id == other
        assert await finish_claim(claim.id, claim.lease_token, uncertain=False)
        assert await claim_next() is None
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.whatsapp_inbox_events SET state='resolved' WHERE id=:id"), {"id": legacy})
        claim = await claim_next()
        assert claim and claim.id == later
        assert await finish_claim(claim.id, claim.lease_token, uncertain=False)
    await engine.dispose()
