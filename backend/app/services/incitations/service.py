"""Incentives navigation service — WhatsApp interactive tree browsing.

Navigates the IncentiveCategory tree via WhatsApp buttons (≤3 options)
or lists (>3 options). Presents IncentiveItem detail fiches when a
leaf category item is selected.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select

from app.core.tenant import TenantContext
from app.models.incitation import IncentiveCategory, IncentiveItem
from app.services.orchestrator.state import ConversationState
from app.services.whatsapp.sender import WhatsAppSenderService

logger = structlog.get_logger()

# WhatsApp interactive message limits
MAX_BUTTONS = 3
MAX_BUTTON_TITLE_LENGTH = 20
MAX_LIST_ROW_TITLE_LENGTH = 24
MAX_LIST_ROW_DESCRIPTION_LENGTH = 72

# Localized prompts
_PROMPTS = {
    "fr": {
        "root": "Choisissez une catégorie d'incitations :",
        "subcategory": "Choisissez une sous-catégorie :",
        "items": "Choisissez une incitation pour plus de détails :",
        "list_button": "Voir les options",
        "back": "Retour",
        "legal_ref": "Référence légale",
        "conditions": "Conditions",
        "documents": "Documents requis",
        "no_items": "Aucune incitation disponible dans cette catégorie.",
        "not_found": "Élément introuvable. Veuillez réessayer.",
    },
    "ar": {
        "root": "اختر فئة الحوافز:",
        "subcategory": "اختر فئة فرعية:",
        "items": "اختر حافزاً لمزيد من التفاصيل:",
        "list_button": "عرض الخيارات",
        "back": "رجوع",
        "legal_ref": "المرجع القانوني",
        "conditions": "الشروط",
        "documents": "الوثائق المطلوبة",
        "no_items": "لا توجد حوافز متاحة في هذه الفئة.",
        "not_found": "العنصر غير موجود. يرجى المحاولة مرة أخرى.",
    },
    "en": {
        "root": "Choose an incentive category:",
        "subcategory": "Choose a sub-category:",
        "items": "Choose an incentive for more details:",
        "list_button": "See options",
        "back": "Back",
        "legal_ref": "Legal reference",
        "conditions": "Conditions",
        "documents": "Required documents",
        "no_items": "No incentives available in this category.",
        "not_found": "Item not found. Please try again.",
    },
}


class IncentivesService:
    """Navigate the incentives decision tree via WhatsApp interactive messages.

    Flow:
    1. No current category → show root categories as buttons/list
    2. Selected non-leaf category → show children
    3. Selected leaf category → show items
    4. Selected item → show detail fiche
    """

    def __init__(self, sender: WhatsAppSenderService) -> None:
        self._sender = sender
        self._logger = logger.bind(service="incentives")

    async def handle(
        self,
        state: ConversationState,
        tenant: TenantContext,
    ) -> ConversationState:
        """LangGraph node: handle incentives navigation.

        Reads incentive_state from the conversation state,
        determines what to show, sends WhatsApp message,
        and returns updated state.

        Args:
            state: Current conversation state.
            tenant: Tenant context for DB access.

        Returns:
            Updated state with response and incentive_state.
        """
        phone = state.get("phone", "")
        language = state.get("language", "fr")
        inc_state = state.get("incentive_state", {})
        updates: dict = {}

        selected_item_id = inc_state.get("selected_item_id")
        current_category_id = inc_state.get("current_category_id")

        try:
            if selected_item_id:
                # Show item detail fiche
                response = await self._show_item_detail(
                    tenant,
                    phone,
                    language,
                    selected_item_id,
                )
            elif current_category_id:
                # Navigate deeper into tree
                response = await self._navigate_category(
                    tenant,
                    phone,
                    language,
                    current_category_id,
                    inc_state,
                )
            else:
                # Show root categories
                response = await self._show_root(tenant, phone, language)

            updates["response"] = response
            updates["error"] = None

        except Exception as exc:
            self._logger.error(
                "incentives_error",
                error=str(exc),
                tenant=tenant.slug,
            )
            updates["response"] = self._t(language, "not_found")
            updates["error"] = str(exc)

        return updates  # type: ignore[return-value]

    # ── Navigation steps ──

    async def _show_root(
        self,
        tenant: TenantContext,
        phone: str,
        language: str,
    ) -> str:
        """Show root categories (parent_id IS NULL)."""
        categories = await self._get_root_categories(tenant)

        if not categories:
            return self._t(language, "no_items")

        body_text = self._t(language, "root")
        await self._send_categories(tenant, phone, language, body_text, categories)
        return body_text

    async def _navigate_category(
        self,
        tenant: TenantContext,
        phone: str,
        language: str,
        category_id: str,
        inc_state: dict,
    ) -> str:
        """Navigate into a category — show children or items."""
        cat_uuid = uuid.UUID(category_id)
        children = await self._get_children(tenant, cat_uuid)

        if children:
            # Non-leaf: show sub-categories
            body_text = self._t(language, "subcategory")
            await self._send_categories(tenant, phone, language, body_text, children)
            return body_text

        # Leaf category: show items
        items = await self._get_items(tenant, cat_uuid)
        if not items:
            return self._t(language, "no_items")

        body_text = self._t(language, "items")
        await self._send_items(tenant, phone, language, body_text, items)
        return body_text

    async def _show_item_detail(
        self,
        tenant: TenantContext,
        phone: str,
        language: str,
        item_id: str,
    ) -> str:
        """Show the full detail fiche for an incentive item."""
        item = await self._get_item_detail(tenant, uuid.UUID(item_id))
        if not item:
            return self._t(language, "not_found")

        detail = self._format_item_detail(item, language)
        await self._sender.send_text(tenant, phone, detail)
        return detail

    # ── WhatsApp message sending ──

    async def _send_categories(
        self,
        tenant: TenantContext,
        phone: str,
        language: str,
        body_text: str,
        categories: list[IncentiveCategory],
    ) -> None:
        """Send categories as buttons (≤3) or list (>3)."""
        if len(categories) <= MAX_BUTTONS:
            buttons = self._categories_to_buttons(categories, language)
            await self._sender.send_buttons(tenant, phone, body_text, buttons)
        else:
            sections = self._categories_to_list(categories, language)
            await self._sender.send_list(
                tenant,
                phone,
                body_text,
                self._t(language, "list_button"),
                sections,
            )

    async def _send_items(
        self,
        tenant: TenantContext,
        phone: str,
        language: str,
        body_text: str,
        items: list[IncentiveItem],
    ) -> None:
        """Send items as buttons (≤3) or list (>3)."""
        if len(items) <= MAX_BUTTONS:
            buttons = self._items_to_buttons(items, language)
            await self._sender.send_buttons(tenant, phone, body_text, buttons)
        else:
            sections = self._items_to_list(items, language)
            await self._sender.send_list(
                tenant,
                phone,
                body_text,
                self._t(language, "list_button"),
                sections,
            )

    # ── Database queries ──

    async def _get_root_categories(
        self,
        tenant: TenantContext,
    ) -> list[IncentiveCategory]:
        """Get top-level categories (parent_id IS NULL), ordered by order_index."""
        async with tenant.db_session() as session:
            result = await session.execute(
                select(IncentiveCategory)
                .where(
                    IncentiveCategory.parent_id.is_(None),
                    IncentiveCategory.is_active.is_(True),
                )
                .order_by(IncentiveCategory.order_index),
            )
            return list(result.scalars().all())

    async def _get_children(
        self,
        tenant: TenantContext,
        parent_id: uuid.UUID,
    ) -> list[IncentiveCategory]:
        """Get child categories of a parent."""
        async with tenant.db_session() as session:
            result = await session.execute(
                select(IncentiveCategory)
                .where(
                    IncentiveCategory.parent_id == parent_id,
                    IncentiveCategory.is_active.is_(True),
                )
                .order_by(IncentiveCategory.order_index),
            )
            return list(result.scalars().all())

    async def _get_items(
        self,
        tenant: TenantContext,
        category_id: uuid.UUID,
    ) -> list[IncentiveItem]:
        """Get incentive items for a leaf category."""
        async with tenant.db_session() as session:
            result = await session.execute(
                select(IncentiveItem)
                .where(
                    IncentiveItem.category_id == category_id,
                    IncentiveItem.is_active.is_(True),
                )
                .order_by(IncentiveItem.order_index),
            )
            return list(result.scalars().all())

    async def _get_item_detail(
        self,
        tenant: TenantContext,
        item_id: uuid.UUID,
    ) -> IncentiveItem | None:
        """Get full detail of a single incentive item."""
        async with tenant.db_session() as session:
            result = await session.execute(
                select(IncentiveItem).where(IncentiveItem.id == item_id),
            )
            return result.scalar_one_or_none()

    # ── Formatting helpers ──

    def _categories_to_buttons(
        self,
        categories: list[IncentiveCategory],
        language: str,
    ) -> list[dict[str, str]]:
        """Convert categories to WhatsApp button format (max 3).

        Returns:
            List of {"id": str(cat.id), "title": localized_name[:20]}
        """
        return [
            {
                "id": str(cat.id),
                "title": self._get_localized_name(cat, language)[:MAX_BUTTON_TITLE_LENGTH],
            }
            for cat in categories[:MAX_BUTTONS]
        ]

    def _categories_to_list(
        self,
        categories: list[IncentiveCategory],
        language: str,
    ) -> list[dict]:
        """Convert categories to WhatsApp list sections format.

        Returns:
            [{"title": "...", "rows": [{"id": ..., "title": ..., "description": ...}]}]
        """
        rows = [
            {
                "id": str(cat.id),
                "title": self._get_localized_name(cat, language)[:MAX_LIST_ROW_TITLE_LENGTH],
                "description": (self._get_localized_description(cat, language) or "")[
                    :MAX_LIST_ROW_DESCRIPTION_LENGTH
                ],
            }
            for cat in categories
        ]
        return [{"title": self._t(language, "root"), "rows": rows}]

    def _items_to_buttons(
        self,
        items: list[IncentiveItem],
        language: str,
    ) -> list[dict[str, str]]:
        """Convert items to WhatsApp button format (max 3)."""
        return [
            {
                "id": str(item.id),
                "title": self._get_localized_title(item, language)[:MAX_BUTTON_TITLE_LENGTH],
            }
            for item in items[:MAX_BUTTONS]
        ]

    def _items_to_list(
        self,
        items: list[IncentiveItem],
        language: str,
    ) -> list[dict]:
        """Convert items to WhatsApp list sections format."""
        rows = [
            {
                "id": str(item.id),
                "title": self._get_localized_title(item, language)[:MAX_LIST_ROW_TITLE_LENGTH],
                "description": (self._get_localized_description(item, language) or "")[
                    :MAX_LIST_ROW_DESCRIPTION_LENGTH
                ],
            }
            for item in items
        ]
        return [{"title": self._t(language, "items"), "rows": rows}]

    def _format_item_detail(self, item: IncentiveItem, language: str) -> str:
        """Format incentive item as readable WhatsApp message.

        Uses WhatsApp markdown: *bold*, _italic_.
        """
        title = self._get_localized_title(item, language)
        description = self._get_localized_description(item, language) or ""
        t = _PROMPTS.get(language, _PROMPTS["fr"])

        parts = [f"*{title}*", ""]

        if description:
            parts.append(description)
            parts.append("")

        if item.legal_reference:
            parts.append(f"*{t['legal_ref']} :* {item.legal_reference}")

        if item.conditions:
            parts.append(f"*{t['conditions']} :* {item.conditions}")

        if item.documents_required:
            docs = ", ".join(str(d) for d in item.documents_required)
            parts.append(f"*{t['documents']} :* {docs}")

        return "\n".join(parts)

    # ── Localization helpers ──

    def _get_localized_name(self, obj: IncentiveCategory, language: str) -> str:
        """Get name in the detected language with FR fallback."""
        if language == "ar" and obj.name_ar:
            return obj.name_ar
        if language == "en" and obj.name_en:
            return obj.name_en
        return obj.name_fr

    def _get_localized_title(self, obj: IncentiveItem, language: str) -> str:
        """Get title in the detected language with FR fallback."""
        if language == "ar" and obj.title_ar:
            return obj.title_ar
        if language == "en" and obj.title_en:
            return obj.title_en
        return obj.title_fr

    def _get_localized_description(
        self,
        obj: IncentiveCategory | IncentiveItem,
        language: str,
    ) -> str | None:
        """Get description in the detected language with FR fallback."""
        if language == "ar" and obj.description_ar:
            return obj.description_ar
        if language == "en" and obj.description_en:
            return obj.description_en
        return obj.description_fr

    @staticmethod
    def _t(language: str, key: str) -> str:
        """Get a localized prompt string."""
        return _PROMPTS.get(language, _PROMPTS["fr"]).get(key, key)


# ── Singleton ──

_incentives_service: IncentivesService | None = None


def get_incentives_service() -> IncentivesService:
    """Get or create the IncentivesService singleton."""
    global _incentives_service  # noqa: PLW0603
    if _incentives_service is None:
        _incentives_service = IncentivesService(sender=WhatsAppSenderService())
    return _incentives_service
