"""Tests for Escalation model, enums, and Pydantic schemas."""

from __future__ import annotations

import uuid

import pytest


# ── 1. Model import ─────────────────────────────────────────────


def test_escalation_model_import():
    """Escalation model is importable and has the correct tablename."""
    from app.models.escalation import Escalation

    assert Escalation.__tablename__ == "escalations"


# ── 2. Enum imports and counts ──────────────────────────────────


def test_escalation_enums_import():
    """All escalation-related enums are importable with correct member counts."""
    from app.models.enums import (
        EscalationPriority,
        EscalationStatus,
        EscalationTrigger,
    )

    assert len(EscalationTrigger) == 6  # 6 trigger scenarios
    assert len(EscalationPriority) == 3  # high, medium, low
    assert len(EscalationStatus) == 5  # pending, assigned, in_progress, resolved, closed


def test_escalation_trigger_values():
    """EscalationTrigger covers all 6 CPS-defined scenarios."""
    from app.models.enums import EscalationTrigger

    expected = {
        "explicit_request",
        "rag_failure",
        "sensitive_topic",
        "negative_feedback",
        "otp_timeout",
        "manual",
    }
    assert {t.value for t in EscalationTrigger} == expected


def test_escalation_status_lifecycle():
    """EscalationStatus covers the full lifecycle."""
    from app.models.enums import EscalationStatus

    expected = {"pending", "assigned", "in_progress", "resolved", "closed"}
    assert {s.value for s in EscalationStatus} == expected


# ── 3. Schema imports ───────────────────────────────────────────


def test_escalation_schemas_import():
    """All escalation schemas are importable."""
    from app.schemas.escalation import (
        EscalationAssign,
        EscalationCreate,
        EscalationList,
        EscalationRead,
        EscalationResolve,
        EscalationRespond,
        EscalationStats,
    )

    assert EscalationCreate is not None
    assert EscalationRead is not None
    assert EscalationList is not None
    assert EscalationAssign is not None
    assert EscalationResolve is not None
    assert EscalationRespond is not None
    assert EscalationStats is not None


# ── 4. EscalationCreate validation ─────────────────────────────


def test_escalation_create_valid():
    """EscalationCreate accepts valid data."""
    from app.models.enums import EscalationPriority, EscalationTrigger
    from app.schemas.escalation import EscalationCreate

    esc = EscalationCreate(
        conversation_id=uuid.uuid4(),
        trigger_type=EscalationTrigger.explicit_request,
        priority=EscalationPriority.high,
        context_summary="L'utilisateur demande a parler a un humain.",
    )
    assert esc.trigger_type == EscalationTrigger.explicit_request
    assert esc.priority == EscalationPriority.high
    assert esc.user_message is None


def test_escalation_create_all_triggers():
    """EscalationCreate accepts all 6 trigger types."""
    from app.models.enums import EscalationPriority, EscalationTrigger
    from app.schemas.escalation import EscalationCreate

    for trigger in EscalationTrigger:
        esc = EscalationCreate(
            conversation_id=uuid.uuid4(),
            trigger_type=trigger,
            priority=EscalationPriority.medium,
        )
        assert esc.trigger_type == trigger


# ── 5. EscalationResolve validation ────────────────────────────


def test_escalation_resolve_rejects_empty_notes():
    """EscalationResolve must reject empty resolution_notes."""
    from app.schemas.escalation import EscalationResolve

    with pytest.raises(ValueError):
        EscalationResolve(resolution_notes="")


def test_escalation_resolve_valid():
    """EscalationResolve accepts non-empty notes."""
    from app.schemas.escalation import EscalationResolve

    res = EscalationResolve(resolution_notes="Probleme resolu par telephone.")
    assert res.resolution_notes == "Probleme resolu par telephone."


# ── 6. EscalationRespond validation ────────────────────────────


def test_escalation_respond_rejects_empty_message():
    """EscalationRespond must reject empty message."""
    from app.schemas.escalation import EscalationRespond

    with pytest.raises(ValueError):
        EscalationRespond(message="")


def test_escalation_respond_valid():
    """EscalationRespond accepts non-empty message."""
    from app.schemas.escalation import EscalationRespond

    resp = EscalationRespond(message="Bonjour, je prends en charge votre demande.")
    assert len(resp.message) > 0


# ── 7. EscalationRead computed field ───────────────────────────


def test_escalation_read_wait_time_for_pending():
    """EscalationRead computes wait_time_seconds for pending escalations."""
    from datetime import datetime, timedelta, timezone

    from app.models.enums import EscalationPriority, EscalationStatus, EscalationTrigger
    from app.schemas.escalation import EscalationRead

    created = datetime.now(timezone.utc) - timedelta(minutes=5)
    esc = EscalationRead(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        trigger_type=EscalationTrigger.rag_failure,
        priority=EscalationPriority.high,
        assigned_to=None,
        context_summary=None,
        user_message="Je ne comprends pas la reponse",
        status=EscalationStatus.pending,
        resolution_notes=None,
        created_at=created,
        assigned_at=None,
        resolved_at=None,
    )
    assert esc.wait_time_seconds is not None
    assert esc.wait_time_seconds >= 299  # ~5 minutes


def test_escalation_read_no_wait_time_for_resolved():
    """EscalationRead does not compute wait_time for resolved escalations."""
    from datetime import datetime, timedelta, timezone

    from app.models.enums import EscalationPriority, EscalationStatus, EscalationTrigger
    from app.schemas.escalation import EscalationRead

    created = datetime.now(timezone.utc) - timedelta(hours=1)
    esc = EscalationRead(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        trigger_type=EscalationTrigger.explicit_request,
        priority=EscalationPriority.medium,
        assigned_to=uuid.uuid4(),
        context_summary="Resolved case",
        user_message=None,
        status=EscalationStatus.resolved,
        resolution_notes="Handled via phone call",
        created_at=created,
        assigned_at=created + timedelta(minutes=2),
        resolved_at=created + timedelta(minutes=15),
    )
    assert esc.wait_time_seconds is None


# ── 8. EscalationStats ─────────────────────────────────────────


def test_escalation_stats_valid():
    """EscalationStats accepts valid dashboard data."""
    from app.schemas.escalation import EscalationStats

    stats = EscalationStats(
        total_pending=5,
        total_in_progress=2,
        avg_wait_seconds=180.5,
        avg_resolution_seconds=600.0,
        by_trigger={"explicit_request": 3, "rag_failure": 2, "manual": 2},
        by_priority={"high": 4, "medium": 2, "low": 1},
    )
    assert stats.total_pending == 5
    assert stats.by_trigger["rag_failure"] == 2
