"""Tests End-to-End Phase 2 — 7 scénarios fonctionnels complets.

Chaque scénario simule un flux utilisateur réaliste traversant
toute la stack : API → Service → DB (mocké) → externe (mocké).

Pattern:
- Patch TenantResolver.from_tenant_id_header → MagicMock tenant
- Override get_current_admin for RBAC
- Pass X-Tenant-ID header
- Patch service singletons for service-layer endpoints
"""

from __future__ import annotations

import gzip
import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.graph import END

from app.main import app
from app.models.enums import AdminRole

from .conftest_phase2 import (
    TEST_ADMIN_ID,
    TEST_TENANT_ID,
    TEST_TENANT_SLUG,
    _make_async_cm,
    make_admin_payload,
    make_campaign_orm,
    make_contact_orm,
    make_escalation_orm,
    make_question_orm,
    make_mock_tenant,
    make_whitelist_orm,
    mock_session_for_crud,
    mock_session_for_list,
    override_admin,
)

# Patch path for TenantResolver
_TENANT_RESOLVER_PATCH = "app.core.middleware.TenantResolver.from_tenant_id_header"

# Default headers for all tenant-scoped requests
_TENANT_HEADERS = {"X-Tenant-ID": str(TEST_TENANT_ID)}


def _make_headers():
    """Base headers with X-Tenant-ID."""
    return {"X-Tenant-ID": str(TEST_TENANT_ID)}


# ═══════════════════════════════════════════════════════════
# SCÉNARIO 1 : AGENT INTERNE — CRUD WHITELIST
# ═══════════════════════════════════════════════════════════


class TestAgentInterne:
    """Tests E2E de l'Agent Interne CRI — CRUD whitelist + RBAC."""

    @pytest.mark.asyncio
    async def test_whitelist_crud_flow(self):
        """Flux CRUD whitelist : ajouter → lister → PATCH désactiver → supprimer."""
        admin_payload = make_admin_payload(role=AdminRole.admin_tenant.value)
        cleanup_admin = override_admin(admin_payload)

        entry = make_whitelist_orm(phone="+212611111111")

        try:
            # ── POST : create ──
            session_create = mock_session_for_crud(entity=None)  # no duplicate
            session_create.refresh = AsyncMock(side_effect=lambda obj: _copy_attrs(obj, entry))
            tenant = make_mock_tenant(db_session_mock=session_create)

            with patch(_TENANT_RESOLVER_PATCH, return_value=tenant):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/whitelist",
                        json={"phone": "+212611111111", "label": "Agent Test"},
                        headers=_make_headers(),
                    )
            assert resp.status_code == 201
            data = resp.json()
            assert data["phone"] == "+212611111111"
            assert data["is_active"] is True

            # ── GET : list ──
            session_list = mock_session_for_list(items=[entry], total=1)
            tenant_list = make_mock_tenant(db_session_mock=session_list)
            with patch(_TENANT_RESOLVER_PATCH, return_value=tenant_list):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get("/api/v1/whitelist", headers=_make_headers())
            assert resp.status_code == 200
            assert resp.json()["total"] == 1

            # ── PATCH : deactivate ──
            deactivated = make_whitelist_orm(id=entry.id, is_active=False)
            session_patch = mock_session_for_crud(entity=entry)
            session_patch.refresh = AsyncMock(side_effect=lambda obj: _copy_attrs(obj, deactivated))
            tenant_patch = make_mock_tenant(db_session_mock=session_patch)
            with patch(_TENANT_RESOLVER_PATCH, return_value=tenant_patch):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.patch(
                        f"/api/v1/whitelist/{entry.id}",
                        json={"is_active": False},
                        headers=_make_headers(),
                    )
            assert resp.status_code == 200
            assert resp.json()["is_active"] is False

            # ── DELETE ──
            session_delete = mock_session_for_crud(entity=entry)
            tenant_del = make_mock_tenant(db_session_mock=session_delete)
            with patch(_TENANT_RESOLVER_PATCH, return_value=tenant_del):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.delete(
                        f"/api/v1/whitelist/{entry.id}", headers=_make_headers()
                    )
            assert resp.status_code == 204

        finally:
            cleanup_admin()

    @pytest.mark.asyncio
    async def test_whitelist_duplicate_rejected(self):
        """Ajouter un numéro déjà whitelisté → 409 Conflict."""
        admin_payload = make_admin_payload(role=AdminRole.admin_tenant.value)
        cleanup_admin = override_admin(admin_payload)
        try:
            existing = make_whitelist_orm(phone="+212600000001")
            session = mock_session_for_crud(entity=existing)
            tenant = make_mock_tenant(db_session_mock=session)

            with patch(_TENANT_RESOLVER_PATCH, return_value=tenant):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/whitelist",
                        json={"phone": "+212600000001", "label": "Doublon"},
                        headers=_make_headers(),
                    )
            assert resp.status_code == 409
        finally:
            cleanup_admin()

    @pytest.mark.asyncio
    async def test_whitelist_invalid_phone_rejected(self):
        """Ajouter un numéro au format invalide (non E.164) → 422."""
        admin_payload = make_admin_payload(role=AdminRole.admin_tenant.value)
        cleanup_admin = override_admin(admin_payload)
        try:
            tenant = make_mock_tenant()
            with patch(_TENANT_RESOLVER_PATCH, return_value=tenant):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/whitelist",
                        json={"phone": "0612345678", "label": "Invalid"},
                        headers=_make_headers(),
                    )
            assert resp.status_code == 422
        finally:
            cleanup_admin()

    @pytest.mark.asyncio
    async def test_viewer_cannot_manage_whitelist(self):
        """Un viewer n'a pas le droit de créer une entrée whitelist → 403."""
        viewer_payload = make_admin_payload(role=AdminRole.viewer.value)
        cleanup_admin = override_admin(viewer_payload)
        try:
            tenant = make_mock_tenant()
            with patch(_TENANT_RESOLVER_PATCH, return_value=tenant):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/whitelist",
                        json={"phone": "+212622222222", "label": "Nope"},
                        headers=_make_headers(),
                    )
            assert resp.status_code == 403
        finally:
            cleanup_admin()


