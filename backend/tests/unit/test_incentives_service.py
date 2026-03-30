"""Unit tests for IncentivesService — localization, button limits, item formatting."""

from unittest.mock import AsyncMock, MagicMock

from app.services.incitations.service import (
    MAX_BUTTON_TITLE_LENGTH,
    MAX_BUTTONS,
    IncentivesService,
)


def _make_category(name_fr="Cat FR", name_ar=None, name_en="Cat EN", cat_id="cat-1"):
    """Create a mock IncentiveCategory ORM object."""
    cat = MagicMock()
    cat.id = cat_id
    cat.name_fr = name_fr
    cat.name_ar = name_ar
    cat.name_en = name_en
    cat.is_leaf = False
    cat.is_active = True
    cat.order_index = 0
    return cat


def _make_item(
    title_fr="Item FR",
    title_ar=None,
    description_fr="Description FR",
    conditions="Condition 1",
    legal_reference="Loi 47-18",
    documents_required=None,
):
    """Create a mock IncentiveItem ORM object."""
    item = MagicMock()
    item.id = "item-1"
    item.title_fr = title_fr
    item.title_ar = title_ar
    item.title_en = "Item EN"
    item.description_fr = description_fr
    item.description_ar = None
    item.description_en = "Description EN"
    item.conditions = conditions
    item.legal_reference = legal_reference
    item.eligibility_criteria = None
    item.documents_required = documents_required or ["CIN", "RC"]
    return item


class TestLocalizedName:
    """_get_localized_name() language fallback."""

    def test_french_name_returned(self):
        """language='fr' returns name_fr."""
        sender = AsyncMock()
        service = IncentivesService(sender=sender)
        cat = _make_category(name_fr="Investissement")

        result = service._get_localized_name(cat, "fr")
        assert result == "Investissement"

    def test_arabic_fallback_to_french(self):
        """name_ar=None falls back to name_fr."""
        sender = AsyncMock()
        service = IncentivesService(sender=sender)
        cat = _make_category(name_fr="Investissement", name_ar=None)

        result = service._get_localized_name(cat, "ar")
        assert result == "Investissement"


class TestButtonTitleTruncation:
    """Button titles respect MAX_BUTTON_TITLE_LENGTH."""

    def test_long_title_truncated(self):
        """50-char title is truncated to MAX_BUTTON_TITLE_LENGTH."""
        sender = AsyncMock()
        service = IncentivesService(sender=sender)
        cat = _make_category(name_fr="A" * 50)
        buttons = service._categories_to_buttons([cat], "fr")

        assert len(buttons[0]["title"]) <= MAX_BUTTON_TITLE_LENGTH


class TestCategoriesToButtons:
    """_categories_to_buttons caps at MAX_BUTTONS."""

    def test_five_categories_capped_at_max(self):
        """5 categories produce at most MAX_BUTTONS buttons."""
        sender = AsyncMock()
        service = IncentivesService(sender=sender)
        cats = [_make_category(name_fr=f"Cat {i}", cat_id=f"c-{i}") for i in range(5)]

        buttons = service._categories_to_buttons(cats, "fr")
        assert len(buttons) <= MAX_BUTTONS


class TestFormatItemDetail:
    """_format_item_detail renders complete item fiches."""

    def test_complete_item_formatted(self):
        """All fields rendered: title, description, legal_reference, conditions."""
        sender = AsyncMock()
        service = IncentivesService(sender=sender)
        item = _make_item()

        text = service._format_item_detail(item, "fr")

        assert "Item FR" in text
        assert "Description FR" in text
        assert "Loi 47-18" in text
        assert "Condition 1" in text
