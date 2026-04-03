"""conftest_phase3 — Fixtures for Phase 3 E2E tests.

Provides:
- InMemoryTrackingStateManager (replaces Redis-backed state)
- InMemoryOTPStore (replaces Redis-backed OTP service)
- Mock tenant and dossier factories
- Excel fixture generators (openpyxl)
- Singleton reset (autouse)
"""

from __future__ import annotations

import hashlib
import importlib
import os
import secrets
import uuid
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import openpyxl
import pytest

from app.models.enums import DossierStatut, Language, OptInStatus
from app.services.dossier.service import DossierService
from app.services.orchestrator.tracking_agent import TrackingAgent
from app.services.orchestrator.tracking_state import TrackingStep, TrackingUserState

# ── Constants ────────────────────────────────────────────────────────

TEST_TENANT_ID_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TEST_TENANT_ID_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TEST_TENANT_SLUG_A = "test_rabat"
TEST_TENANT_SLUG_B = "test_tanger"
PHONE_A = "+212611111111"
PHONE_B = "+212622222222"
PHONE_C = "+212633333333"

DOSSIER_A1_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
DOSSIER_A2_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
DOSSIER_B1_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
CONTACT_A_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
CONTACT_B_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
CONTACT_C_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")


# ── Tenant factory ──────────────────────────────────────────────────


def make_tenant(
    slug: str = TEST_TENANT_SLUG_A,
    tenant_id: uuid.UUID = TEST_TENANT_ID_A,
) -> MagicMock:
    """Create a MagicMock that mimics TenantContext (frozen dataclass)."""
    tenant = MagicMock()
    tenant.id = tenant_id
    tenant.slug = slug
    tenant.name = f"CRI {slug.replace('test_', '').capitalize()}"
    tenant.status = "active"
    tenant.whatsapp_config = {
        "phone_number_id": f"phone_{slug}",
        "access_token": f"tok_{slug}",
        "verify_token": f"verify_{slug}",
    }
    tenant.db_schema = f"tenant_{slug}"
    tenant.qdrant_collection = f"kb_{slug}"
    tenant.redis_prefix = slug
    tenant.minio_bucket = f"cri-{slug}"

    # Async context manager for db_session()
    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    tenant.db_session = MagicMock(return_value=mock_cm)
    tenant._mock_db_session = mock_session

    return tenant


# ── In-memory TrackingStateManager ──────────────────────────────────


class InMemoryTrackingStateManager:
    """Drop-in replacement for TrackingStateManager using a Python dict."""

    def __init__(self) -> None:
        self._store: dict[str, TrackingUserState] = {}

    def _key(self, phone: str, tenant: Any) -> str:
        return f"{tenant.slug}:tracking_state:{phone}"

    async def get_state(self, phone: str, tenant: Any) -> TrackingUserState:
        key = self._key(phone, tenant)
        return self._store.get(key, TrackingUserState())

    async def set_state(
        self, phone: str, state: TrackingUserState, tenant: Any,
    ) -> None:
        key = self._key(phone, tenant)
        self._store[key] = state

    async def clear_state(self, phone: str, tenant: Any) -> None:
        key = self._key(phone, tenant)
        self._store.pop(key, None)


# ── In-memory OTP store ─────────────────────────────────────────────

MAX_OTP_ATTEMPTS = 3


