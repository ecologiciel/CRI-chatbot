"""test_e2e_phase3 — 8 E2E scenarios for Phase 3 (dossier tracking, import, notifications).

Exercises:
- TrackingAgent OTP state machine (idle → awaiting_identifier → otp_sent → authenticated)
- Anti-bruteforce (3 bad OTP attempts → block)
- Anti-BOLA (phone A cannot access phone B's dossier)
- DossierImportService (parse, sanitize, validate, dedup)
- NotificationService (decision matrix, opt-in, send)
- Multilingual messages (FR/AR/EN)
- Multi-tenant isolation (tenant A dossiers invisible from tenant B)

Run: pytest tests/test_e2e_phase3.py -v -m "e2e and phase3"
"""

from __future__ import annotations

pytest_plugins = ["tests.conftest_phase3"]

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import DossierStatut, Language, OptInStatus
from app.services.dossier.import_service import DossierImportService
from app.services.dossier.service import DossierService, UnauthorizedDossierAccess
from app.services.notification.service import (
    DossierChangeEvent,
    NotificationEventType,
    NotificationPriority,
    NotificationService,
)
from app.services.orchestrator.tracking_agent import TrackingAgent
from app.services.orchestrator.tracking_state import TrackingStep

from .conftest_phase3 import (
    CONTACT_A_ID,
    CONTACT_B_ID,
    CONTACT_C_ID,
    DOSSIER_A1_ID,
    DOSSIER_A2_ID,
    DOSSIER_B1_ID,
    PHONE_A,
    PHONE_B,
    PHONE_C,
    TEST_TENANT_SLUG_A,
    TEST_TENANT_SLUG_B,
    InMemoryOTPStore,
    InMemoryTrackingStateManager,
    make_contact_mock,
    make_dossier_detail,
    make_dossier_read,
    make_tenant,
    make_tracking_state,
)


# ═══════════════════════════════════════════════════════════════════
# Scenario 1 — Full OTP Flow (happy path)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.e2e
@pytest.mark.phase3
@pytest.mark.asyncio
async def test_e2e_otp_full_flow(tracking_agent_env, tenant_a):
    """Complete tracking flow: ask identifier → give numero → OTP → dossiers shown."""
    agent, otp_svc, dossier_svc, state_mgr = tracking_agent_env

    # Configure dossier service
    detail_001 = make_dossier_detail(
        "2024-10001", DossierStatut.en_cours,
        dossier_id=DOSSIER_A1_ID, contact_id=CONTACT_A_ID,
    )
    detail_002 = make_dossier_detail(
        "2024-10002", DossierStatut.valide,
        dossier_id=DOSSIER_A2_ID, contact_id=CONTACT_A_ID,
    )
    read_001 = make_dossier_read(
        "2024-10001", DossierStatut.en_cours,
        dossier_id=DOSSIER_A1_ID, contact_id=CONTACT_A_ID,
    )
    read_002 = make_dossier_read(
        "2024-10002", DossierStatut.valide,
        dossier_id=DOSSIER_A2_ID, contact_id=CONTACT_A_ID,
    )

    dossier_svc.get_dossier_by_numero = AsyncMock(return_value=detail_001)
    dossier_svc.get_dossiers_by_phone = AsyncMock(return_value=[read_001, read_002])
    dossier_svc.get_dossier_with_bola_check = AsyncMock(
        side_effect=lambda t, did, p: detail_001 if did == DOSSIER_A1_ID else detail_002,
    )
    dossier_svc.format_dossier_for_whatsapp = MagicMock(
        side_effect=lambda d, lang: f"Dossier N° {d.numero}",
    )

    # ── Step 1: Initial message → ask for identifier ──
    state = make_tracking_state("je veux suivre mon dossier", phone=PHONE_A)
    result = await agent.handle(state, tenant_a)

    assert "numéro de dossier" in result["response"].lower() or "CIN" in result["response"]
    ts = await state_mgr.get_state(PHONE_A, tenant_a)
    assert ts.step == TrackingStep.awaiting_identifier

    # ── Step 2: Provide dossier numero → OTP sent ──
    state = make_tracking_state("2024-10001", phone=PHONE_A)
    result = await agent.handle(state, tenant_a)

    assert "code" in result["response"].lower() or "رمز" in result["response"]
    dossier_svc.get_dossier_by_numero.assert_called()
    ts = await state_mgr.get_state(PHONE_A, tenant_a)
    assert ts.step == TrackingStep.otp_sent
    captured_otp = otp_svc._last_otp
    assert captured_otp is not None
    assert len(captured_otp) == 6

    # ── Step 3: Submit correct OTP → dossiers displayed ──
    state = make_tracking_state(captured_otp, phone=PHONE_A)
    result = await agent.handle(state, tenant_a)

    assert "2024-10001" in result["response"]
    dossier_svc.get_dossiers_by_phone.assert_called()
    ts = await state_mgr.get_state(PHONE_A, tenant_a)
    assert ts.step == TrackingStep.authenticated
    assert ts.session_token is not None