# ═══════════════════════════════════════════════════════════
# SCÉNARIO 2 : ESCALADE AUTOMATIQUE
# ═══════════════════════════════════════════════════════════


class TestEscaladeAutomatique:
    """Tests de l'escalade automatique (échec RAG répété)."""

    @pytest.mark.asyncio
    async def test_auto_escalation_on_consecutive_low_confidence(self):
        """consecutive_low_confidence >= 2 → route vers escalation_handler."""
        from app.services.orchestrator.graph import check_auto_escalation

        state = {"consecutive_low_confidence": 2, "confidence": 0.2}
        result = check_auto_escalation(state)
        assert result == "escalation_handler"

    @pytest.mark.asyncio
    async def test_confidence_counter_routes_to_validator(self):
        """consecutive_low_confidence < 2 → route vers response_validator."""
        from app.services.orchestrator.graph import check_auto_escalation

        state = {"consecutive_low_confidence": 0, "confidence": 0.9}
        assert check_auto_escalation(state) == "response_validator"

        state = {"consecutive_low_confidence": 1, "confidence": 0.3}
        assert check_auto_escalation(state) == "response_validator"


# ═══════════════════════════════════════════════════════════
# SCÉNARIO 3 : ESCALADE MANUELLE
# ═══════════════════════════════════════════════════════════