class InMemoryOTPStore:
    """Drop-in replacement for DossierOTPService using Python dicts.

    Uses real crypto (secrets.randbelow, SHA-256) to faithfully test
    the OTP generation/verification logic without Redis.
    """

    def __init__(self) -> None:
        self._otp_hashes: dict[str, str] = {}  # key → sha256 hash
        self._attempts: dict[str, int] = {}  # key → attempt count
        self._sessions: dict[str, str] = {}  # key → session token
        self._last_otp: str | None = None  # for test inspection

    def _key(self, tenant: Any, key_type: str, phone: str) -> str:
        return f"{tenant.slug}:{key_type}:{phone}"

    async def is_rate_limited(self, tenant: Any, phone: str) -> bool:
        key = self._key(tenant, "dossier_otp_attempts", phone)
        return self._attempts.get(key, 0) >= MAX_OTP_ATTEMPTS

    async def generate_otp(self, phone: str, tenant: Any) -> str:
        if await self.is_rate_limited(tenant, phone):
            from app.core.exceptions import RateLimitExceededError
            raise RateLimitExceededError("OTP rate limit exceeded")

        otp = str(secrets.randbelow(900000) + 100000)
        otp_hash = hashlib.sha256(otp.encode()).hexdigest()

        otp_key = self._key(tenant, "dossier_otp", phone)
        self._otp_hashes[otp_key] = otp_hash

        attempts_key = self._key(tenant, "dossier_otp_attempts", phone)
        self._attempts[attempts_key] = self._attempts.get(attempts_key, 0) + 1

        self._last_otp = otp
        return otp

    async def verify_otp(self, phone: str, otp_code: str, tenant: Any) -> bool:
        otp_key = self._key(tenant, "dossier_otp", phone)
        stored_hash = self._otp_hashes.get(otp_key)

        if stored_hash is None:
            return False

        computed_hash = hashlib.sha256(otp_code.encode()).hexdigest()
        if computed_hash != stored_hash:
            return False

        # Anti-replay: delete OTP on success
        del self._otp_hashes[otp_key]
        return True

    async def create_dossier_session(self, phone: str, tenant: Any) -> str:
        token = secrets.token_hex(32)
        session_key = self._key(tenant, "dossier_session", phone)
        self._sessions[session_key] = token
        return token

    async def validate_dossier_session(
        self, phone: str, session_token: str, tenant: Any,
    ) -> bool:
        session_key = self._key(tenant, "dossier_session", phone)
        stored = self._sessions.get(session_key)
        return stored is not None and stored == session_token

    async def invalidate_session(self, phone: str, tenant: Any) -> None:
        session_key = self._key(tenant, "dossier_session", phone)
        self._sessions.pop(session_key, None)


# ── Mock dossier data factories ─────────────────────────────────────


def make_dossier_detail(
    numero: str,
    statut: DossierStatut = DossierStatut.en_cours,
    dossier_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    **overrides: Any,
) -> MagicMock:
    """Create a mock DossierDetail with preset attributes."""
    d = MagicMock()
    d.id = dossier_id or uuid.uuid4()
    d.numero = numero
    d.statut = statut
    d.contact_id = contact_id
    d.type_projet = overrides.get("type_projet", "Industrie")
    d.raison_sociale = overrides.get("raison_sociale", "SARL Alpha")
    d.region = overrides.get("region", "Rabat-Salé-Kénitra")
    d.secteur = overrides.get("secteur", "Industrie")
    d.date_depot = overrides.get("date_depot")
    d.date_derniere_maj = overrides.get("date_derniere_maj")
    d.montant_investissement = overrides.get("montant_investissement")
    d.observations = overrides.get("observations")
    d.history = overrides.get("history", [])
    return d


def make_dossier_read(
    numero: str,
    statut: DossierStatut = DossierStatut.en_cours,
    dossier_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
) -> MagicMock:
    """Create a mock DossierRead with preset attributes."""
    d = MagicMock()
    d.id = dossier_id or uuid.uuid4()
    d.numero = numero
    d.statut = statut
    d.contact_id = contact_id
    return d


def make_contact_mock(
    phone: str,
    name: str = "Test User",
    language: Language = Language.fr,
    opt_in_status: OptInStatus = OptInStatus.opted_in,
    contact_id: uuid.UUID | None = None,
) -> MagicMock:
    """Create a mock Contact ORM object."""
    c = MagicMock()
    c.id = contact_id or uuid.uuid4()
    c.phone = phone
    c.name = name
    c.language = language
    c.opt_in_status = opt_in_status
    return c


# ── ConversationState helper ────────────────────────────────────────


def make_tracking_state(
    query: str,
    phone: str = PHONE_A,
    language: str = "fr",
) -> dict[str, Any]:
    """Build a minimal ConversationState dict for TrackingAgent.handle()."""
    return {
        "tenant_slug": TEST_TENANT_SLUG_A,
        "phone": phone,
        "language": language,
        "intent": "suivi_dossier",
        "query": query,
        "messages": [],
        "retrieved_chunks": [],
        "response": "",
        "chunk_ids": [],
        "confidence": 0.0,
        "is_safe": True,
        "guard_message": None,
        "incentive_state": {},
        "error": None,
        "is_internal_user": False,
        "agent_type": "public",
        "escalation_id": None,
        "consecutive_low_confidence": 0,
        "conversation_id": str(uuid.uuid4()),
        "tracking_state": None,
        "authenticated_phone": None,
    }


