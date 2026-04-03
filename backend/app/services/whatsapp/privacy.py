"""PrivacyNoticeService --- CNDP loi 09-08 Art. 9 compliance.

Sends a one-time privacy notice to every new WhatsApp contact on their
first message.  Uses Redis SET NX for atomic idempotency (same pattern
as dedup in WhatsAppSessionManager).

Fire-and-forget: exceptions are logged but never re-raised.
"""

from __future__ import annotations

import structlog

from app.core.exceptions import WhatsAppSendError
from app.core.redis import get_redis
from app.core.tenant import TenantContext
from app.schemas.audit import AuditLogCreate
from app.services.audit.service import get_audit_service
from app.services.whatsapp.sender import WhatsAppSenderService

logger = structlog.get_logger()

# -- Constants ----------------------------------------------------------------

REDIS_KEY_PREFIX = "privacy_sent"
PRIVACY_TEMPLATE_NAME = "cndp_privacy_notice"

PRIVACY_FALLBACK_TEXT: dict[str, str] = {
    "fr": (
        "\U0001f512 *Protection de vos donn\u00e9es*\n\n"
        "Conform\u00e9ment \u00e0 la loi 09-08 (Art. 9), vos donn\u00e9es "
        "(t\u00e9l\u00e9phone, messages) sont trait\u00e9es pour l\u2019assistance "
        "automatis\u00e9e aux investisseurs. Donn\u00e9es h\u00e9berg\u00e9es au Maroc.\n\n"
        "Vos droits : envoyez *MES DONN\u00c9ES* pour consulter, "
        "ou *STOP* pour vous d\u00e9sinscrire.\n\n"
        "Plus d\u2019infos : dpo@cri.ma"
    ),
    "ar": (
        "\U0001f512 *\u062d\u0645\u0627\u064a\u0629 \u0628\u064a\u0627\u0646\u0627\u062a\u0643*\n\n"
        "\u0648\u0641\u0642\u0627\u064b \u0644\u0644\u0642\u0627\u0646\u0648\u0646 09-08 "
        "(\u0627\u0644\u0645\u0627\u062f\u0629 9)\u060c \u062a\u062a\u0645 "
        "\u0645\u0639\u0627\u0644\u062c\u0629 \u0628\u064a\u0627\u0646\u0627\u062a\u0643\u0645 "
        "(\u0627\u0644\u0647\u0627\u062a\u0641\u060c \u0627\u0644\u0631\u0633\u0627\u0626\u0644) "
        "\u0644\u062e\u062f\u0645\u0629 \u0627\u0644\u0645\u0633\u0627\u0639\u062f\u0629 "
        "\u0627\u0644\u0622\u0644\u064a\u0629 \u0644\u0644\u0645\u0633\u062a\u062b\u0645\u0631\u064a\u0646. "
        "\u0628\u064a\u0627\u0646\u0627\u062a\u0643\u0645 \u0645\u0633\u062a\u0636\u0627\u0641\u0629 "
        "\u0628\u0627\u0644\u0645\u063a\u0631\u0628.\n\n"
        "\u062d\u0642\u0648\u0642\u0643\u0645: \u0623\u0631\u0633\u0644\u0648\u0627 "
        "*\u0628\u064a\u0627\u0646\u0627\u062a\u064a* \u0644\u0644\u0627\u0637\u0644\u0627\u0639\u060c "
        "\u0623\u0648 *\u062a\u0648\u0642\u0641* \u0644\u0625\u0644\u063a\u0627\u0621 "
        "\u0627\u0644\u0627\u0634\u062a\u0631\u0627\u0643.\n\n"
        "\u0644\u0644\u0645\u0632\u064a\u062f: dpo@cri.ma"
    ),
    "en": (
        "\U0001f512 *Data Protection Notice*\n\n"
        "Per Law 09-08 (Art. 9), your data (phone, messages) is processed "
        "for automated investor assistance. Data hosted in Morocco.\n\n"
        "Your rights: send *MY DATA* to access, or *STOP* to unsubscribe.\n\n"
        "More info: dpo@cri.ma"
    ),
}


# -- Service ------------------------------------------------------------------


class PrivacyNoticeService:
    """Sends a one-time CNDP privacy notice to new WhatsApp contacts."""

    def __init__(self) -> None:
        self._logger = logger.bind(service="privacy_notice")
        self._sender = WhatsAppSenderService()

    async def should_send(self, tenant: TenantContext, phone: str) -> bool:
        """Check and atomically mark whether the notice needs sending.

        Uses Redis SET NX (no TTL --- permanent). Returns True if the key
        was newly set (notice not yet sent), False if already exists.
        """
        redis = get_redis()
        key = f"{tenant.redis_prefix}:{REDIS_KEY_PREFIX}:{phone}"
        result = await redis.set(key, "1", nx=True)
        return result is not None

    async def send_privacy_notice(
        self,
        tenant: TenantContext,
        phone: str,
        *,
        language: str = "fr",
    ) -> None:
        """Send privacy notice if not already sent.  Fire-and-forget.

        Args:
            tenant: Current tenant context.
            phone: Recipient phone (E.164).
            language: ISO language code (fr/ar/en).
        """
        try:
            if not await self.should_send(tenant, phone):
                self._logger.debug(
                    "privacy_notice_already_sent",
                    phone_last4=phone[-4:],
                    tenant=tenant.slug,
                )
                return

            method = "template"

            # Try Meta template first
            try:
                await self._sender.send_template(
                    tenant,
                    phone,
                    PRIVACY_TEMPLATE_NAME,
                    language,
                )
            except (WhatsAppSendError, Exception):
                # Fallback to plain text
                method = "text"
                fallback = PRIVACY_FALLBACK_TEXT.get(
                    language, PRIVACY_FALLBACK_TEXT["fr"],
                )
                await self._sender.send_text(tenant, phone, fallback)

            # Audit trail (fire-and-forget)
            audit = get_audit_service()
            await audit.log_action(
                AuditLogCreate(
                    tenant_slug=tenant.slug,
                    user_type="system",
                    action="privacy_notice",
                    resource_type="contact",
                    resource_id=phone,
                    details={
                        "language": language,
                        "method": method,
                        "law": "09-08",
                        "article": "9",
                    },
                ),
            )

            self._logger.info(
                "privacy_notice_sent",
                phone_last4=phone[-4:],
                tenant=tenant.slug,
                language=language,
                method=method,
            )

        except Exception as exc:
            self._logger.warning(
                "privacy_notice_failed",
                phone_last4=phone[-4:],
                tenant=tenant.slug,
                error=str(exc),
            )


# -- Singleton ----------------------------------------------------------------

_privacy_notice_service: PrivacyNoticeService | None = None


def get_privacy_notice_service() -> PrivacyNoticeService:
    """Return the singleton PrivacyNoticeService instance."""
    global _privacy_notice_service  # noqa: PLW0603
    if _privacy_notice_service is None:
        _privacy_notice_service = PrivacyNoticeService()
    return _privacy_notice_service
