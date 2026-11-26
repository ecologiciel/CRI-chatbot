import pytest

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
    ],
)
def test_status_order_and_conflicts(current, incoming, expected):
    assert decide_status(current, incoming) == expected
