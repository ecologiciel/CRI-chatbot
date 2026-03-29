"""Shared fixtures for unit tests.

All external I/O (Redis, PostgreSQL, Qdrant, Gemini API, httpx) is mocked.
TenantContext is constructed directly (frozen dataclass, not mockable).
"""

from __future__ import annotations

import importlib
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.tenant import TenantContext

# ── Constants ──

TEST_TENANT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
TEST_ADMIN_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
TEST_PHONE = "+212600000001"


# ── TenantContext fixtures ──


@pytest.fixture
def tenant_context():
    """Standard active tenant with WhatsApp config."""
    return TenantContext(
        id=TEST_TENANT_ID,
        slug="rabat",
        name="CRI Rabat-Sale-Kenitra",
        status="active",
        whatsapp_config={
            "phone_number_id": "111222333",
            "access_token": "test_access_token",
            "verify_token": "test_verify_token",
            "annual_message_limit": 100_000,
        },
    )


@pytest.fixture
def tenant_no_whatsapp():
    """Tenant without WhatsApp configuration."""
    return TenantContext(
        id=TEST_TENANT_ID,
        slug="rabat",
        name="CRI Rabat-Sale-Kenitra",
        status="active",
        whatsapp_config=None,
    )


def make_tenant(**overrides):
    """Factory function for TenantContext with arbitrary overrides."""
    defaults = {
        "id": TEST_TENANT_ID,
        "slug": "rabat",
        "name": "CRI Rabat",
        "status": "active",
        "whatsapp_config": {
            "phone_number_id": "111222333",
            "access_token": "test_access_token",
            "verify_token": "test_verify_token",
            "annual_message_limit": 100_000,
        },
    }
    defaults.update(overrides)
    return TenantContext(**defaults)


# ── Redis mock fixtures ──


@pytest.fixture
def mock_redis():
    """Mock Redis with basic get/set/delete/incr/ttl operations."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    redis.incr = AsyncMock(return_value=1)
    redis.ttl = AsyncMock(return_value=-2)
    redis.setex = AsyncMock()
    redis.exists = AsyncMock(return_value=0)
    redis.expire = AsyncMock()
    redis.hgetall = AsyncMock(return_value={})
    # Pipeline support
    pipe = AsyncMock()
    pipe.incr = MagicMock(return_value=pipe)
    pipe.hincrby = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.get = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[1, True, 1, True])
    redis.pipeline = MagicMock(return_value=pipe)
    redis._pipe = pipe  # Expose for assertions
    return redis


# ── DB session mock ──


@pytest.fixture
def mock_db_session():
    """Async DB session mock with context manager support."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalar_one.return_value = None
    mock_result.first.return_value = None
    mock_result.fetchall.return_value = []
    mock_result.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    return session, mock_result


# ── Admin ORM factory ──


def make_admin_orm(**overrides):
    """Create a mock Admin ORM object for auth tests."""
    from app.models.enums import AdminRole
    from app.services.auth.service import AuthService

    defaults = {
        "id": TEST_ADMIN_ID,
        "email": "admin@cri-rabat.ma",
        "password_hash": AuthService.hash_password("SecureP@ss123!"),
        "full_name": "Admin CRI",
        "role": AdminRole.admin_tenant,
        "tenant_id": TEST_TENANT_ID,
        "is_active": True,
        "last_login": None,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def make_session_factory(admin=None):
    """Create a mock session factory returning the given admin on query."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = admin
    mock_result.scalar_one.return_value = admin

    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    mock_factory = MagicMock(return_value=mock_session)
    return mock_factory, mock_session


# ── ConversationState factory ──


def make_conversation_state(**overrides):
    """Create a minimal ConversationState dict for orchestrator tests."""
    state = {
        "tenant_slug": "rabat",
        "phone": TEST_PHONE,
        "language": "fr",
        "intent": "",
        "query": "",
        "messages": [],
        "retrieved_chunks": [],
        "response": "",
        "chunk_ids": [],
        "confidence": 0.0,
        "is_safe": True,
        "guard_message": None,
        "incentive_state": {},
        "error": None,
    }
    state.update(overrides)
    return state


# ── Gemini mock helpers ──


def make_mock_gemini_response(text="OK", input_tokens=10, output_tokens=5):
    """Create a mock Gemini API SDK response object."""
    usage = MagicMock()
    usage.prompt_token_count = input_tokens
    usage.candidates_token_count = output_tokens

    finish_reason = MagicMock()
    finish_reason.name = "STOP"

    candidate = MagicMock()
    candidate.finish_reason = finish_reason

    response = MagicMock()
    response.text = text
    response.usage_metadata = usage
    response.candidates = [candidate]
    return response


# ── DB session context manager for tenant ──


def make_tenant_db_session(session):
    """Create an async context manager simulating tenant.db_session()."""

    @asynccontextmanager
    async def _fake_db_session():
        yield session

    return _fake_db_session


# ── Singleton reset autouse fixture ──

_SINGLETON_VARS = {
    "app.services.ai.gemini": "_gemini_service",
    "app.services.ai.embeddings": "_embedding_service",
    "app.services.ai.language": "_language_service",
    "app.services.guardrails.input_guard": "_input_guard_service",
    "app.services.guardrails.output_guard": "_output_guard_service",
    "app.services.guardrails.pii_masker": "_pii_masker",
    "app.services.rag.ingestion": "_ingestion_service",
    "app.services.rag.retrieval": "_retrieval_service",
    "app.services.rag.generation": "_generation_service",
    "app.services.feedback.service": "_feedback_service",
    "app.services.orchestrator.intent": "_intent_detector",
    "app.services.orchestrator.faq_agent": "_faq_agent",
    "app.services.orchestrator.feedback_collector": "_feedback_collector",
    "app.services.auth.session_manager": "_session_manager",
    "app.services.campaign.service": "_campaign_service",
    "app.services.contact.segmentation": "_segmentation_service",
}


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset all service singletons after each test to prevent leaks."""
    yield
    for module_path, var_name in _SINGLETON_VARS.items():
        try:
            mod = importlib.import_module(module_path)
            if hasattr(mod, var_name):
                setattr(mod, var_name, None)
        except ImportError:
            pass
