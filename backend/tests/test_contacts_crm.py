"""Tests for Wave 17 — Contacts CRM enrichment.

Covers: schemas validation, segmentation service, STOP command,
batch tags, opt-in change, contact history, filtered export.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.models.enums import (
    AgentType,
    ConversationStatus,
    OptInStatus,
    RecipientStatus,
)

# ---------------------------------------------------------------------------
# 1. Import smoke tests
# ---------------------------------------------------------------------------


def test_imports_schemas():
    from app.schemas.contacts_extended import (
        ContactHistory,
        SegmentInfo,
        TagsBatchUpdate,
    )

    assert TagsBatchUpdate is not None
    assert ContactHistory is not None
    assert SegmentInfo is not None


def test_imports_segmentation():
    from app.services.contact.segmentation import (
        SegmentationService,
        get_segmentation_service,
    )

    assert SegmentationService is not None
    assert get_segmentation_service is not None


# ---------------------------------------------------------------------------
# 2. Schema validation
# ---------------------------------------------------------------------------


def test_tags_batch_requires_operations():
    """Empty add_tags AND remove_tags should fail validation."""
    from app.schemas.contacts_extended import TagsBatchUpdate

    with pytest.raises(ValueError, match="Must specify add_tags or remove_tags"):
        TagsBatchUpdate(
            contact_ids=[uuid.uuid4()],
            add_tags=[],
            remove_tags=[],
        )


def test_tags_batch_requires_contacts():
    """Empty contact_ids should fail validation."""
    from app.schemas.contacts_extended import TagsBatchUpdate

    with pytest.raises(ValueError):
        TagsBatchUpdate(contact_ids=[], add_tags=["test"])


def test_tags_batch_valid():
    """Valid TagsBatchUpdate should pass."""
    from app.schemas.contacts_extended import TagsBatchUpdate

    batch = TagsBatchUpdate(
        contact_ids=[uuid.uuid4(), uuid.uuid4()],
        add_tags=["vip"],
        remove_tags=["inactive"],
    )
    assert len(batch.contact_ids) == 2
    assert batch.add_tags == ["vip"]


def test_opt_in_change_request_valid():
    from app.schemas.contacts_extended import OptInChangeRequest

    req = OptInChangeRequest(
        new_status=OptInStatus.opted_out,
        reason="Demande utilisateur",
    )
    assert req.new_status == OptInStatus.opted_out
    assert len(req.reason) > 0


def test_opt_in_change_request_empty_reason():
    from app.schemas.contacts_extended import OptInChangeRequest

    with pytest.raises(ValueError):
        OptInChangeRequest(
            new_status=OptInStatus.opted_out,
            reason="",
        )


def test_segment_info_schema():
    from app.schemas.contacts_extended import SegmentInfo

    seg = SegmentInfo(
        key="opted_in",
        label_fr="Opt-in actif",
        label_en="Opted in",
        description_fr="Contacts actifs",
        count=42,
    )
    assert seg.count == 42


def test_conversation_summary_schema():
    from app.schemas.contacts_extended import ConversationSummary

    s = ConversationSummary(
        id=uuid.uuid4(),
        status=ConversationStatus.active,
        agent_type=AgentType.public,
        message_count=5,
        started_at=datetime.now(UTC),
    )
    assert s.message_count == 5


def test_campaign_participation_schema():
    from app.schemas.contacts_extended import CampaignParticipation

    p = CampaignParticipation(
        campaign_id=uuid.uuid4(),
        campaign_name="Rentrée 2026",
        status=RecipientStatus.delivered,
        sent_at=datetime.now(UTC),
    )
    assert p.status == RecipientStatus.delivered


def test_contact_history_schema():
    from app.schemas.contacts_extended import ContactHistory

    h = ContactHistory(
        contact_id=uuid.uuid4(),
        conversations=[],
        campaigns=[],
        total_conversations=0,
        total_campaigns=0,
    )
    assert h.total_conversations == 0


# ---------------------------------------------------------------------------
# 3. Segmentation — STOP command
# ---------------------------------------------------------------------------


class TestStopCommand:
    """Test the is_stop_command static method."""

    def test_exact_stop(self):
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("STOP") is True

    def test_lowercase(self):
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("stop") is True

    def test_with_whitespace(self):
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("  stop  ") is True

    def test_french_variants(self):
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("arrêter") is True
        assert SegmentationService.is_stop_command("DESABONNER") is True
        assert SegmentationService.is_stop_command("désabonner") is True

    def test_unsubscribe(self):
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("unsubscribe") is True

    def test_not_substring(self):
        """'STOP talking' must NOT trigger opt-out."""
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("STOP talking") is False

    def test_normal_message(self):
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("Bonjour") is False
        assert SegmentationService.is_stop_command("Mon dossier") is False

    def test_empty_string(self):
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("") is False

    # --- Arabe (Art. 9 loi 09-08) ---

    def test_arabic_tawaquf(self):
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("توقف") is True

    def test_arabic_ilghaa(self):
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("إلغاء") is True

    def test_arabic_waqf(self):
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("وقف") is True

    def test_arabic_iqaf(self):
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("ايقاف") is True

    def test_arabic_alghaa_variant(self):
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("الغاء") is True

    def test_arabic_with_spaces(self):
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("  توقف  ") is True

    def test_arabic_sentence_not_optout(self):
        """An Arabic sentence must NOT trigger opt-out."""
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("أريد متابعة ملفي") is False


# ---------------------------------------------------------------------------
# 4. Segmentation — predefined segments
# ---------------------------------------------------------------------------


def test_segment_keys_exist():
    """All documented segment keys must be defined."""
    from app.services.contact.segmentation import SEGMENTS

    expected = {
        "opted_in",
        "opted_out",
        "pending",
        "from_whatsapp",
        "from_import",
        "from_manual",
        "has_cin",
        "no_cin",
        "new_30d",
        "inactive_90d",
    }
    assert set(SEGMENTS.keys()) == expected


def test_segment_defs_have_labels():
    """Each segment must have both French and English labels."""
    from app.services.contact.segmentation import SEGMENTS

    for key, seg_def in SEGMENTS.items():
        assert seg_def.label_fr, f"Segment {key} missing label_fr"
        assert seg_def.label_en, f"Segment {key} missing label_en"
        assert seg_def.description_fr, f"Segment {key} missing description_fr"


def test_segment_filter_fn_returns_select():
    """Each segment's filter_fn must return a SQLAlchemy Select."""
    from sqlalchemy import Select

    from app.services.contact.segmentation import SEGMENTS

    for key, seg_def in SEGMENTS.items():
        result = seg_def.filter_fn()
        assert isinstance(result, Select), f"Segment {key} filter_fn did not return Select"


