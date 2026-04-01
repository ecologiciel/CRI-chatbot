"""Unit tests for NotificationService — decision matrix, opt-in, dedup, send.

All external I/O (DB, Redis, WhatsApp) is mocked.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import DossierStatut, Language, OptInStatus
from app.services.notification.service import (
    DossierChangeEvent,
    NotificationDecision,
    NotificationEventType,
    NotificationPriority,
    NotificationService,
    get_notification_service,
)


# ── Helpers ──────────────────────────────────────────────────────


def _make_service(
    sender: AsyncMock | None = None,
    audit: AsyncMock | None = None,
) -> NotificationService:
    """Create a NotificationService with mocked dependencies."""
    return NotificationService(
        sender=sender or AsyncMock(),
        audit=audit or AsyncMock(),
    )


def _make_contact(**overrides) -> MagicMock:
    """Create a mock Contact ORM object."""
    defaults = {
        "id": uuid.uuid4(),
        "phone": "+212612345678",
        "name": "Ahmed Benali",
        "language": Language.fr,
        "opt_in_status": OptInStatus.pending,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_event(**overrides) -> DossierChangeEvent:
    """Create a DossierChangeEvent with defaults."""
    defaults = {
        "dossier_id": str(uuid.uuid4()),
        "numero": "2024-CRI-0001",
        "contact_id": str(uuid.uuid4()),
        "old_statut": "en_attente",
        "new_statut": "valide",
        "sync_log_id": str(uuid.uuid4()),
        "timestamp": "2026-04-01T10:00:00",
    }
    defaults.update(overrides)
    return DossierChangeEvent(**defaults)


def _make_tenant(slug: str = "rabat") -> MagicMock:
    """Create a mock TenantContext."""
    tenant = MagicMock()
    tenant.slug = slug
    tenant.id = uuid.uuid4()
    tenant.name = "CRI Rabat"
    tenant.status = "active"
    return tenant


# =====================================================================
# TestShouldNotify — pure logic, no I/O
# =====================================================================


class TestShouldNotify:
    """Test the status-change decision matrix."""

    def setup_method(self) -> None:
        self.service = _make_service()

    def test_to_valide_is_decision_finale_high(self) -> None:
        """Any status → validé = decision_finale, high priority."""
        decision = self.service.should_notify("en_attente", "valide")
        assert decision.should_send is True
        assert decision.event_type == NotificationEventType.decision_finale
        assert decision.priority == NotificationPriority.high
        assert decision.template_name == "dossier_decision_finale"

    def test_to_rejete_is_decision_finale_high(self) -> None:
        """Any status → rejeté = decision_finale, high priority."""
        decision = self.service.should_notify("en_cours", "rejete")
        assert decision.should_send is True
        assert decision.event_type == NotificationEventType.decision_finale
        assert decision.priority == NotificationPriority.high

    def test_same_status_skips(self) -> None:
        """Same status → no notification."""
        decision = self.service.should_notify("en_cours", "en_cours")
        assert decision.should_send is False
        assert decision.reason == "same_status"

    def test_to_complement_is_complement_request(self) -> None:
        """Any status → complement = complement_request."""
        decision = self.service.should_notify("en_cours", "complement")
        assert decision.should_send is True
        assert decision.event_type == NotificationEventType.complement_request
        assert decision.priority == NotificationPriority.high

    def test_en_attente_to_incomplet_is_complement_request(self) -> None:
        """en_attente → incomplet = complement_request (special case)."""
        decision = self.service.should_notify("en_attente", "incomplet")
        assert decision.should_send is True
        assert decision.event_type == NotificationEventType.complement_request

    def test_incomplet_to_en_cours_is_status_update(self) -> None:
        """incomplet → en_cours = status_update, medium."""
        decision = self.service.should_notify("incomplet", "en_cours")
        assert decision.should_send is True
        assert decision.event_type == NotificationEventType.status_update
        assert decision.priority == NotificationPriority.medium

    def test_en_attente_to_en_cours_is_status_update(self) -> None:
        """en_attente → en_cours = status_update, medium."""
        decision = self.service.should_notify("en_attente", "en_cours")
        assert decision.should_send is True
        assert decision.event_type == NotificationEventType.status_update

    def test_other_to_incomplet_is_dossier_incomplet(self) -> None:
        """en_cours → incomplet = dossier_incomplet, low."""
        decision = self.service.should_notify("en_cours", "incomplet")
        assert decision.should_send is True
        assert decision.event_type == NotificationEventType.dossier_incomplet
        assert decision.priority == NotificationPriority.low

    def test_en_cours_to_en_attente_no_notification(self) -> None:
        """en_cours → en_attente = no notification (not actionable)."""
        decision = self.service.should_notify("en_cours", "en_attente")
        assert decision.should_send is False


# =====================================================================
# TestTemplates — mapping and component building
# =====================================================================


class TestTemplates:
    """Test template mapping and component building."""

    def setup_method(self) -> None:
        self.service = _make_service()

    def test_all_event_types_have_templates(self) -> None:
        """Every NotificationEventType has a template mapping."""
        for event_type in NotificationEventType:
            template = self.service.get_template_name(event_type)
            assert template is not None
            assert len(template) > 0

    def test_build_template_components_structure(self) -> None:
        """Components follow Meta Cloud API format."""
        components = self.service.build_template_components(
            contact_name="Ahmed Benali",
            dossier_numero="2024-CRI-0001",
            event_type=NotificationEventType.decision_finale,
            language_code="fr",
        )
        assert len(components) == 1
        assert components[0]["type"] == "body"
        params = components[0]["parameters"]
        assert len(params) == 4
        assert params[0] == {"type": "text", "text": "Ahmed Benali"}
        assert params[1] == {"type": "text", "text": "2024-CRI-0001"}
        # params[2] is status label, params[3] is date
        assert params[2]["type"] == "text"
        assert params[3]["type"] == "text"

    def test_build_template_fallback_name(self) -> None:
        """None contact name falls back to 'Investisseur'."""
        components = self.service.build_template_components(
            contact_name=None,
            dossier_numero="2024-001",
            event_type=NotificationEventType.status_update,
            language_code="fr",
        )
        assert components[0]["parameters"][0]["text"] == "Investisseur"

    def test_build_template_arabic(self) -> None:
        """Arabic language produces Arabic labels and date format."""
        components = self.service.build_template_components(
            contact_name="أحمد",
            dossier_numero="2024-001",
            event_type=NotificationEventType.complement_request,
            language_code="ar",
        )
        params = components[0]["parameters"]
        assert params[0]["text"] == "أحمد"
        # Arabic date format YYYY/MM/DD
        assert "/" in params[3]["text"]


# =====================================================================
# TestOptIn — DB-backed opt-in check
# =====================================================================


class TestOptIn:
    """Test opt-in verification."""

    @pytest.mark.asyncio
    async def test_opted_out_returns_false(self) -> None:
        """Contact with opted_out status → cannot receive notifications."""
        service = _make_service()
        contact = _make_contact(opt_in_status=OptInStatus.opted_out)
        tenant = _make_tenant()

        with patch.object(service, "_load_contact", return_value=contact):
            result = await service.check_opt_in(contact.id, tenant)
        assert result is False

    @pytest.mark.asyncio
    async def test_opted_in_returns_true(self) -> None:
        """Contact with opted_in status → can receive notifications."""
        service = _make_service()
        contact = _make_contact(opt_in_status=OptInStatus.opted_in)
        tenant = _make_tenant()

        with patch.object(service, "_load_contact", return_value=contact):
            result = await service.check_opt_in(contact.id, tenant)
        assert result is True

    @pytest.mark.asyncio
    async def test_pending_returns_true(self) -> None:
        """Contact with pending status → treated as opt-in."""
        service = _make_service()
        contact = _make_contact(opt_in_status=OptInStatus.pending)
        tenant = _make_tenant()

        with patch.object(service, "_load_contact", return_value=contact):
            result = await service.check_opt_in(contact.id, tenant)
        assert result is True

    @pytest.mark.asyncio
    async def test_contact_not_found_returns_false(self) -> None:
        """Non-existent contact → cannot receive notifications."""
        service = _make_service()
        tenant = _make_tenant()

        with patch.object(service, "_load_contact", return_value=None):
            result = await service.check_opt_in(uuid.uuid4(), tenant)
        assert result is False


# =====================================================================
# TestDeduplication — Redis-backed 24h dedup
# =====================================================================


class TestDeduplication:
    """Test 24h deduplication via Redis."""

    @pytest.mark.asyncio
    async def test_first_notification_allowed(self) -> None:
        """First notification for a contact/event/dossier → not duplicate."""
        service = _make_service()
        tenant = _make_tenant()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # NX succeeded

        with patch("app.services.notification.service.get_redis", return_value=mock_redis):
            is_dup = await service.is_duplicate("contact-1", "decision_finale", "dossier-1", tenant)

        assert is_dup is False
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "rabat:notif:dedup:contact-1:decision_finale:dossier-1"
        assert call_args[1]["ex"] == 86_400
        assert call_args[1]["nx"] is True

    @pytest.mark.asyncio
    async def test_second_notification_blocked(self) -> None:
        """Second notification within 24h → duplicate blocked."""
        service = _make_service()
        tenant = _make_tenant()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)  # NX failed (key exists)

        with patch("app.services.notification.service.get_redis", return_value=mock_redis):
            is_dup = await service.is_duplicate("contact-1", "decision_finale", "dossier-1", tenant)

        assert is_dup is True


# =====================================================================
# TestSendNotification — full orchestration
# =====================================================================


class TestSendNotification:
    """Test the end-to-end send_notification orchestrator."""

    @pytest.mark.asyncio
    async def test_happy_path_sends_template(self) -> None:
        """Full flow: contact exists, opted in, not dup → sends WhatsApp."""
        sender = AsyncMock()
        sender.send_template = AsyncMock(return_value="wamid.123")
        audit = AsyncMock()
        service = _make_service(sender=sender, audit=audit)

        contact = _make_contact(opt_in_status=OptInStatus.opted_in)
        tenant = _make_tenant()
        event = _make_event(
            contact_id=str(contact.id),
            old_statut="en_attente",
            new_statut="valide",
        )

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # NX: not duplicate

        with (
            patch.object(service, "_load_contact", return_value=contact),
            patch("app.services.notification.service.get_redis", return_value=mock_redis),
        ):
            result = await service.send_notification(event, tenant)

        assert result["status"] == "sent"
        assert result["wamid"] == "wamid.123"
        sender.send_template.assert_called_once()
        # Verify audit was called with notification_sent
        audit.log_action.assert_called()

    @pytest.mark.asyncio
    async def test_no_contact_id_skips(self) -> None:
        """Event without contact_id → skip."""
        audit = AsyncMock()
        service = _make_service(audit=audit)
        tenant = _make_tenant()
        event = _make_event(contact_id=None, new_statut="valide")

        result = await service.send_notification(event, tenant)
        assert result["status"] == "skipped"
        assert result["reason"] == "no_contact_id"

    @pytest.mark.asyncio
    async def test_opted_out_skips(self) -> None:
        """Contact opted out → skip with audit."""
        audit = AsyncMock()
        service = _make_service(audit=audit)
        contact = _make_contact(opt_in_status=OptInStatus.opted_out)
        tenant = _make_tenant()
        event = _make_event(contact_id=str(contact.id), new_statut="valide")

        with patch.object(service, "_load_contact", return_value=contact):
            result = await service.send_notification(event, tenant)

        assert result["status"] == "skipped"
        assert result["reason"] == "opted_out"

    @pytest.mark.asyncio
    async def test_duplicate_skips(self) -> None:
        """Duplicate within 24h → skip."""
        service = _make_service()
        contact = _make_contact(opt_in_status=OptInStatus.opted_in)
        tenant = _make_tenant()
        event = _make_event(contact_id=str(contact.id), new_statut="valide")

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)  # Already exists

        with (
            patch.object(service, "_load_contact", return_value=contact),
            patch("app.services.notification.service.get_redis", return_value=mock_redis),
        ):
            result = await service.send_notification(event, tenant)

        assert result["status"] == "skipped"
        assert result["reason"] == "deduplicated"

    @pytest.mark.asyncio
    async def test_whatsapp_failure_returns_failed(self) -> None:
        """WhatsApp send error → returns failed, audits error."""
        sender = AsyncMock()
        sender.send_template = AsyncMock(side_effect=Exception("API timeout"))
        audit = AsyncMock()
        service = _make_service(sender=sender, audit=audit)

        contact = _make_contact(opt_in_status=OptInStatus.opted_in)
        tenant = _make_tenant()
        event = _make_event(contact_id=str(contact.id), new_statut="valide")

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with (
            patch.object(service, "_load_contact", return_value=contact),
            patch("app.services.notification.service.get_redis", return_value=mock_redis),
        ):
            result = await service.send_notification(event, tenant)

        assert result["status"] == "failed"
        # Audit should log the failure
        audit.log_action.assert_called()

    @pytest.mark.asyncio
    async def test_same_status_skips_early(self) -> None:
        """Same old/new status → skip without loading contact."""
        service = _make_service()
        tenant = _make_tenant()
        event = _make_event(old_statut="en_cours", new_statut="en_cours")

        result = await service.send_notification(event, tenant)
        assert result["status"] == "skipped"
        assert result["reason"] == "same_status"

    @pytest.mark.asyncio
    async def test_contact_not_found_skips(self) -> None:
        """Contact ID present but not in DB → skip."""
        service = _make_service()
        tenant = _make_tenant()
        event = _make_event(new_statut="valide")

        with patch.object(service, "_load_contact", return_value=None):
            result = await service.send_notification(event, tenant)

        assert result["status"] == "skipped"
        assert result["reason"] == "contact_not_found"

    @pytest.mark.asyncio
    async def test_no_phone_skips(self) -> None:
        """Contact exists but has no phone → skip."""
        service = _make_service()
        contact = _make_contact(phone=None, opt_in_status=OptInStatus.opted_in)
        tenant = _make_tenant()
        event = _make_event(contact_id=str(contact.id), new_statut="valide")

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with (
            patch.object(service, "_load_contact", return_value=contact),
            patch("app.services.notification.service.get_redis", return_value=mock_redis),
        ):
            result = await service.send_notification(event, tenant)

        assert result["status"] == "skipped"
        assert result["reason"] == "no_phone"


# =====================================================================
# TestImports — verify module importability
# =====================================================================


class TestImports:
    """Verify all notification modules are importable."""

    def test_service_import(self) -> None:
        from app.services.notification.service import NotificationService
        assert NotificationService is not None

    def test_package_import(self) -> None:
        from app.services.notification import NotificationService, get_notification_service
        assert NotificationService is not None
        assert get_notification_service is not None

    def test_worker_import(self) -> None:
        from app.workers.notification import (
            WorkerSettings,
            process_all_notifications,
            task_send_notifications,
        )
        assert task_send_notifications is not None
        assert process_all_notifications is not None
        assert WorkerSettings is not None

    def test_event_type_enum(self) -> None:
        assert len(NotificationEventType) == 4
        assert NotificationEventType.decision_finale.value == "decision_finale"

    def test_change_event_model(self) -> None:
        event = DossierChangeEvent(
            dossier_id="abc",
            numero="2024-001",
            old_statut="en_attente",
            new_statut="valide",
        )
        assert event.contact_id is None  # optional