# ═══════════════════════════════════════════════════════════════════
# Scenario 2 — OTP Anti-Bruteforce
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.e2e
@pytest.mark.phase3
@pytest.mark.asyncio
async def test_e2e_otp_antibruteforce(tracking_agent_env, tenant_a):
    """3 bad OTP attempts → max attempts message → state cleared."""
    agent, otp_svc, dossier_svc, state_mgr = tracking_agent_env

    detail = make_dossier_detail(
        "2024-10001", DossierStatut.en_cours,
        dossier_id=DOSSIER_A1_ID, contact_id=CONTACT_A_ID,
    )
    dossier_svc.get_dossier_by_numero = AsyncMock(return_value=detail)
    dossier_svc.get_dossiers_by_phone = AsyncMock(return_value=[])

    # ── Trigger flow: identifier in query → straight to OTP sent ──
    state = make_tracking_state("suivre 2024-10001", phone=PHONE_A)
    result = await agent.handle(state, tenant_a)
    assert "code" in result["response"].lower() or "رمز" in result["response"]

    ts = await state_mgr.get_state(PHONE_A, tenant_a)
    assert ts.step == TrackingStep.otp_sent

    # ── Bad OTP 1 ──
    state = make_tracking_state("111111", phone=PHONE_A)
    result = await agent.handle(state, tenant_a)
    assert "2" in result["response"]  # 2 remaining

    # ── Bad OTP 2 ──
    state = make_tracking_state("222222", phone=PHONE_A)
    result = await agent.handle(state, tenant_a)
    assert "1" in result["response"]  # 1 remaining

    # ── Bad OTP 3 → max attempts ──
    state = make_tracking_state("333333", phone=PHONE_A)
    result = await agent.handle(state, tenant_a)

    # Check for max attempts message (FR: "maximal", AR: "الأقصى", EN: "Maximum")
    resp_lower = result["response"].lower()
    assert "maximal" in resp_lower or "maximum" in resp_lower or "الأقصى" in result["response"]

    # State should be cleared (back to idle)
    ts = await state_mgr.get_state(PHONE_A, tenant_a)
    assert ts.step == TrackingStep.idle


# ═══════════════════════════════════════════════════════════════════
# Scenario 3 — Anti-BOLA
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.e2e
@pytest.mark.phase3
@pytest.mark.asyncio
async def test_e2e_anti_bola(tracking_agent_env, tenant_a):
    """Authenticated phone A cannot access phone B's dossier."""
    agent, otp_svc, dossier_svc, state_mgr = tracking_agent_env

    # Dossier A belongs to PHONE_A, dossier B belongs to PHONE_B
    detail_a = make_dossier_detail(
        "2024-10001", DossierStatut.en_cours,
        dossier_id=DOSSIER_A1_ID, contact_id=CONTACT_A_ID,
    )
    detail_b = make_dossier_detail(
        "2024-99099", DossierStatut.valide,
        dossier_id=DOSSIER_B1_ID, contact_id=CONTACT_B_ID,
    )
    read_a = make_dossier_read(
        "2024-10001", DossierStatut.en_cours,
        dossier_id=DOSSIER_A1_ID, contact_id=CONTACT_A_ID,
    )

    # get_dossier_by_numero returns dossier regardless (lookup by numero)
    async def _get_by_numero(tenant, numero):
        if numero == "2024-10001":
            return detail_a
        if numero == "2024-99099":
            return detail_b
        return None

    dossier_svc.get_dossier_by_numero = AsyncMock(side_effect=_get_by_numero)
    dossier_svc.get_dossiers_by_phone = AsyncMock(return_value=[read_a])

    # BOLA check: phone A can access dossier A, but NOT dossier B
    async def _bola_check(tenant, dossier_id, phone):
        if dossier_id == DOSSIER_A1_ID and phone == PHONE_A:
            return detail_a
        raise UnauthorizedDossierAccess(phone, str(dossier_id))

    dossier_svc.get_dossier_with_bola_check = AsyncMock(side_effect=_bola_check)
    dossier_svc.format_dossier_for_whatsapp = MagicMock(
        side_effect=lambda d, lang: f"Dossier N° {d.numero}",
    )

    # ── Complete OTP flow for PHONE_A ──
    state = make_tracking_state("suivre 2024-10001", phone=PHONE_A)
    await agent.handle(state, tenant_a)  # OTP sent

    otp = otp_svc._last_otp
    state = make_tracking_state(otp, phone=PHONE_A)
    result = await agent.handle(state, tenant_a)  # Authenticated
    assert "2024-10001" in result["response"]

    ts = await state_mgr.get_state(PHONE_A, tenant_a)
    assert ts.step == TrackingStep.authenticated

    # ── Attempt to access phone B's dossier → graceful rejection ──
    state = make_tracking_state("2024-99099", phone=PHONE_A)
    result = await agent.handle(state, tenant_a)

    # The agent catches UnauthorizedDossierAccess and returns "no dossier found"
    resp_lower = result["response"].lower()
    assert "aucun dossier" in resp_lower or "no file" in resp_lower or "لم يتم" in result["response"]

    # Verify no dossier B data leaked
    assert "2024-99099" not in result["response"]