# ---------------------------------------------------------------------------
# 5. Import/Export filter builder
# ---------------------------------------------------------------------------


def test_build_filtered_query_no_filters():
    """With no filters, query should select all contacts."""
    from app.services.contact.import_export import ContactImportExportService

    query = ContactImportExportService._build_filtered_query()
    # Should be a valid Select — compile check
    assert str(query).startswith("SELECT")


def test_build_filtered_query_with_search():
    """Search filter should add ILIKE clauses."""
    from app.services.contact.import_export import ContactImportExportService

    query = ContactImportExportService._build_filtered_query(search="test")
    compiled = str(query)
    assert "LIKE" in compiled.upper()


def test_build_filtered_query_with_status():
    """Status filter should add WHERE clause."""
    from app.services.contact.import_export import ContactImportExportService

    query = ContactImportExportService._build_filtered_query(
        opt_in_status=OptInStatus.opted_out,
    )
    compiled = str(query)
    assert "opt_in_status" in compiled


def test_build_filtered_query_with_dates():
    """Date filters should add WHERE clauses."""
    from datetime import datetime

    from app.services.contact.import_export import ContactImportExportService

    query = ContactImportExportService._build_filtered_query(
        created_after=datetime(2025, 1, 1, tzinfo=UTC),
        created_before=datetime(2025, 12, 31, tzinfo=UTC),
    )
    compiled = str(query)
    assert "created_at" in compiled
