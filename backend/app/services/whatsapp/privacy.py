"""PrivacyNoticeService — basic notice for WhatsApp contacts.

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
        "Vos messages sont traités dans le cadre de ce service d’assistance automatisé. "
        "Évitez de transmettre des données sensibles. Pour connaître les modalités de "
        "traitement et exercer vos droits, consultez les informations de confidentialité "
        "de l’institution."
    ),
    "ar": (
        "تُعالج رسائلك في إطار خدمة المساعدة الآلية هذه. تجنّب إرسال بيانات حساسة. "
        "للاطلاع على كيفية معالجة البيانات وممارسة حقوقك، راجع معلومات الخصوصية "
        "الخاصة بالمؤسسة."
    ),
    "en": (
        "Your messages are processed as part of this automated assistance service. "
        "Avoid sending sensitive information. For details about processing and how "
        "to exercise your rights, consult the institution’s privacy information."
    ),
}


# -- Service ------------------------------------------------------------------


class PrivacyNoticeService:
    """Send a basic notice; institutional wording requires independent review."""

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
                    language,
                    PRIVACY_FALLBACK_TEXT["fr"],
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