# ═══════════════════════════════════════════════════════════════════
# Scenario 4 — Import Triggers Notifications
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.e2e
@pytest.mark.phase3
@pytest.mark.asyncio
async def test_e2e_import_triggers_notifications(tenant_a):
    """Status changes trigger notifications; opt-out contacts are skipped."""
    mock_sender = AsyncMock()
    mock_sender.send_template = AsyncMock(return_value="wamid.test123")
    mock_audit = AsyncMock()
    mock_audit.log_action = AsyncMock()

    notification_svc = NotificationService(
        sender=mock_sender,
        audit=mock_audit,
    )

    # Contact A: opted_in, Contact C: opted_out
    contact_a = make_contact_mock(
        PHONE_A, "User A", Language.fr, OptInStatus.opted_in, CONTACT_A_ID,
    )
    contact_c = make_contact_mock(
        PHONE_C, "User C", Language.fr, OptInStatus.opted_out, CONTACT_C_ID,
    )

    # Mock _load_contact to return appropriate contacts
    async def _load_contact(contact_id, tenant):
        if contact_id == CONTACT_A_ID:
            return contact_a
        if contact_id == CONTACT_C_ID:
            return contact_c
        return None

    notification_svc._load_contact = AsyncMock(side_effect=_load_contact)

    # Mock Redis dedup (always allow — first time)
    with patch("app.services.notification.service.get_redis") as mock_get_redis:
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # NX: key was set (not duplicate)
        mock_get_redis.return_value = mock_redis

        # ── Event 1: en_cours → valide (opted_in contact A) → should send ──
        event_1 = DossierChangeEvent(
            dossier_id=str(DOSSIER_A1_ID),
            numero="2024-10001",
            contact_id=str(CONTACT_A_ID),
            old_statut="en_cours",
            new_statut="valide",
        )
        result_1 = await notification_svc.send_notification(event_1, tenant_a)
        assert result_1["status"] == "sent"
        assert mock_sender.send_template.call_count == 1

        # ── Event 2: en_cours → complement (opted_out contact C) → skipped ──
        event_2 = DossierChangeEvent(
            dossier_id=str(DOSSIER_B1_ID),
            numero="2024-TEST-003",
            contact_id=str(CONTACT_C_ID),
            old_statut="en_cours",
            new_statut="complement",
        )
        result_2 = await notification_svc.send_notification(event_2, tenant_a)
        assert result_2["status"] == "skipped"
        assert result_2["reason"] == "opted_out"

        # Sender was NOT called again (still 1)
        assert mock_sender.send_template.call_count == 1

    # ── Verify decision matrix ──
    decision = notification_svc.should_notify("en_cours", "valide")
    assert decision.should_send is True
    assert decision.event_type == NotificationEventType.decision_finale
    assert decision.priority == NotificationPriority.high

    decision_same = notification_svc.should_notify("en_cours", "en_cours")
    assert decision_same.should_send is False


