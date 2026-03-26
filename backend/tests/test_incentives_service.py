"""Tests for IncentivesService — tree navigation and WhatsApp formatting."""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from app.core.tenant import TenantContext
from app.services.incitations.service import (
    MAX_BUTTON_TITLE_LENGTH,
    MAX_BUTTONS,
    IncentivesService,
)


# --- Fixtures ---

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)


def _make_category(
    name_fr="Catégorie Test",
    name_ar=None,
    name_en=None,
    description_fr=None,
    description_ar=None,
    description_en=None,
    parent_id=None,
    is_leaf=False,
    order_index=0,
    is_active=True,
    icon=None,
) -> MagicMock:
    """Create a mock IncentiveCategory."""
    cat = MagicMock()
    cat.id = uuid.uuid4()
    cat.name_fr = name_fr
    cat.name_ar = name_ar
    cat.name_en = name_en
    cat.description_fr = description_fr
    cat.description_ar = description_ar
    cat.description_en = description_en
    cat.parent_id = parent_id
    cat.is_leaf = is_leaf
    cat.order_index = order_index
    cat.is_active = is_active
    cat.icon = icon
    return cat


def _make_item(
    title_fr="Incitation Test",
    title_ar=None,
    title_en=None,
    description_fr="Description test",
    description_ar=None,
    description_en=None,
    conditions="Condition A",
    legal_reference="Loi n° 1-23",
    eligibility_criteria=None,
    documents_required=None,
    order_index=0,
    is_active=True,
    category_id=None,
) -> MagicMock:
    """Create a mock IncentiveItem."""
    item = MagicMock()
    item.id = uuid.uuid4()
    item.title_fr = title_fr
    item.title_ar = title_ar
    item.title_en = title_en
    item.description_fr = description_fr
    item.description_ar = description_ar
    item.description_en = description_en
    item.conditions = conditions
    item.legal_reference = legal_reference
    item.eligibility_criteria = eligibility_criteria or {}
    item.documents_required = documents_required if documents_required is not None else ["CIN", "Statuts"]
    item.order_index = order_index
    item.is_active = is_active
    item.category_id = category_id or uuid.uuid4()
    return item


@pytest.fixture
def mock_sender():
    """Mock WhatsAppSenderService."""
    sender = AsyncMock()
    sender.send_text = AsyncMock(return_value="wamid.test")
    sender.send_buttons = AsyncMock(return_value="wamid.test")
    sender.send_list = AsyncMock(return_value="wamid.test")
    return sender


@pytest.fixture
def service(mock_sender):
    """IncentivesService with mocked sender."""
    return IncentivesService(sender=mock_sender)


# --- Localization tests ---


class TestLocalization:
    """Test localized name/title/description resolution."""

    def test_localized_name_french(self, service):
        cat = _make_category(name_fr="Industrie", name_ar="صناعة", name_en="Industry")
        assert service._get_localized_name(cat, "fr") == "Industrie"

    def test_localized_name_arabic(self, service):
        cat = _make_category(name_fr="Industrie", name_ar="صناعة", name_en="Industry")
        assert service._get_localized_name(cat, "ar") == "صناعة"

    def test_localized_name_english(self, service):
        cat = _make_category(name_fr="Industrie", name_ar="صناعة", name_en="Industry")
        assert service._get_localized_name(cat, "en") == "Industry"

    def test_localized_name_arabic_fallback_to_french(self, service):
        """If name_ar is None, fall back to name_fr."""
        cat = _make_category(name_fr="Industrie", name_ar=None)
        assert service._get_localized_name(cat, "ar") == "Industrie"

    def test_localized_title_french(self, service):
        item = _make_item(title_fr="Exonération TVA", title_en="VAT Exemption")
        assert service._get_localized_title(item, "fr") == "Exonération TVA"

    def test_localized_title_english(self, service):
        item = _make_item(title_fr="Exonération TVA", title_en="VAT Exemption")
        assert service._get_localized_title(item, "en") == "VAT Exemption"

    def test_localized_description_fallback(self, service):
        cat = _make_category(description_fr="Desc FR", description_en=None)
        assert service._get_localized_description(cat, "en") == "Desc FR"


# --- Button/List formatting tests ---