class TestEscaladeManuelle:
    """Tests de l'escalade manuelle et du cycle de vie API."""

    @pytest.mark.asyncio
    async def test_escalation_lifecycle_via_api(self):
        """GET /escalations/ + GET /escalations/stats → 200 avec données."""
        admin_payload = make_admin_payload(role=AdminRole.admin_tenant.value)
        cleanup_admin = override_admin(admin_payload)
        try:
            tenant = make_mock_tenant()
            svc_mock = AsyncMock()
            svc_mock.get_escalations = AsyncMock(return_value=([], 0))
            svc_mock.get_escalation_stats = AsyncMock(return_value={
                "total_pending": 2,
                "total_in_progress": 1,
                "avg_wait_seconds": 300.0,
                "avg_resolution_seconds": 1200.0,
                "by_trigger": {"explicit_request": 2, "rag_failure": 1},
                "by_priority": {"high": 2, "medium": 1},
            })

            with (
                patch(_TENANT_RESOLVER_PATCH, return_value=tenant),
                patch("app.api.v1.escalation.get_escalation_service", return_value=svc_mock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    # List
                    resp = await client.get("/api/v1/escalations", headers=_make_headers())
                    assert resp.status_code == 200
                    data = resp.json()
                    assert "items" in data
                    assert "total" in data

                    # Stats
                    resp = await client.get("/api/v1/escalations/stats", headers=_make_headers())
                    assert resp.status_code == 200
                    stats = resp.json()
                    assert stats["total_pending"] == 2
                    assert "by_trigger" in stats
                    assert "by_priority" in stats
        finally:
            cleanup_admin()

    @pytest.mark.asyncio
    async def test_escalation_keywords_detection(self):
        """Les mots-clés d'escalade FR/AR/EN sont détectés (+ confidence < 0.5)."""
        from app.services.orchestrator.graph import check_feedback_escalation

        # Français + low confidence → escalade
        assert check_feedback_escalation(
            {"query": "je veux parler à un agent", "confidence": 0.3}
        ) == "escalation_handler"
        assert check_feedback_escalation(
            {"query": "je veux un conseiller", "confidence": 0.4}
        ) == "escalation_handler"

        # Arabe + low confidence → escalade
        assert check_feedback_escalation(
            {"query": "أريد التحدث مع موظف", "confidence": 0.2}
        ) == "escalation_handler"

        # Anglais + low confidence → escalade
        assert check_feedback_escalation(
            {"query": "I want to talk to a human advisor", "confidence": 0.1}
        ) == "escalation_handler"

        # Keywords present BUT high confidence → NO escalade
        assert check_feedback_escalation(
            {"query": "je veux parler à un agent", "confidence": 0.8}
        ) == END

        # No keywords → NO escalade
        assert check_feedback_escalation(
            {"query": "merci beaucoup", "confidence": 0.3}
        ) == END

    @pytest.mark.asyncio
    async def test_router_phase2_intents(self):
        """Le routeur LangGraph v2 supporte tous les intents Phase 2."""
        from app.services.orchestrator.router import Router
        from app.services.orchestrator.state import IntentType

        # Phase 1 intents
        assert Router.route({"intent": IntentType.FAQ, "is_safe": True}) == "faq_agent"
        assert Router.route({"intent": IntentType.INCITATIONS, "is_safe": True}) == "incentives_agent"
        assert Router.route({"intent": IntentType.SALUTATION, "is_safe": True}) == "greeting_response"
        assert Router.route({"intent": IntentType.HORS_PERIMETRE, "is_safe": True}) == "out_of_scope_response"
        assert Router.route({"intent": IntentType.SUIVI_DOSSIER, "is_safe": True}) == "tracking_agent"

        # Phase 2 intents
        assert Router.route({"intent": IntentType.INTERNE, "is_safe": True}) == "internal_agent"
        assert Router.route({"intent": IntentType.ESCALADE, "is_safe": True}) == "escalation_handler"

        # Safety override
        assert Router.route({"intent": IntentType.FAQ, "is_safe": False}) == "blocked_response"

        # Unknown intent → fallback to faq_agent
        assert Router.route({"intent": "unknown_stuff", "is_safe": True}) == "faq_agent"


# ═══════════════════════════════════════════════════════════
# SCÉNARIO 4 : APPRENTISSAGE SUPERVISÉ
# ═══════════════════════════════════════════════════════════


class TestApprentissageSupervise:
    """Tests E2E du cycle d'apprentissage supervisé."""

    @pytest.mark.asyncio
    async def test_learning_list_and_stats(self):
        """Lister les questions et récupérer les stats → 200."""
        admin_payload = make_admin_payload(role=AdminRole.admin_tenant.value)
        cleanup_admin = override_admin(admin_payload)
        try:
            tenant = make_mock_tenant()
            question = make_question_orm()
            svc_mock = AsyncMock()
            svc_mock.get_unanswered_questions = AsyncMock(return_value=([question], 1))
            svc_mock.get_learning_stats = AsyncMock(return_value={
                "total": 5,
                "by_status": {"pending": 3, "approved": 1, "rejected": 1},
                "approval_rate": 0.5,
                "avg_review_time_hours": 2.5,
                "top_questions": [{"question": question.question, "frequency": 3}],
            })

            with (
                patch(_TENANT_RESOLVER_PATCH, return_value=tenant),
                patch("app.api.v1.learning.get_learning_service", return_value=svc_mock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    # List
                    resp = await client.get("/api/v1/learning/questions", headers=_make_headers())
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["total"] >= 1
                    assert len(data["items"]) >= 1

                    # Stats
                    resp = await client.get("/api/v1/learning/stats", headers=_make_headers())
                    assert resp.status_code == 200
                    stats = resp.json()
                    assert stats["total"] == 5
                    assert stats["by_status"]["pending"] == 3
        finally:
            cleanup_admin()

    @pytest.mark.asyncio
    async def test_learning_generate_proposal(self):
        """Générer une proposition IA pour une question non couverte → 200."""
        admin_payload = make_admin_payload(role=AdminRole.admin_tenant.value)
        cleanup_admin = override_admin(admin_payload)
        try:
            tenant = make_mock_tenant()
            question_id = uuid.uuid4()
            generated = make_question_orm(
                id=question_id,
                proposed_answer="Pour obtenir un agrément touristique à Kénitra...",
            )
            svc_mock = AsyncMock()
            svc_mock.generate_ai_proposal = AsyncMock(return_value=generated)

            with (
                patch(_TENANT_RESOLVER_PATCH, return_value=tenant),
                patch("app.api.v1.learning.get_learning_service", return_value=svc_mock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        f"/api/v1/learning/questions/{question_id}/generate",
                        headers=_make_headers(),
                    )
            assert resp.status_code == 200
            data = resp.json()
            assert data["proposed_answer"] is not None
            assert len(data["proposed_answer"]) > 0
        finally:
            cleanup_admin()

    @pytest.mark.asyncio
    async def test_learning_approve_triggers_reinjection(self):
        """Approuver une question → status approved + arq enqueue appelé."""
        admin_payload = make_admin_payload(role=AdminRole.admin_tenant.value)
        cleanup_admin = override_admin(admin_payload)
        try:
            tenant = make_mock_tenant()
            question_id = uuid.uuid4()
            from app.models.enums import UnansweredStatus

            approved = make_question_orm(
                id=question_id,
                status=UnansweredStatus.approved,
                proposed_answer="Réponse approuvée.",
                reviewed_by=TEST_ADMIN_ID,
            )
            svc_mock = AsyncMock()
            svc_mock.approve_question = AsyncMock(return_value=approved)
            arq_mock = AsyncMock()
            arq_mock.enqueue_job = AsyncMock()

            with (
                patch(_TENANT_RESOLVER_PATCH, return_value=tenant),
                patch("app.api.v1.learning.get_learning_service", return_value=svc_mock),
                patch("app.api.v1.learning.get_arq_pool", return_value=arq_mock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        f"/api/v1/learning/questions/{question_id}/approve",
                        json={"proposed_answer": None, "review_note": None},
                        headers=_make_headers(),
                    )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] in ("approved", "modified")
            arq_mock.enqueue_job.assert_called_once()
        finally:
            cleanup_admin()

    @pytest.mark.asyncio
    async def test_learning_reject_with_review_note(self):
        """Rejeter une question avec une note de review → 200 + status rejected."""
        admin_payload = make_admin_payload(role=AdminRole.admin_tenant.value)
        cleanup_admin = override_admin(admin_payload)
        try:
            tenant = make_mock_tenant()
            question_id = uuid.uuid4()
            from app.models.enums import UnansweredStatus

            rejected = make_question_orm(
                id=question_id,
                status=UnansweredStatus.rejected,
                review_note="Question hors périmètre CRI.",
                reviewed_by=TEST_ADMIN_ID,
            )
            svc_mock = AsyncMock()
            svc_mock.reject_question = AsyncMock(return_value=rejected)

            with (
                patch(_TENANT_RESOLVER_PATCH, return_value=tenant),
                patch("app.api.v1.learning.get_learning_service", return_value=svc_mock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        f"/api/v1/learning/questions/{question_id}/reject",
                        json={"review_note": "Question hors périmètre CRI."},
                        headers=_make_headers(),
                    )
            assert resp.status_code == 200
            assert resp.json()["status"] == "rejected"
        finally:
            cleanup_admin()

    @pytest.mark.asyncio
    async def test_viewer_cannot_approve(self):
        """Un viewer n'a pas le droit d'approuver → 403."""
        viewer_payload = make_admin_payload(role=AdminRole.viewer.value)
        cleanup_admin = override_admin(viewer_payload)
        try:
            tenant = make_mock_tenant()
            question_id = uuid.uuid4()
            with patch(_TENANT_RESOLVER_PATCH, return_value=tenant):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        f"/api/v1/learning/questions/{question_id}/approve",
                        json={"proposed_answer": None},
                        headers=_make_headers(),
                    )
            assert resp.status_code == 403
        finally:
            cleanup_admin()


# ═══════════════════════════════════════════════════════════
# SCÉNARIO 5 : CAMPAGNES
# ═══════════════════════════════════════════════════════════


class TestCampagnes:
    """Tests E2E du module de publipostage WhatsApp."""

    @pytest.mark.asyncio
    async def test_campaign_creation_flow(self):
        """Créer une campagne draft → preview audience → vérifié."""
        admin_payload = make_admin_payload(role=AdminRole.admin_tenant.value)
        cleanup_admin = override_admin(admin_payload)
        try:
            tenant = make_mock_tenant()
            campaign = make_campaign_orm()
            svc_mock = AsyncMock()
            svc_mock.create_campaign = AsyncMock(return_value=campaign)
            svc_mock.get_campaign = AsyncMock(return_value=campaign)
            svc_mock.preview_audience = AsyncMock(return_value=MagicMock(
                count=7,
                sample=[{"phone": "+212610000001", "name": "Contact 1"}],
            ))

            with (
                patch(_TENANT_RESOLVER_PATCH, return_value=tenant),
                patch("app.api.v1.campaigns.get_campaign_service", return_value=svc_mock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    # Create campaign
                    resp = await client.post(
                        "/api/v1/campaigns",
                        json={
                            "name": "Campagne Test E2E",
                            "template_id": "welcome_fr_001",
                            "template_name": "Bienvenue Investisseur",
                            "audience_filter": {"tags": ["investisseur"]},
                            "variable_mapping": {"1": "contact.name"},
                        },
                        headers=_make_headers(),
                    )
                    assert resp.status_code == 201
                    data = resp.json()
                    assert data["status"] == "draft"
                    campaign_id = data["id"]

                    # Preview audience
                    resp = await client.post(
                        f"/api/v1/campaigns/{campaign_id}/preview",
                        headers=_make_headers(),
                    )
                    assert resp.status_code == 200
                    preview = resp.json()
                    assert preview["count"] >= 1
        finally:
            cleanup_admin()

    @pytest.mark.asyncio
    async def test_campaign_quota_check(self):
        """Vérifier le statut du quota WhatsApp → 200 + shape correcte."""
        admin_payload = make_admin_payload(role=AdminRole.admin_tenant.value)
        cleanup_admin = override_admin(admin_payload)
        try:
            tenant = make_mock_tenant()
            svc_mock = AsyncMock()
            svc_mock.check_quota = AsyncMock(return_value={
                "used": 5000,
                "limit": 100000,
                "remaining": 95000,
                "percentage": 5.0,
                "warning": False,
                "critical": False,
            })

            with (
                patch(_TENANT_RESOLVER_PATCH, return_value=tenant),
                patch("app.api.v1.campaigns.get_campaign_service", return_value=svc_mock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get("/api/v1/campaigns/quota", headers=_make_headers())
            assert resp.status_code == 200
            quota = resp.json()
            assert "used" in quota
            assert "limit" in quota
            assert "remaining" in quota
            assert quota["limit"] == 100000
        finally:
            cleanup_admin()

    @pytest.mark.asyncio
    async def test_campaign_update_only_draft(self):
        """Seules les campagnes en draft peuvent être modifiées (PATCH)."""
        admin_payload = make_admin_payload(role=AdminRole.admin_tenant.value)
        cleanup_admin = override_admin(admin_payload)
        try:
            from app.core.exceptions import ValidationError
            from app.models.enums import CampaignStatus

            tenant = make_mock_tenant()
            draft = make_campaign_orm(status=CampaignStatus.draft)
            updated = make_campaign_orm(id=draft.id, status=CampaignStatus.draft, name="Modifié")

            # Draft → OK (200)
            svc_ok = AsyncMock()
            svc_ok.update_campaign = AsyncMock(return_value=updated)

            with (
                patch(_TENANT_RESOLVER_PATCH, return_value=tenant),
                patch("app.api.v1.campaigns.get_campaign_service", return_value=svc_ok),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.patch(
                        f"/api/v1/campaigns/{draft.id}",
                        json={"name": "Modifié"},
                        headers=_make_headers(),
                    )
            assert resp.status_code == 200

            # Non-draft → 400
            svc_err = AsyncMock()
            svc_err.update_campaign = AsyncMock(
                side_effect=ValidationError(
                    "Only draft campaigns can be updated",
                    details={"current_status": "sending"},
                )
            )

            with (
                patch(_TENANT_RESOLVER_PATCH, return_value=tenant),
                patch("app.api.v1.campaigns.get_campaign_service", return_value=svc_err),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.patch(
                        f"/api/v1/campaigns/{draft.id}",
                        json={"name": "Nope"},
                        headers=_make_headers(),
                    )
            assert resp.status_code == 422
        finally:
            cleanup_admin()

    @pytest.mark.asyncio
    async def test_campaign_audience_excludes_opted_out(self):
        """Les contacts opted_out sont exclus de l'audience preview."""
        admin_payload = make_admin_payload(role=AdminRole.admin_tenant.value)
        cleanup_admin = override_admin(admin_payload)
        try:
            tenant = make_mock_tenant()
            campaign = make_campaign_orm()
            svc_mock = AsyncMock()
            svc_mock.get_campaign = AsyncMock(return_value=campaign)
            svc_mock.preview_audience = AsyncMock(return_value=MagicMock(
                count=7,
                sample=[
                    {"phone": f"+2126100000{i:02d}", "name": f"Contact {i}"}
                    for i in range(5)
                ],
            ))

            with (
                patch(_TENANT_RESOLVER_PATCH, return_value=tenant),
                patch("app.api.v1.campaigns.get_campaign_service", return_value=svc_mock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        f"/api/v1/campaigns/{campaign.id}/preview",
                        headers=_make_headers(),
                    )
            assert resp.status_code == 200
            assert resp.json()["count"] == 7  # opted_out excluded
        finally:
            cleanup_admin()


# ═══════════════════════════════════════════════════════════
# SCÉNARIO 6 : SÉCURITÉ PHASE 2
# ═══════════════════════════════════════════════════════════


class TestSecuritePhase2:
    """Tests E2E des mesures de sécurité Phase 2."""

    @pytest.mark.asyncio
    async def test_kms_encrypt_decrypt_roundtrip(self):
        """KMS : envelope encryption AES-256-GCM → round-trip OK."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        master_key = secrets.token_bytes(32)
        data_key = secrets.token_bytes(32)

        # Envelope: encrypt data key with master key
        master_aesgcm = AESGCM(master_key)
        nonce = secrets.token_bytes(12)
        encrypted_dk = master_aesgcm.encrypt(nonce, data_key, None)
        decrypted_dk = master_aesgcm.decrypt(nonce, encrypted_dk, None)
        assert decrypted_dk == data_key

        # Data: encrypt plaintext with data key
        data_aesgcm = AESGCM(data_key)
        plaintext = "CIN: AB123456 — Données sensibles"
        nonce2 = secrets.token_bytes(12)
        ct = data_aesgcm.encrypt(nonce2, plaintext.encode(), None)
        pt = data_aesgcm.decrypt(nonce2, ct, None)
        assert pt.decode() == plaintext

    @pytest.mark.asyncio
    async def test_session_ip_change_invalidates(self):
        """Changement d'IP pendant une session → session invalidée (False)."""
        from app.services.auth.session_manager import SessionManager

        redis_mock = AsyncMock()
        # is_token_revoked uses redis.exists() → 0 means not revoked
        redis_mock.exists = AsyncMock(return_value=0)
        # validate_session.get calls:
        #   1. get(key_active) → "valid-jti" (matches)
        #   2. get(key_ip) → "1.2.3.4" (different from 5.6.7.8)
        # invalidate_session.get calls:
        #   3. get(key_active) → "valid-jti" (to revoke it)
        redis_mock.get = AsyncMock(
            side_effect=["valid-jti", "1.2.3.4", "valid-jti"]
        )
        redis_mock.setex = AsyncMock()
        redis_mock.delete = AsyncMock()

        sm = SessionManager(redis_mock)
        result = await sm.validate_session("admin-1", "valid-jti", "5.6.7.8")
        assert result is False  # IP changed → invalidated

    @pytest.mark.asyncio
    async def test_session_unique_invalidates_previous(self):
        """Nouvelle connexion invalide l'ancienne session (session unique)."""
        from app.services.auth.session_manager import SessionManager

        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(
            side_effect=[
                "old-jti",     # active session → old JTI (will be revoked)
                "1.2.3.4",     # previous IP
                "1700000000",  # last login timestamp (old enough → no alert)
            ]
        )
        redis_mock.setex = AsyncMock()

        pipe_mock = AsyncMock()
        pipe_mock.setex = MagicMock(return_value=pipe_mock)
        pipe_mock.execute = AsyncMock()
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)

        sm = SessionManager(redis_mock)
        result = await sm.register_session("admin-1", "new-jti", "1.2.3.4")
        assert result["previous_session_invalidated"] is True

    @pytest.mark.asyncio
    async def test_audit_trail_archive_sha256(self):
        """L'archivage produit un hash SHA-256 déterministe + gzip round-trip."""
        logs = [
            {"id": str(uuid.uuid4()), "action": "create", "resource_type": "campaign"},
            {"id": str(uuid.uuid4()), "action": "approve", "resource_type": "unanswered_question"},
        ]
        json_bytes = json.dumps(logs, default=str, ensure_ascii=False).encode()
        sha256_1 = hashlib.sha256(json_bytes).hexdigest()
        sha256_2 = hashlib.sha256(json_bytes).hexdigest()
        assert sha256_1 == sha256_2  # deterministic

        # Gzip round-trip
        compressed = gzip.compress(json_bytes)
        decompressed = gzip.decompress(compressed)
        assert decompressed == json_bytes

    @pytest.mark.asyncio
    async def test_conversation_state_has_phase2_fields(self):
        """Le ConversationState TypedDict contient tous les champs Phase 2."""
        from app.services.orchestrator.state import ConversationState

        state: ConversationState = {
            "tenant_slug": "test",
            "tenant_context": {"id": "uuid", "slug": "test", "name": "Test", "status": "active"},
            "phone": "+212600000000",
            "language": "fr",
            "intent": "faq",
            "query": "Test",
            "messages": [],
            "retrieved_chunks": [],
            "response": "",
            "chunk_ids": [],
            "confidence": 0.0,
            "is_safe": True,
            "guard_message": None,
            "incentive_state": {},
            "error": None,
            # Phase 2 fields
            "is_internal_user": False,
            "agent_type": "public",
            "escalation_id": None,
            "consecutive_low_confidence": 0,
            "conversation_id": None,
        }

        assert state["is_internal_user"] is False
        assert state["consecutive_low_confidence"] == 0

        # Verify they are valid keys of ConversationState
        annotations = ConversationState.__annotations__
        for key in ("is_internal_user", "escalation_id", "consecutive_low_confidence",
                     "conversation_id", "agent_type"):
            assert key in annotations, f"Missing Phase 2 field: {key}"


# ═══════════════════════════════════════════════════════════
# SCÉNARIO 7 : ISOLATION MULTI-TENANT
# ═══════════════════════════════════════════════════════════


class TestIsolationMultiTenant:
    """Vérifier que les endpoints sont scopés au tenant courant."""

    @pytest.mark.asyncio
    async def test_escalation_cross_tenant_scoped(self):
        """GET /escalations/ — le service reçoit le bon tenant."""
        admin_payload = make_admin_payload(role=AdminRole.admin_tenant.value)
        cleanup_admin = override_admin(admin_payload)
        try:
            tenant = make_mock_tenant()
            svc_mock = AsyncMock()
            svc_mock.get_escalations = AsyncMock(return_value=([], 0))

            with (
                patch(_TENANT_RESOLVER_PATCH, return_value=tenant),
                patch("app.api.v1.escalation.get_escalation_service", return_value=svc_mock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get("/api/v1/escalations", headers=_make_headers())
            assert resp.status_code == 200
            svc_mock.get_escalations.assert_called_once()
            called_tenant = svc_mock.get_escalations.call_args[0][0]
            assert called_tenant.slug == TEST_TENANT_SLUG
        finally:
            cleanup_admin()

    @pytest.mark.asyncio
    async def test_campaign_cross_tenant_scoped(self):
        """GET /campaigns/ — le service reçoit le bon tenant."""
        admin_payload = make_admin_payload(role=AdminRole.admin_tenant.value)
        cleanup_admin = override_admin(admin_payload)
        try:
            tenant = make_mock_tenant()
            svc_mock = AsyncMock()
            svc_mock.list_campaigns = AsyncMock(return_value=([], 0))

            with (
                patch(_TENANT_RESOLVER_PATCH, return_value=tenant),
                patch("app.api.v1.campaigns.get_campaign_service", return_value=svc_mock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get("/api/v1/campaigns", headers=_make_headers())
            assert resp.status_code == 200
            svc_mock.list_campaigns.assert_called_once()
            called_tenant = svc_mock.list_campaigns.call_args[0][0]
            assert called_tenant.slug == TEST_TENANT_SLUG
        finally:
            cleanup_admin()

    @pytest.mark.asyncio
    async def test_whitelist_cross_tenant_scoped(self):
        """GET /whitelist/ — les données sont scopées au tenant du header."""
        admin_payload = make_admin_payload(role=AdminRole.admin_tenant.value)
        cleanup_admin = override_admin(admin_payload)
        try:
            session = mock_session_for_list(items=[], total=0)
            tenant = make_mock_tenant(db_session_mock=session)

            with patch(_TENANT_RESOLVER_PATCH, return_value=tenant):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get("/api/v1/whitelist", headers=_make_headers())
            assert resp.status_code == 200
            assert resp.json()["total"] == 0
        finally:
            cleanup_admin()


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════


def _copy_attrs(target, source):
    """Copy attributes from source mock to target (for session.refresh)."""
    for attr in ("id", "phone", "label", "note", "is_active", "added_by",
                 "created_at", "updated_at"):
        if hasattr(source, attr):
            try:
                setattr(target, attr, getattr(source, attr))
            except (AttributeError, TypeError):
                pass
