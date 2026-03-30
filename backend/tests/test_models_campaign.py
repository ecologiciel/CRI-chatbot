"""Tests for Campaign and CampaignRecipient models, enums, and schemas."""

import pytest


# 1. Import des modèles sans erreur
def test_campaign_models_import():
    from app.models.campaign import Campaign, CampaignRecipient

    assert Campaign.__tablename__ == "campaigns"
    assert CampaignRecipient.__tablename__ == "campaign_recipients"


# 2. Import des enums sans erreur
def test_campaign_enums_import():
    from app.models.enums import CampaignStatus, RecipientStatus

    assert len(CampaignStatus) == 6  # draft, scheduled, sending, paused, completed, failed
    assert len(RecipientStatus) == 5  # pending, sent, delivered, read, failed


# 3. Import des schemas sans erreur
def test_campaign_schemas_import():
    from app.schemas.campaign import (
        AudiencePreview,
        CampaignCreate,
        CampaignList,
        CampaignRead,
        CampaignSchedule,
        CampaignStats,
        RecipientList,
        RecipientRead,
    )

    assert CampaignCreate is not None
    assert CampaignRead is not None
    assert CampaignList is not None
    assert CampaignSchedule is not None
    assert RecipientRead is not None
    assert RecipientList is not None
    assert CampaignStats is not None
    assert AudiencePreview is not None


# 4. Validation CampaignCreate
def test_campaign_create_valid():
    from app.schemas.campaign import CampaignCreate

    c = CampaignCreate(
        name="Campagne Q2 2026",
        template_id="welcome_fr_001",
        template_name="Bienvenue Investisseur",
        audience_filter={"tags": ["investisseur_actif"]},
        variable_mapping={"1": "contact.name"},
    )
    assert c.name == "Campagne Q2 2026"
    assert c.template_language == "fr"
    assert c.variable_mapping == {"1": "contact.name"}


# 5. Validation CampaignCreate rejette audience_filter vide
def test_campaign_create_empty_audience():
    from app.schemas.campaign import CampaignCreate

    with pytest.raises(ValueError):
        CampaignCreate(
            name="Test",
            template_id="t1",
            template_name="T1",
            audience_filter={},
            variable_mapping={},
        )


# 6. Validation CampaignCreate rejette nom vide
def test_campaign_create_empty_name():
    from app.schemas.campaign import CampaignCreate

    with pytest.raises(ValueError):
        CampaignCreate(
            name="",
            template_id="t1",
            template_name="T1",
            audience_filter={"tags": ["all"]},
            variable_mapping={},
        )


# 7. Stats par défaut
def test_campaign_stats_schema():
    from app.schemas.campaign import CampaignStats

    s = CampaignStats(
        total=100,
        sent=80,
        delivered=70,
        read=50,
        failed=5,
        pending=15,
    )
    assert s.total == 100
    assert s.sent == 80
    assert s.delivery_rate is None or isinstance(s.delivery_rate, float)
    assert s.read_rate is None or isinstance(s.read_rate, float)


# 8. CampaignStatus values
def test_campaign_status_lifecycle():
    from app.models.enums import CampaignStatus

    assert CampaignStatus.draft.value == "draft"
    assert CampaignStatus.paused.value == "paused"
    assert CampaignStatus.failed.value == "failed"
    # Ensure cancelled is no longer present
    assert not hasattr(CampaignStatus, "cancelled")
