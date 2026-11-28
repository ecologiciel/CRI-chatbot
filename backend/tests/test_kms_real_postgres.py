"""Exercise tenant-key handling with a disposable PostgreSQL database."""
import os
import secrets
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import CRIDecryptionError
from app.services.crypto.kms import KMSService

URL = os.getenv("TEST_KMS_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable PostgreSQL")


@pytest.mark.asyncio
async def test_database_key_roundtrip_and_redis_cannot_resurrect_deleted_key():
    engine = create_async_engine(URL)
    tenant_id = uuid.uuid4()
    slug = "kmsfixture" + uuid.uuid4().hex
    redis = AsyncMock()
    redis.get.return_value = secrets.token_hex(32)
    try:
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
            await conn.execute(
                text("INSERT INTO public.tenants (id,name,slug,region,status) "
                     "VALUES (:id,'Fixture',:slug,'Test','active')"),
                {"id": tenant_id, "slug": slug},
            )
        kms = KMSService(async_sessionmaker(engine, expire_on_commit=False), redis, secrets.token_hex(32))
        await kms.generate_tenant_key(tenant_id)
        encrypted = await kms.encrypt("synthetic-sensitive-data", slug)
        assert await kms.decrypt(encrypted, slug) == "synthetic-sensitive-data"
        redis.get.assert_not_awaited()
        redis.set.assert_not_awaited()
        await kms.delete_tenant_key(tenant_id, slug)
        with pytest.raises(CRIDecryptionError, match="No active encryption key"):
            await kms.decrypt(encrypted, slug)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM public.tenants WHERE id=:id"), {"id": tenant_id})
        await engine.dispose()
