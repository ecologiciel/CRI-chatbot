import pytest

from app.services.whatsapp.status_batch import run_status_batch
from app.services.whatsapp.status_policy import StatusDecision, decide_status


@pytest.mark.parametrize(
    ("current", "incoming", "expected"),
    [
        (None, "sent", StatusDecision("sent", False)),
        ("accepted", "delivered", StatusDecision("delivered", False)),
        ("delivered", "sent", StatusDecision("delivered", False)),
        ("read", "delivered", StatusDecision("read", False)),
        ("sent", "failed", StatusDecision("failed", False)),
        ("read", "failed", StatusDecision("read", True)),
        ("failed", "read", StatusDecision("failed", True)),
        ("failed", "failed", StatusDecision("failed", False)),
        ("accepted", "unexpected", StatusDecision("accepted", True)),
        ("unexpected", "delivered", StatusDecision("unexpected", True)),
        ({"malformed": True}, "delivered", StatusDecision(None, True)),
    ],
)
def test_status_order_and_conflicts(current, incoming, expected):
    assert decide_status(current, incoming) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 251])
async def test_status_batch_rejects_unbounded_requests(limit):
    with pytest.raises(ValueError):
        await run_status_batch(cipher=None, limit=limit)