# ═══════════════════════════════════════════════════════════════════
# Scenario 5 — Import Deduplication
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.e2e
@pytest.mark.phase3
@pytest.mark.asyncio
async def test_e2e_import_deduplication(sample_import_xlsx, tenant_a):
    """Same file imported twice → second rejected as duplicate hash."""
    import_svc = DossierImportService()

    # Mock db_session for SyncLog duplicate check
    mock_session = AsyncMock()
    mock_result = MagicMock()

    # First call: no existing hash → None (not duplicate)
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    tenant_a.db_session = MagicMock(return_value=mock_cm)

    # ── First import: valid ──
    result_1 = await import_svc.validate_file(sample_import_xlsx, tenant_a)
    assert result_1.is_valid is True
    assert result_1.is_duplicate is False
    assert result_1.file_hash is not None
    captured_hash = result_1.file_hash

    # ── Reconfigure mock: hash now exists in SyncLog ──
    mock_result_dup = MagicMock()
    mock_result_dup.scalar_one_or_none = MagicMock(return_value=uuid.uuid4())
    mock_session.execute = AsyncMock(return_value=mock_result_dup)

    # ── Second import: duplicate ──
    result_2 = await import_svc.validate_file(sample_import_xlsx, tenant_a)
    assert result_2.is_valid is False
    assert result_2.is_duplicate is True
    assert "déjà été importé" in result_2.error
    assert result_2.file_hash == captured_hash


# ═══════════════════════════════════════════════════════════════════
# Scenario 6 — Import with Errors (parse + sanitize)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.e2e
@pytest.mark.phase3
@pytest.mark.asyncio
async def test_e2e_import_with_errors(sample_import_errors_xlsx):
    """Invalid rows have fields sanitized; valid rows pass through."""
    import_svc = DossierImportService()

    # ── Parse Excel ──
    rows = import_svc.parse_excel(sample_import_errors_xlsx)
    assert len(rows) == 5  # 5 data rows (header excluded)

    # ── Sanitize all rows ──
    sanitized = [import_svc.sanitize_row(row) for row in rows]

    # Row 0 (2024-ERR-001): valid, should be clean
    assert sanitized[0].numero == "2024-ERR-001"
    assert sanitized[0].raison_sociale == "Normal Company"

    # Row 1: missing numero → should remain None/empty after sanitize
    assert sanitized[1].numero is None or sanitized[1].numero == ""

    # Row 2 (2024-ERR-003): SQL injection neutralized ("; DROP" pattern removed)
    assert "DROP TABLE" not in (sanitized[2].raison_sociale or "").upper()
    assert "; DROP" not in (sanitized[2].raison_sociale or "").upper()

    # Row 3 (2024-ERR-004): HTML tags stripped from observations
    assert "<script>" not in (sanitized[3].observations or "")
    assert "</script>" not in (sanitized[3].observations or "")

    # Row 4 (2024-ERR-005): valid row passes through
    assert sanitized[4].numero == "2024-ERR-005"
    assert sanitized[4].statut == "valide"
    assert sanitized[4].raison_sociale == "Valid Company"