# ── Tracking agent fixture ──────────────────────────────────────────


@pytest.fixture
def tracking_agent_env():
    """Create a fresh TrackingAgent with in-memory dependencies.

    Returns: (agent, otp_service, dossier_service_mock, state_manager)
    """
    state_mgr = InMemoryTrackingStateManager()
    otp_svc = InMemoryOTPStore()
    dossier_svc = AsyncMock(spec=DossierService)
    agent = TrackingAgent(
        otp_service=otp_svc,
        dossier_service=dossier_svc,
        state_manager=state_mgr,
    )
    return agent, otp_svc, dossier_svc, state_mgr


@pytest.fixture
def tenant_a() -> MagicMock:
    return make_tenant(TEST_TENANT_SLUG_A, TEST_TENANT_ID_A)


@pytest.fixture
def tenant_b() -> MagicMock:
    return make_tenant(TEST_TENANT_SLUG_B, TEST_TENANT_ID_B)


# ── Excel fixture generators ────────────────────────────────────────

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def sample_import_xlsx() -> str:
    """Generate a valid 10-row Excel file. Returns file path."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Dossiers"
    ws.append([
        "Numéro", "Statut", "Type Projet", "Raison Sociale",
        "Téléphone", "Observations",
    ])
    statuts = ["en_cours", "valide", "en_attente", "incomplet", "en_cours"]
    for i in range(10):
        ws.append([
            f"2024-IMP-{i + 1:03d}",
            statuts[i % len(statuts)],
            "Industrie" if i % 2 == 0 else "Services",
            f"Entreprise Test {i + 1}",
            f"+2126400000{i:02d}",
            f"Observation {i + 1}" if i % 3 == 0 else "",
        ])

    file_path = os.path.join(FIXTURES_DIR, "sample_import.xlsx")
    wb.save(file_path)
    wb.close()
    yield file_path
    # Cleanup
    if os.path.exists(file_path):
        os.remove(file_path)


@pytest.fixture
def sample_import_errors_xlsx() -> str:
    """Generate an Excel file with deliberate errors. Returns file path."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Dossiers"
    ws.append([
        "Numéro", "Statut", "Type Projet", "Raison Sociale",
        "Téléphone", "Observations",
    ])
    # Row 2: valid
    ws.append([
        "2024-ERR-001", "en_cours", "Industrie", "Normal Company",
        "+212640000001", "OK",
    ])
    # Row 3: missing numero
    ws.append([
        "", "en_cours", "Industrie", "Missing Numero",
        "+212640000002", "",
    ])
    # Row 4: SQL injection in raison_sociale
    ws.append([
        "2024-ERR-003", "en_cours", "Industrie",
        "'; DROP TABLE dossiers; --",
        "+212640000003", "",
    ])
    # Row 5: XSS in observations
    ws.append([
        "2024-ERR-004", "en_cours", "Industrie", "XSS Company",
        "+212640000004", "<script>alert('xss')</script>",
    ])
    # Row 6: valid
    ws.append([
        "2024-ERR-005", "valide", "Services", "Valid Company",
        "+212640000005", "Observations normales",
    ])

    file_path = os.path.join(FIXTURES_DIR, "sample_import_errors.xlsx")
    wb.save(file_path)
    wb.close()
    yield file_path
    if os.path.exists(file_path):
        os.remove(file_path)


# ── Singleton reset (autouse) ───────────────────────────────────────

_PHASE3_SINGLETONS = {
    "app.services.dossier.service": "_dossier_service",
    "app.services.dossier.otp": "_dossier_otp_service",
    "app.services.dossier.import_service": "_dossier_import_service",
    "app.services.notification.service": "_notification_service",
    "app.services.orchestrator.tracking_agent": "_tracking_agent",
    "app.services.orchestrator.graph": "_conversation_graph",
}


@pytest.fixture(autouse=True)
def reset_phase3_singletons():
    """Reset Phase 3 service singletons after each test."""
    yield
    for module_path, var_name in _PHASE3_SINGLETONS.items():
        try:
            mod = importlib.import_module(module_path)
            if hasattr(mod, var_name):
                setattr(mod, var_name, None)
        except ImportError:
            pass