class TestFormatting:
    """Test WhatsApp button and list formatting."""

    def test_categories_to_buttons_3(self, service):
        """3 categories → 3 WhatsApp buttons."""
        cats = [
            _make_category(name_fr=f"Cat {i}", order_index=i)
            for i in range(3)
        ]
        buttons = service._categories_to_buttons(cats, "fr")

        assert len(buttons) == 3
        assert buttons[0]["title"] == "Cat 0"
        assert "id" in buttons[0]

    def test_categories_to_buttons_truncates_title(self, service):
        """Long title is truncated to MAX_BUTTON_TITLE_LENGTH."""
        cat = _make_category(name_fr="A" * 50)
        buttons = service._categories_to_buttons([cat], "fr")

        assert len(buttons[0]["title"]) == MAX_BUTTON_TITLE_LENGTH

    def test_categories_to_buttons_max_3(self, service):
        """Even with 5 categories, buttons are capped at MAX_BUTTONS."""
        cats = [_make_category(name_fr=f"Cat {i}") for i in range(5)]
        buttons = service._categories_to_buttons(cats, "fr")

        assert len(buttons) == MAX_BUTTONS

    def test_categories_to_list(self, service):
        """5 categories → list format with sections."""
        cats = [
            _make_category(name_fr=f"Cat {i}", description_fr=f"Desc {i}")
            for i in range(5)
        ]
        sections = service._categories_to_list(cats, "fr")

        assert len(sections) == 1
        assert "rows" in sections[0]
        assert len(sections[0]["rows"]) == 5
        assert sections[0]["rows"][0]["title"] == "Cat 0"
        assert sections[0]["rows"][0]["description"] == "Desc 0"

    def test_items_to_buttons(self, service):
        """2 items → 2 WhatsApp buttons."""
        items = [
            _make_item(title_fr=f"Item {i}")
            for i in range(2)
        ]
        buttons = service._items_to_buttons(items, "fr")

        assert len(buttons) == 2
        assert buttons[0]["title"] == "Item 0"

    def test_format_item_detail(self, service):
        """Complete item → formatted WhatsApp message."""
        item = _make_item(
            title_fr="Exonération IS",
            description_fr="Exonération de l'impôt sur les sociétés",
            conditions="Investissement > 200 MDH",
            legal_reference="Loi 47-18",
            documents_required=["CIN", "Statuts", "Business Plan"],
        )
        detail = service._format_item_detail(item, "fr")

        assert "*Exonération IS*" in detail
        assert "Exonération de l'impôt" in detail
        assert "Loi 47-18" in detail
        assert "Investissement > 200 MDH" in detail
        assert "CIN" in detail

    def test_format_item_detail_arabic(self, service):
        """Arabic language uses Arabic labels."""
        item = _make_item(
            title_fr="Exonération IS",
            title_ar="إعفاء ضريبي",
            description_fr="Description FR",
            description_ar="وصف بالعربية",
            legal_reference="قانون 47-18",
        )
        detail = service._format_item_detail(item, "ar")

        assert "*إعفاء ضريبي*" in detail
        assert "وصف بالعربية" in detail
        assert "المرجع القانوني" in detail  # Arabic label

    def test_format_item_detail_no_optional_fields(self, service):
        """Item with no conditions/legal_ref/docs → minimal output."""
        item = _make_item(
            title_fr="Simple Item",
            description_fr="Simple desc",
            conditions=None,
            legal_reference=None,
            documents_required=[],
        )
        detail = service._format_item_detail(item, "fr")

        assert "*Simple Item*" in detail
        assert "Simple desc" in detail
        assert "Référence légale" not in detail
        assert "Conditions" not in detail
        assert "Documents requis" not in detail


# --- Database query tests (mocked) ---


class TestDatabaseQueries:
    """Test DB query methods with mocked tenant sessions."""

    @pytest.mark.asyncio
    async def test_get_root_categories(self, service):
        """Root categories query returns ordered results."""
        cats = [
            _make_category(name_fr="Cat A", order_index=0),
            _make_category(name_fr="Cat B", order_index=1),
            _make_category(name_fr="Cat C", order_index=2),
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = cats

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        @asynccontextmanager
        async def mock_db_session():
            yield mock_session

        mock_tenant = MagicMock(spec=TenantContext)
        mock_tenant.db_session = mock_db_session

        result = await service._get_root_categories(mock_tenant)

        assert len(result) == 3
        assert result[0].name_fr == "Cat A"
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_item_detail(self, service):
        """Single item lookup returns the item."""
        item = _make_item(title_fr="Exonération IS")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = item

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        @asynccontextmanager
        async def mock_db_session():
            yield mock_session

        mock_tenant = MagicMock(spec=TenantContext)
        mock_tenant.db_session = mock_db_session

        result = await service._get_item_detail(mock_tenant, item.id)

        assert result is not None
        assert result.title_fr == "Exonération IS"

    @pytest.mark.asyncio
    async def test_get_item_detail_not_found(self, service):
        """Non-existent item returns None."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        @asynccontextmanager
        async def mock_db_session():
            yield mock_session

        mock_tenant = MagicMock(spec=TenantContext)
        mock_tenant.db_session = mock_db_session

        result = await service._get_item_detail(mock_tenant, uuid.uuid4())
        assert result is None
