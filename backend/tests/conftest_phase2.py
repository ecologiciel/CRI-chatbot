"""Fixtures spécifiques aux tests E2E Phase 2.

Complète le conftest.py Phase 1 avec les fixtures nécessaires
pour les modules whitelist, escalade, apprentissage, campagne, et sécurité.

Pattern:
- Patch TenantResolver.from_tenant_id_header → MagicMock tenant (TenantContext is frozen)
- Override get_current_admin FastAPI dependency for RBAC
- Pass X-Tenant-ID header on every request
- Patch service singletons for service-layer endpoints
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

# Env vars must be set BEFORE importing app (triggers Settings())
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("REDIS_PASSWORD", "test-password")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key")

from app.core.rbac import get_current_admin
from app.main import app
from app.models.enums import AdminRole
from app.schemas.auth import AdminTokenPayload

# ── Constants ──────────────────────────────────────────────

TEST_TENANT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TEST_ADMIN_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TEST_TENANT_SLUG = "test_tenant"


# ── Admin payload factory ──────────────────────────────────


def make_admin_payload(
    role: str = AdminRole.admin_tenant.value,
    tenant_id: uuid.UUID | None = TEST_TENANT_ID,
    admin_id: uuid.UUID | None = None,
    **overrides,
) -> AdminTokenPayload:
    """Create an AdminTokenPayload with sensible defaults."""
    defaults = {
        "sub": str(admin_id or TEST_ADMIN_ID),
        "role": role,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "exp": 9999999999,
        "iat": 1700000000,
        "jti": str(uuid.uuid4()),
        "type": "access",
    }
    defaults.update(overrides)
    return AdminTokenPayload(**defaults)


# ── Dependency override helpers ────────────────────────────


def override_admin(payload: AdminTokenPayload):
    """Set get_current_admin dependency override. Returns cleanup."""
    app.dependency_overrides[get_current_admin] = lambda: payload
    return lambda: app.dependency_overrides.pop(get_current_admin, None)


def make_mock_tenant(db_session_mock=None) -> MagicMock:
    """Create a MagicMock that mimics TenantContext.

    TenantContext is a frozen dataclass so we can't patch.object on it.
    Instead, the middleware will store this mock in request.state.tenant,
    and get_current_tenant() will return it to route handlers.
    """
    tenant = MagicMock()
    tenant.id = TEST_TENANT_ID
    tenant.slug = TEST_TENANT_SLUG
    tenant.name = "CRI Test"
    tenant.status = "active"
    tenant.whatsapp_config = {
        "phone_number_id": "111222333",
        "access_token": "test_whatsapp_token",
        "verify_token": "test_verify_token",
    }
    tenant.db_schema = f"tenant_{TEST_TENANT_SLUG}"
    tenant.qdrant_collection = f"kb_{TEST_TENANT_SLUG}"
    tenant.redis_prefix = TEST_TENANT_SLUG
    tenant.minio_bucket = f"cri-{TEST_TENANT_SLUG}"

    if db_session_mock is not None:
        tenant.db_session = MagicMock(return_value=_make_async_cm(db_session_mock))
    else:
        # Default: empty async context manager
        default_session = AsyncMock()
        default_session.__aenter__ = AsyncMock(return_value=default_session)
        default_session.__aexit__ = AsyncMock(return_value=False)
        tenant.db_session = MagicMock(return_value=_make_async_cm(default_session))

    return tenant


# ── Async context manager helper ───────────────────────────


class _AsyncCM:
    """Minimal async context manager wrapping a mock session."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return False


def _make_async_cm(session):
    """Create an async context manager from a mock session."""
    return _AsyncCM(session)


# ── Mock DB session factories ──────────────────────────────


def mock_session_for_list(items=None, total=0):
    """Create mock session for paginated list endpoints.

    First execute() returns count, second returns items.
    """
    session = AsyncMock()

    call_count = 0

    async def _execute_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # Count query
            result.scalar_one.return_value = total
        else:
            # Data query
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = items or []
            result.scalars.return_value = mock_scalars
        return result

    session.execute = AsyncMock(side_effect=_execute_side_effect)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


def mock_session_for_crud(entity=None, *, not_found=False):
    """Create mock session for single-entity CRUD operations."""
    session = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None if not_found else entity
    mock_result.scalar_one.return_value = entity
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


# ── Mock ORM factories ─────────────────────────────────────


def make_whitelist_orm(**overrides) -> MagicMock:
    """Create a mock InternalWhitelist ORM object."""
    defaults = {
        "id": uuid.uuid4(),
        "phone": "+212611111111",
        "label": "Agent Test CRI",
        "note": "Fixture de test",
        "is_active": True,
        "added_by": TEST_ADMIN_ID,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def make_escalation_orm(**overrides) -> MagicMock:
    """Create a mock Escalation ORM object."""
    from app.models.enums import EscalationPriority, EscalationStatus, EscalationTrigger

    defaults = {
        "id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "trigger_type": EscalationTrigger.explicit_request,
        "priority": EscalationPriority.high,
        "assigned_to": None,
        "context_summary": "User asked to speak with a human agent.",
        "user_message": "Je veux parler à un agent",
        "status": EscalationStatus.pending,
        "resolution_notes": None,
        "created_at": datetime(2026, 3, 1, tzinfo=UTC),
        "assigned_at": None,
        "resolved_at": None,
        "agent": None,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def make_question_orm(**overrides) -> MagicMock:
    """Create a mock UnansweredQuestion ORM object."""
    from app.models.enums import UnansweredStatus

    defaults = {
        "id": uuid.uuid4(),
        "question": "Comment obtenir un agrément pour un projet touristique à Kénitra ?",
        "language": "fr",
        "frequency": 3,
        "proposed_answer": None,
        "status": UnansweredStatus.pending,
        "reviewed_by": None,
        "review_note": None,
        "source_conversation_id": None,
        "created_at": datetime(2026, 2, 15, tzinfo=UTC),
        "updated_at": datetime(2026, 2, 15, tzinfo=UTC),
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def make_campaign_orm(**overrides) -> MagicMock:
    """Create a mock Campaign ORM object."""
    from app.models.enums import CampaignStatus

    defaults = {
        "id": uuid.uuid4(),
        "name": "Campagne Test E2E",
        "description": None,
        "template_id": "welcome_fr_001",
        "template_name": "Bienvenue Investisseur",
        "template_language": "fr",
        "audience_filter": {"tags": ["investisseur"]},
        "audience_count": 0,
        "variable_mapping": {"1": "contact.name"},
        "status": CampaignStatus.draft,
        "scheduled_at": None,
        "started_at": None,
        "completed_at": None,
        "stats": {"sent": 0, "delivered": 0, "read": 0, "failed": 0, "total": 0},
        "created_by": TEST_ADMIN_ID,
        "created_at": datetime(2026, 3, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 3, 1, tzinfo=UTC),
        "recipients": [],
        "creator": MagicMock(id=TEST_ADMIN_ID, email="admin@cri-test.ma"),
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def make_contact_orm(**overrides) -> MagicMock:
    """Create a mock Contact ORM object."""
    from app.models.enums import ContactSource, Language, OptInStatus

    defaults = {
        "id": uuid.uuid4(),
        "phone": "+212610000001",
        "name": "Contact Test",
        "language": Language.fr,
        "cin": None,
        "opt_in_status": OptInStatus.opted_in,
        "tags": ["investisseur", "actif"],
        "source": ContactSource.whatsapp,
        "metadata": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock
