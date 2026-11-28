"""Invalid worker lease settings fail before touching the database."""

import pytest

from app.services.whatsapp.inbox_leases import claim_next, defer_claim, quarantine_expired


@pytest.mark.asyncio
@pytest.mark.parametrize("seconds", [0, 9, 901])
async def test_claim_rejects_unbounded_lease(seconds):
    with pytest.raises(ValueError):
        await claim_next(lease_seconds=seconds)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 1001])
async def test_quarantine_rejects_invalid_batch(limit):
    with pytest.raises(ValueError):
        await quarantine_expired(limit=limit)


@pytest.mark.asyncio
@pytest.mark.parametrize("seconds", [0, 901])
async def test_defer_rejects_invalid_delay(seconds):
    import uuid

    with pytest.raises(ValueError):
        await defer_claim(uuid.uuid4(), uuid.uuid4(), delay_seconds=seconds)
