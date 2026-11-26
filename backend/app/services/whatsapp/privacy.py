"""PrivacyNoticeService — basic notice for WhatsApp contacts.

Sends a one-time privacy notice to every new WhatsApp contact on their
first message.  Uses Redis SET NX for atomic idempotency (same pattern
as dedup in WhatsAppSessionManager).

Fire-and-forget: exceptions are logged but never re-raised.
"""

from __future__ import annotations

import contextlib
import uuid
from enum import Enum

import structlog
from prometheus_client import Counter

from app.core.redis import get_redis
from app.core.tenant import TenantContext
from app.schemas.audit import AuditLogCreate
from app.services.audit.service import get_audit_service
from app.services.whatsapp.sender import WhatsAppSenderService

logger = structlog.get_logger()

# -- Constants ----------------------------------------------------------------

REDIS_KEY_PREFIX = "privacy_sent"
NOTICE_RESULTS = Counter(
    "cri_whatsapp_privacy_notice_results_total",
    "WhatsApp privacy notice processing results (not a delivery receipt)",
    ["tenant", "result"],
)
_CAS_STATE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('SET', KEYS[1], ARGV[2])
  return 1
end
return 0
"""


class NoticeResult(str, Enum):
    accepted = "accepted"
    pending = "pending"
    uncertain = "uncertain"
    legacy_unknown = "legacy_unknown"


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

    async def send_privacy_notice(
        self,
        tenant: TenantContext,
        phone: str,
        *,
        language: str = "fr",
    ) -> NoticeResult:
        """Attempt one notice; acceptance is not a delivery receipt.

        A pending marker is never silently treated as sent. A timeout is
        uncertain, and is not automatically retried because Meta could have
        accepted the message before the connection failed. Legacy markers did
        not record outcomes and must not be treated as proof of delivery.
        """
        key = f"{tenant.redis_prefix}:{REDIS_KEY_PREFIX}:{phone}"
        token = f"pending:{uuid.uuid4()}"
        try:
            redis = get_redis()
            claimed = await redis.set(key, token, nx=True)
            if not claimed:
                current = await redis.get(key)
                if current == "accepted":
                    result = NoticeResult.accepted
                elif isinstance(current, str) and current.startswith("pending:"):
                    result = NoticeResult.pending
                elif current == "1":
                    result = NoticeResult.legacy_unknown
                else:
                    result = NoticeResult.uncertain
                NOTICE_RESULTS.labels(tenant=tenant.slug, result=result.value).inc()
                self._logger.info(
                    "privacy_notice_existing_state", tenant=tenant.slug, result=result.value
                )
                return result

            try:
                text = PRIVACY_FALLBACK_TEXT.get(language, PRIVACY_FALLBACK_TEXT["fr"])
                message_id = await self._sender.send_text(tenant, phone, text)
                if not message_id:
                    raise RuntimeError("Provider did not confirm acceptance")
                changed = await redis.eval(_CAS_STATE, 1, key, token, "accepted")
                if not changed:
                    raise RuntimeError("Notice state changed before confirmation")
            except Exception as exc:
                # If Redis is unavailable, the pending marker also means unknown.
                with contextlib.suppress(Exception):
                    await redis.eval(_CAS_STATE, 1, key, token, "uncertain")
                NOTICE_RESULTS.labels(tenant=tenant.slug, result=NoticeResult.uncertain.value).inc()
                self._logger.warning(
                    "privacy_notice_unconfirmed", tenant=tenant.slug, error_type=type(exc).__name__
                )
                return NoticeResult.uncertain

            NOTICE_RESULTS.labels(tenant=tenant.slug, result=NoticeResult.accepted.value).inc()
            await get_audit_service().log_action(
                AuditLogCreate(
                    tenant_slug=tenant.slug,
                    user_type="system",
                    action="privacy_notice",
                    resource_type="contact",
                    resource_id=phone,
                    details={"language": language, "method": "text", "state": "provider_accepted"},
                )
            )
            self._logger.info("privacy_notice_provider_accepted", tenant=tenant.slug)
            return NoticeResult.accepted
        except Exception as exc:
            NOTICE_RESULTS.labels(tenant=tenant.slug, result=NoticeResult.uncertain.value).inc()
            self._logger.warning(
                "privacy_notice_state_unavailable",
                tenant=tenant.slug,
                error_type=type(exc).__name__,
            )
            return NoticeResult.uncertain


# -- Singleton ----------------------------------------------------------------

_privacy_notice_service: PrivacyNoticeService | None = None


def get_privacy_notice_service() -> PrivacyNoticeService:
    """Return the singleton PrivacyNoticeService instance."""
    global _privacy_notice_service  # noqa: PLW0603
    if _privacy_notice_service is None:
        _privacy_notice_service = PrivacyNoticeService()
    return _privacy_notice_service
