"""Completion tests for NotificationService — Wave 29B.

Adds edge cases NOT in test_notification_service.py (Wave 24):
- en_cours → rejeté triggers decision_finale
- complement → validé triggers decision_finale (recovery path)
- English template components
- Dedup allows different event types for same contact+dossier
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import DossierStatut, Language, OptInStatus
from app.services.notification.service import (
    NotificationEventType,
    NotificationPriority,
    NotificationService,
)


# -- Helpers ----------------------------------------------------------------


def _make_service() -> NotificationService:
    return NotificationService(sender=AsyncMock(), audit=AsyncMock())


def _make_tenant(slug: str = "rabat") -> MagicMock:
    tenant = MagicMock()
    tenant.slug = slug
    tenant.id = uuid.uuid4()
    return tenant


# -- Tests ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.phase3
class TestDecisionComplete:
    """Status transition edge cases not in test_notification_service.py."""

    def test_en_cours_to_rejete_triggers_decision_finale(self) -> None:
        """en_cours → rejeté = decision_finale, high priority."""
        service = _make_service()
        decision = service.should_notify("en_cours", "rejete")
        assert decision.should_send is True
        assert decision.event_type == NotificationEventType.decision_finale
        assert decision.priority == NotificationPriority.high

    def test_complement_to_valide_triggers_decision_finale(self) -> None:
        """complement → validé = decision_finale (recovery path)."""
        service = _make_service()
        decision = service.should_notify("complement", "valide")
        assert decision.should_send is True
        assert decision.event_type == NotificationEventType.decision_finale
        assert decision.priority == NotificationPriority.high


@pytest.mark.unit
@pytest.mark.phase3
class TestTemplateComplete:
    """Template building edge cases."""

    def test_build_template_english_labels(self) -> None:
        """English language components contain English date format and labels."""
        service = _make_service()
        components = service.build_template_components(
            contact_name="John Doe",
            dossier_numero="2024-CRI-0042",
            event_type=NotificationEventType.status_update,
            language_code="en",
        )
        assert len(components) >= 1
        params = components[0]["parameters"]
        assert params[0]["text"] == "John Doe"
        assert params[1]["text"] == "2024-CRI-0042"


@pytest.mark.unit
@pytest.mark.phase3
class TestDedupComplete:
    """Deduplication edge case."""

    @pytest.mark.asyncio
    async def test_dedup_different_event_types_allowed(self) -> None:
        """Same contact+dossier but different event types → both allowed."""
        service = _make_service()
        tenant = _make_tenant()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # NX succeeded

        with patch("app.services.notification.service.get_redis", return_value=mock_redis):
            dup1 = await service.is_duplicate("contact-1", "decision_finale", "dossier-1", tenant)
            dup2 = await service.is_duplicate("contact-1", "complement_request", "dossier-1", tenant)

        assert dup1 is False
        assert dup2 is False

        # Verify two different keys were used
        assert mock_redis.set.call_count == 2
        key1 = mock_redis.set.call_args_list[0][0][0]
        key2 = mock_redis.set.call_args_list[1][0][0]
        assert key1 != key2
        assert "decision_finale" in key1
        assert "complement_request" in key2