# ═══════════════════════════════════════════════════════════════════
# Scenario 7 — Tracking Agent Multi-Language
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.e2e
@pytest.mark.phase3
@pytest.mark.asyncio
async def test_e2e_tracking_multilang(tenant_a):
    """TrackingAgent messages adapt to FR, AR, and EN."""
    detail = make_dossier_detail(
        "2024-10001", DossierStatut.en_cours,
        dossier_id=DOSSIER_A1_ID, contact_id=CONTACT_A_ID,
    )

    # ── French ──
    state_mgr_fr = InMemoryTrackingStateManager()
    otp_fr = InMemoryOTPStore()
    dossier_svc_fr = AsyncMock(spec=DossierService)
    dossier_svc_fr.get_dossier_by_numero = AsyncMock(return_value=detail)
    agent_fr = TrackingAgent(otp_fr, dossier_svc_fr, state_mgr_fr)

    state = make_tracking_state("suivre mon dossier", language="fr")
    result = await agent_fr.handle(state, tenant_a)
    assert "numéro de dossier" in result["response"].lower()

    # Provide identifier → OTP sent in French
    state = make_tracking_state("2024-10001", language="fr")
    result = await agent_fr.handle(state, tenant_a)
    assert "code" in result["response"].lower() and "vérification" in result["response"].lower()

    # ── Arabic ──
    state_mgr_ar = InMemoryTrackingStateManager()
    otp_ar = InMemoryOTPStore()
    dossier_svc_ar = AsyncMock(spec=DossierService)
    dossier_svc_ar.get_dossier_by_numero = AsyncMock(return_value=detail)
    agent_ar = TrackingAgent(otp_ar, dossier_svc_ar, state_mgr_ar)

    state = make_tracking_state("أريد متابعة ملفي", language="ar")
    result = await agent_ar.handle(state, tenant_a)
    assert "رقم الملف" in result["response"] or "الملف" in result["response"]

    # Identifier → OTP in Arabic
    state = make_tracking_state("2024-10001", language="ar")
    result = await agent_ar.handle(state, tenant_a)
    assert "رمز" in result["response"]  # "رمز التحقق" = verification code

    # ── English ──
    state_mgr_en = InMemoryTrackingStateManager()
    otp_en = InMemoryOTPStore()
    dossier_svc_en = AsyncMock(spec=DossierService)
    dossier_svc_en.get_dossier_by_numero = AsyncMock(return_value=detail)
    agent_en = TrackingAgent(otp_en, dossier_svc_en, state_mgr_en)

    state = make_tracking_state("track my file", language="en")
    result = await agent_en.handle(state, tenant_a)
    assert "file number" in result["response"].lower() or "CIN" in result["response"]

    # Identifier → OTP in English
    state = make_tracking_state("2024-10001", language="en")
    result = await agent_en.handle(state, tenant_a)
    assert "verification code" in result["response"].lower() or "code" in result["response"].lower()


# ═══════════════════════════════════════════════════════════════════
# Scenario 8 — Multi-Tenant Isolation
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.e2e
@pytest.mark.phase3
@pytest.mark.asyncio
async def test_e2e_multitenant_isolation(tenant_a, tenant_b):
    """Dossiers in tenant A are invisible from tenant B."""
    detail_a = make_dossier_detail(
        "2024-001", DossierStatut.en_cours,
        dossier_id=DOSSIER_A1_ID, contact_id=CONTACT_A_ID,
    )

    # ── Tenant A: dossier exists ──
    state_mgr_a = InMemoryTrackingStateManager()
    otp_a = InMemoryOTPStore()
    dossier_svc_a = AsyncMock(spec=DossierService)
    dossier_svc_a.get_dossier_by_numero = AsyncMock(return_value=detail_a)
    agent_a = TrackingAgent(otp_a, dossier_svc_a, state_mgr_a)

    # ── Tenant B: dossier does NOT exist ──
    state_mgr_b = InMemoryTrackingStateManager()
    otp_b = InMemoryOTPStore()
    dossier_svc_b = AsyncMock(spec=DossierService)
    dossier_svc_b.get_dossier_by_numero = AsyncMock(return_value=None)
    agent_b = TrackingAgent(otp_b, dossier_svc_b, state_mgr_b)

    # ── Tenant A: dossier found → OTP sent ──
    state = make_tracking_state("suivre 2024-001", phone=PHONE_A)
    result_a = await agent_a.handle(state, tenant_a)
    assert "code" in result_a["response"].lower()

    ts_a = await state_mgr_a.get_state(PHONE_A, tenant_a)
    assert ts_a.step == TrackingStep.otp_sent

    # ── Tenant B: same numero → not found ──
    state = make_tracking_state("suivre 2024-001", phone=PHONE_A)
    result_b = await agent_b.handle(state, tenant_b)
    resp_lower = result_b["response"].lower()
    assert "aucun dossier" in resp_lower or "no file" in resp_lower

    # Tenant B state did NOT advance past awaiting_identifier
    ts_b = await state_mgr_b.get_state(PHONE_A, tenant_b)
    assert ts_b.step == TrackingStep.awaiting_identifier or ts_b.step == TrackingStep.idle

    # ── Cross-tenant state isolation ──
    # Tenant B's state manager has NO state from tenant A
    ts_b_check = await state_mgr_b.get_state(PHONE_A, tenant_a)
    # key includes tenant slug, so tenant_a key in state_mgr_b returns idle (empty)
    assert ts_b_check.step == TrackingStep.idle

    # Tenant A's state is untouched
    ts_a_check = await state_mgr_a.get_state(PHONE_A, tenant_a)
    assert ts_a_check.step == TrackingStep.otp_sent
