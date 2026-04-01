"""TrackingAgent — LangGraph node for OTP-authenticated dossier tracking.

Implements a multi-step conversational flow via WhatsApp:

    idle → awaiting_identifier → otp_sent → authenticated

State is persisted in Redis between WhatsApp messages (see
``tracking_state.py``). **No data transits through Gemini** — dossier
consultation is 100% local (PostgreSQL). Anti-BOLA is enforced via
``DossierService.get_dossiers_by_phone`` / ``get_dossier_with_bola_check``.

Follows the same class pattern as ``FAQAgent``, ``InternalAgent``, etc.:
constructor with injected dependencies, ``handle(state, tenant)`` method
returning a partial ``ConversationState`` dict.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

import structlog

from app.core.exceptions import RateLimitExceededError
from app.models.enums import Language
from app.services.dossier.otp import DossierOTPService, get_dossier_otp_service
from app.services.dossier.service import DossierService, get_dossier_service
from app.services.orchestrator.state import ConversationState
from app.services.orchestrator.tracking_state import (
    TrackingStateManager,
    TrackingStep,
    TrackingUserState,
)

if TYPE_CHECKING:
    from app.core.tenant import TenantContext

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Dossier numero: 2024-001, 2024/12345, etc.
_DOSSIER_NUMERO_RE = re.compile(r"(\d{4}[-/]\d{1,6})")
# Moroccan CIN: 1-2 uppercase letters + 5-7 digits
_CIN_RE = re.compile(r"([A-Z]{1,2}\d{5,7})", re.IGNORECASE)
# OTP: exactly 6 digits (full match)
_OTP_RE = re.compile(r"(\d{6})")


# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

_CANCEL_KEYWORDS: set[str] = {
    # French
    "annuler", "retour", "quitter",
    # Arabic
    "\u0627\u0644\u063a\u0627\u0621",  # الغاء
    "\u0631\u062c\u0648\u0639",         # رجوع
    # English
    "cancel", "back", "quit",
}

_LOGOUT_KEYWORDS: set[str] = {
    # French
    "deconnecter", "terminer", "fin",
    # Arabic
    "\u062e\u0631\u0648\u062c",  # خروج
    # English
    "logout", "done",
}


# ---------------------------------------------------------------------------
# Trilingual messages
# ---------------------------------------------------------------------------

_MESSAGES: dict[str, dict[str, str]] = {
    "ask_identifier": {
        "fr": (
            "\U0001f4cb Pour consulter votre dossier, veuillez saisir "
            "votre *num\u00e9ro de dossier* (ex: 2024-1234) ou votre *CIN*."
        ),
        "ar": (
            "\U0001f4cb \u0644\u0644\u0627\u0637\u0644\u0627\u0639 "
            "\u0639\u0644\u0649 \u0645\u0644\u0641\u0643\u0645\u060c "
            "\u064a\u0631\u062c\u0649 \u0625\u062f\u062e\u0627\u0644 "
            "*\u0631\u0642\u0645 \u0627\u0644\u0645\u0644\u0641* "
            "(\u0645\u062b\u0627\u0644: 2024-1234) "
            "\u0623\u0648 *\u0631\u0642\u0645 \u0627\u0644\u0628\u0637\u0627\u0642\u0629 "
            "\u0627\u0644\u0648\u0637\u0646\u064a\u0629*."
        ),
        "en": (
            "\U0001f4cb To check your file status, please enter your "
            "*file number* (e.g., 2024-1234) or your *national ID (CIN)*."
        ),
    },
    "otp_sent": {
        "fr": (
            "\U0001f510 Un code de v\u00e9rification \u00e0 6 chiffres "
            "a \u00e9t\u00e9 envoy\u00e9. Veuillez le saisir."
        ),
        "ar": (
            "\U0001f510 \u062a\u0645 \u0625\u0631\u0633\u0627\u0644 "
            "\u0631\u0645\u0632 \u0627\u0644\u062a\u062d\u0642\u0642 "
            "\u0627\u0644\u0645\u0643\u0648\u0646 \u0645\u0646 6 "
            "\u0623\u0631\u0642\u0627\u0645. \u064a\u0631\u062c\u0649 "
            "\u0625\u062f\u062e\u0627\u0644\u0647."
        ),
        "en": (
            "\U0001f510 A 6-digit verification code has been sent. "
            "Please enter it."
        ),
    },
    "otp_invalid": {
        "fr": (
            "\u274c Code incorrect. Veuillez r\u00e9essayer "
            "({remaining} tentative(s) restante(s))."
        ),
        "ar": (
            "\u274c \u0631\u0645\u0632 \u063a\u064a\u0631 "
            "\u0635\u062d\u064a\u062d. \u064a\u0631\u062c\u0649 "
            "\u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629 "
            "\u0645\u0631\u0629 \u0623\u062e\u0631\u0649 "
            "({remaining} \u0645\u062d\u0627\u0648\u0644\u0629/\u0645\u062d\u0627\u0648\u0644\u0627\u062a "
            "\u0645\u062a\u0628\u0642\u064a\u0629)."
        ),
        "en": (
            "\u274c Invalid code. Please try again "
            "({remaining} attempt(s) remaining)."
        ),
    },
    "otp_rate_limited": {
        "fr": (
            "\u23f3 Trop de tentatives. Veuillez r\u00e9essayer "
            "dans 15 minutes."
        ),
        "ar": (
            "\u23f3 \u0645\u062d\u0627\u0648\u0644\u0627\u062a "
            "\u0643\u062b\u064a\u0631\u0629 \u062c\u062f\u064b\u0627. "
            "\u064a\u0631\u062c\u0649 \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629 "
            "\u0628\u0639\u062f 15 \u062f\u0642\u064a\u0642\u0629."
        ),
        "en": (
            "\u23f3 Too many attempts. Please try again "
            "in 15 minutes."
        ),
    },
    "no_dossier_found": {
        "fr": (
            "\U0001f50d Aucun dossier trouv\u00e9 avec cet identifiant. "
            "V\u00e9rifiez et r\u00e9essayez."
        ),
        "ar": (
            "\U0001f50d \u0644\u0645 \u064a\u062a\u0645 "
            "\u0627\u0644\u0639\u062b\u0648\u0631 \u0639\u0644\u0649 "
            "\u0645\u0644\u0641 \u0628\u0647\u0630\u0627 "
            "\u0627\u0644\u0645\u0639\u0631\u0641. \u064a\u0631\u062c\u0649 "
            "\u0627\u0644\u062a\u062d\u0642\u0642 "
            "\u0648\u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629 "
            "\u0645\u0631\u0629 \u0623\u062e\u0631\u0649."
        ),
        "en": (
            "\U0001f50d No file found with this identifier. "
            "Please check and try again."
        ),
    },
    "session_expired": {
        "fr": (
            "\u23f0 Votre session a expir\u00e9. "
            "Envoyez \u00absuivi\u00bb pour recommencer."
        ),
        "ar": (
            "\u23f0 \u0627\u0646\u062a\u0647\u062a "
            "\u0635\u0644\u0627\u062d\u064a\u0629 \u062c\u0644\u0633\u062a\u0643. "
            "\u0623\u0631\u0633\u0644 \u00ab\u0645\u062a\u0627\u0628\u0639\u0629\u00bb "
            "\u0644\u0644\u0628\u062f\u0621 \u0645\u0646 \u062c\u062f\u064a\u062f."
        ),
        "en": (
            "\u23f0 Your session has expired. "
            "Send \u00abtrack\u00bb to start again."
        ),
    },
    "dossier_header": {
        "fr": "\u2705 Voici vos dossier(s) :\n\n",
        "ar": "\u2705 \u0625\u0644\u064a\u0643 \u0645\u0644\u0641\u0627\u062a\u0643 :\n\n",
        "en": "\u2705 Here are your file(s):\n\n",
    },
    "no_dossiers_for_phone": {
        "fr": (
            "\U0001f4cb Aucun dossier n\u2019est associ\u00e9 "
            "\u00e0 votre num\u00e9ro de t\u00e9l\u00e9phone."
        ),
        "ar": (
            "\U0001f4cb \u0644\u0627 \u062a\u0648\u062c\u062f "
            "\u0645\u0644\u0641\u0627\u062a \u0645\u0631\u062a\u0628\u0637\u0629 "
            "\u0628\u0631\u0642\u0645 \u0647\u0627\u062a\u0641\u0643."
        ),
        "en": (
            "\U0001f4cb No files are associated with your phone number."
        ),
    },
    "cancel_confirmed": {
        "fr": "\u2705 Op\u00e9ration annul\u00e9e. Comment puis-je vous aider ?",
        "ar": "\u2705 \u062a\u0645 \u0627\u0644\u0625\u0644\u063a\u0627\u0621. \u0643\u064a\u0641 \u064a\u0645\u0643\u0646\u0646\u064a \u0645\u0633\u0627\u0639\u062f\u062a\u0643\u061f",
        "en": "\u2705 Operation cancelled. How can I help you?",
    },
    "logout_confirmed": {
        "fr": "\U0001f44b Session termin\u00e9e. \u00c0 bient\u00f4t !",
        "ar": "\U0001f44b \u062a\u0645 \u0625\u0646\u0647\u0627\u0621 \u0627\u0644\u062c\u0644\u0633\u0629. \u0625\u0644\u0649 \u0627\u0644\u0644\u0642\u0627\u0621!",
        "en": "\U0001f44b Session ended. See you soon!",
    },
    "enter_otp": {
        "fr": "Veuillez saisir le code \u00e0 6 chiffres envoy\u00e9 par SMS.",
        "ar": "\u064a\u0631\u062c\u0649 \u0625\u062f\u062e\u0627\u0644 \u0627\u0644\u0631\u0645\u0632 \u0627\u0644\u0645\u0643\u0648\u0646 \u0645\u0646 6 \u0623\u0631\u0642\u0627\u0645.",
        "en": "Please enter the 6-digit code sent to your number.",
    },
    "otp_max_attempts": {
        "fr": (
            "\u26a0\ufe0f Nombre maximal de tentatives atteint. "
            "Veuillez r\u00e9essayer plus tard."
        ),
        "ar": (
            "\u26a0\ufe0f \u062a\u0645 \u0628\u0644\u0648\u063a "
            "\u0627\u0644\u062d\u062f \u0627\u0644\u0623\u0642\u0635\u0649 "
            "\u0645\u0646 \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0627\u062a. "
            "\u064a\u0631\u062c\u0649 \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629 "
            "\u0644\u0627\u062d\u0642\u064b\u0627."
        ),
        "en": (
            "\u26a0\ufe0f Maximum attempts reached. "
            "Please try again later."
        ),
    },
    "error_fallback": {
        "fr": "Une erreur est survenue. Veuillez r\u00e9essayer.",
        "ar": "\u062d\u062f\u062b \u062e\u0637\u0623. \u064a\u0631\u062c\u0649 \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629 \u0645\u0631\u0629 \u0623\u062e\u0631\u0649.",
        "en": "An error occurred. Please try again.",
    },
}

MAX_OTP_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(key: str, language: str, **kwargs: str) -> str:
    """Get a trilingual message, with optional format substitution."""
    lang_map = _MESSAGES.get(key, {})
    text = lang_map.get(language, lang_map.get("fr", ""))
    if kwargs:
        text = text.format(**kwargs)
    return text


def _is_cancel(query: str) -> bool:
    """Check if the user wants to cancel the tracking flow."""
    words = query.lower().split()
    return bool(_CANCEL_KEYWORDS & set(words))


def _is_logout(query: str) -> bool:
    """Check if the user wants to end the session."""
    words = query.lower().split()
    return bool(_LOGOUT_KEYWORDS & set(words))


def _extract_identifier(query: str) -> tuple[str, str] | None:
    """Extract a dossier numero or CIN from the query.

    Returns:
        ``(value, type)`` where type is ``"numero"`` or ``"cin"``,
        or ``None`` if no identifier found.
    """
    # Try dossier numero first (more specific pattern)
    match = _DOSSIER_NUMERO_RE.search(query)
    if match:
        return match.group(1), "numero"

    # Try CIN
    match = _CIN_RE.search(query)
    if match:
        return match.group(1).upper(), "cin"

    return None


# ---------------------------------------------------------------------------
# TrackingAgent
# ---------------------------------------------------------------------------


class TrackingAgent:
    """LangGraph node for OTP-authenticated dossier consultation.

    Manages a stateful flow persisted in Redis:
    ``idle → awaiting_identifier → otp_sent → authenticated``.

    No data transits through Gemini — all operations are local
    (PostgreSQL lookups + Redis state).
    """

    def __init__(
        self,
        otp_service: DossierOTPService,
        dossier_service: DossierService,
        state_manager: TrackingStateManager,
    ) -> None:
        self._otp = otp_service
        self._dossier = dossier_service
        self._state_mgr = state_manager
        self._logger = logger.bind(service="tracking_agent")

    # -- Main entry point ---------------------------------------------------

    async def handle(
        self,
        state: ConversationState,
        tenant: TenantContext,
    ) -> ConversationState:
        """Process a tracking-related message through the step machine.

        Args:
            state: Current LangGraph conversation state.
            tenant: Current tenant context.

        Returns:
            Partial ConversationState with ``response`` set.
        """
        phone = state.get("phone", "")
        query = (state.get("query") or "").strip()
        language = state.get("language", "fr")

        self._logger.info(
            "tracking_agent_start",
            tenant=tenant.slug,
            phone_last4=phone[-4:],
        )

        try:
            tracking = await self._state_mgr.get_state(phone, tenant)

            # Universal cancel check (any step except idle)
            if tracking.step != TrackingStep.idle and _is_cancel(query):
                await self._state_mgr.clear_state(phone, tenant)
                self._logger.info(
                    "tracking_cancelled",
                    tenant=tenant.slug,
                    phone_last4=phone[-4:],
                    from_step=tracking.step.value,
                )
                return {"response": _msg("cancel_confirmed", language)}  # type: ignore[return-value]

            # Dispatch by current step
            if tracking.step == TrackingStep.idle:
                return await self._handle_idle(
                    tenant, tracking, phone, query, language,
                )
            if tracking.step == TrackingStep.awaiting_identifier:
                return await self._handle_awaiting_identifier(
                    tenant, tracking, phone, query, language,
                )
            if tracking.step == TrackingStep.otp_sent:
                return await self._handle_otp_sent(
                    tenant, tracking, phone, query, language,
                )
            if tracking.step == TrackingStep.authenticated:
                return await self._handle_authenticated(
                    tenant, tracking, phone, query, language,
                )

            # Defensive fallback: unknown step → reset
            await self._state_mgr.clear_state(phone, tenant)
            return {"response": _msg("ask_identifier", language)}  # type: ignore[return-value]

        except Exception as exc:
            self._logger.error(
                "tracking_agent_error",
                tenant=tenant.slug,
                phone_last4=phone[-4:],
                error=str(exc),
            )
            return {"response": _msg("error_fallback", language)}  # type: ignore[return-value]

    # -- Step handlers ------------------------------------------------------

    async def _handle_idle(
        self,
        tenant: TenantContext,
        tracking: TrackingUserState,
        phone: str,
        query: str,
        language: str,
    ) -> ConversationState:
        """Entry point: check if query already contains an identifier."""
        # Optimization: if the initial query already has an identifier,
        # skip the "enter identifier" prompt and process immediately.
        identifier = _extract_identifier(query)
        if identifier:
            tracking.step = TrackingStep.awaiting_identifier
            return await self._handle_awaiting_identifier(
                tenant, tracking, phone, query, language,
            )

        # Ask the user to enter their identifier
        tracking.step = TrackingStep.awaiting_identifier
        await self._state_mgr.set_state(phone, tracking, tenant)

        self._logger.info(
            "tracking_ask_identifier",
            tenant=tenant.slug,
            phone_last4=phone[-4:],
        )
        return {"response": _msg("ask_identifier", language)}  # type: ignore[return-value]

    async def _handle_awaiting_identifier(
        self,
        tenant: TenantContext,
        tracking: TrackingUserState,
        phone: str,
        query: str,
        language: str,
    ) -> ConversationState:
        """Parse identifier, look up dossier, initiate OTP if found."""
        identifier = _extract_identifier(query)
        if identifier is None:
            # Unrecognized input — ask again
            return {"response": _msg("ask_identifier", language)}  # type: ignore[return-value]

        value, id_type = identifier
        tracking.identifier = value
        tracking.identifier_type = id_type

        self._logger.info(
            "tracking_identifier_received",
            tenant=tenant.slug,
            phone_last4=phone[-4:],
            identifier_type=id_type,
        )

        # Verify the identifier maps to at least one dossier
        has_dossier = False
        if id_type == "numero":
            dossier = await self._dossier.get_dossier_by_numero(tenant, value)
            if dossier is not None:
                has_dossier = True
                tracking.dossier_ids = [str(dossier.id)]
        else:
            # CIN: look up dossiers by phone (anti-BOLA safe)
            dossiers = await self._dossier.get_dossiers_by_phone(tenant, phone)
            if dossiers:
                has_dossier = True
                tracking.dossier_ids = [str(d.id) for d in dossiers]

        if not has_dossier:
            self._logger.info(
                "tracking_identifier_not_found",
                tenant=tenant.slug,
                phone_last4=phone[-4:],
                identifier_type=id_type,
            )
            return {"response": _msg("no_dossier_found", language)}  # type: ignore[return-value]

        # Check rate limit before generating OTP
        if await self._otp.is_rate_limited(tenant, phone):
            self._logger.warning(
                "tracking_otp_rate_limited",
                tenant=tenant.slug,
                phone_last4=phone[-4:],
            )
            return {"response": _msg("otp_rate_limited", language)}  # type: ignore[return-value]

        # Generate and send OTP
        try:
            otp_code = await self._otp.generate_otp(phone, tenant)
        except RateLimitExceededError:
            return {"response": _msg("otp_rate_limited", language)}  # type: ignore[return-value]

        self._logger.info(
            "tracking_otp_generated",
            tenant=tenant.slug,
            phone_last4=phone[-4:],
        )

        # Transition to otp_sent
        tracking.step = TrackingStep.otp_sent
        tracking.otp_attempts = 0
        await self._state_mgr.set_state(phone, tracking, tenant)

        return {"response": _msg("otp_sent", language)}  # type: ignore[return-value]

    async def _handle_otp_sent(
        self,
        tenant: TenantContext,
        tracking: TrackingUserState,
        phone: str,
        query: str,
        language: str,
    ) -> ConversationState:
        """Verify OTP code. On success, create session and show dossiers."""
        # Extract 6-digit code
        match = _OTP_RE.search(query)
        if not match:
            return {"response": _msg("enter_otp", language)}  # type: ignore[return-value]

        otp_code = match.group(1)
        is_valid = await self._otp.verify_otp(phone, otp_code, tenant)

        if is_valid:
            # Create authenticated session
            session_token = await self._otp.create_dossier_session(phone, tenant)

            # Load dossiers for this phone
            dossiers = await self._dossier.get_dossiers_by_phone(tenant, phone)

            # Transition to authenticated
            tracking.step = TrackingStep.authenticated
            tracking.session_token = session_token
            tracking.otp_attempts = 0
            if dossiers:
                tracking.dossier_ids = [str(d.id) for d in dossiers]
            await self._state_mgr.set_state(phone, tracking, tenant)

            self._logger.info(
                "tracking_authenticated",
                tenant=tenant.slug,
                phone_last4=phone[-4:],
                dossier_count=len(dossiers),
            )

            if not dossiers:
                return {"response": _msg("no_dossiers_for_phone", language)}  # type: ignore[return-value]

            # Format dossier list
            lang_enum = Language(language) if language in ("fr", "ar", "en") else Language.fr
            response = _msg("dossier_header", language)
            for d_read in dossiers:
                # get_dossier_with_bola_check returns DossierDetail
                detail = await self._dossier.get_dossier_with_bola_check(
                    tenant, d_read.id, phone,
                )
                response += self._dossier.format_dossier_for_whatsapp(
                    detail, lang_enum,
                )
                response += "\n\n---\n\n"

            return {"response": response.rstrip("\n-")}  # type: ignore[return-value]

        # Invalid OTP
        tracking.otp_attempts += 1

        if tracking.otp_attempts >= MAX_OTP_ATTEMPTS:
            # Max attempts reached — reset flow
            await self._state_mgr.clear_state(phone, tenant)
            self._logger.warning(
                "tracking_otp_max_attempts",
                tenant=tenant.slug,
                phone_last4=phone[-4:],
            )
            return {"response": _msg("otp_max_attempts", language)}  # type: ignore[return-value]

        # Still has remaining attempts
        await self._state_mgr.set_state(phone, tracking, tenant)
        remaining = MAX_OTP_ATTEMPTS - tracking.otp_attempts

        self._logger.info(
            "tracking_otp_invalid",
            tenant=tenant.slug,
            phone_last4=phone[-4:],
            attempts=tracking.otp_attempts,
        )

        return {  # type: ignore[return-value]
            "response": _msg(
                "otp_invalid", language,
                remaining=str(remaining),
            ),
        }

    async def _handle_authenticated(
        self,
        tenant: TenantContext,
        tracking: TrackingUserState,
        phone: str,
        query: str,
        language: str,
    ) -> ConversationState:
        """Authenticated session: validate session and serve dossier queries."""
        # Validate session (sliding window TTL renewed on success)
        if not tracking.session_token or not await self._otp.validate_dossier_session(
            phone, tracking.session_token, tenant,
        ):
            # Session expired or invalid
            await self._state_mgr.clear_state(phone, tenant)
            self._logger.info(
                "tracking_session_expired",
                tenant=tenant.slug,
                phone_last4=phone[-4:],
            )
            return {"response": _msg("session_expired", language)}  # type: ignore[return-value]

        # Logout check
        if _is_logout(query):
            await self._otp.invalidate_session(phone, tenant)
            await self._state_mgr.clear_state(phone, tenant)
            self._logger.info(
                "tracking_logout",
                tenant=tenant.slug,
                phone_last4=phone[-4:],
            )
            return {"response": _msg("logout_confirmed", language)}  # type: ignore[return-value]

        lang_enum = Language(language) if language in ("fr", "ar", "en") else Language.fr

        # Check if the user is asking about a specific dossier
        identifier = _extract_identifier(query)
        if identifier and identifier[1] == "numero":
            numero = identifier[0]
            dossier = await self._dossier.get_dossier_by_numero(tenant, numero)
            if dossier is None:
                return {"response": _msg("no_dossier_found", language)}  # type: ignore[return-value]

            # Anti-BOLA check
            try:
                detail = await self._dossier.get_dossier_with_bola_check(
                    tenant, dossier.id, phone,
                )
            except Exception:
                self._logger.warning(
                    "tracking_bola_denied",
                    tenant=tenant.slug,
                    phone_last4=phone[-4:],
                )
                return {"response": _msg("no_dossier_found", language)}  # type: ignore[return-value]

            return {  # type: ignore[return-value]
                "response": self._dossier.format_dossier_for_whatsapp(
                    detail, lang_enum,
                ),
            }

        # Default: show all dossiers for this phone
        dossiers = await self._dossier.get_dossiers_by_phone(tenant, phone)

        if not dossiers:
            return {"response": _msg("no_dossiers_for_phone", language)}  # type: ignore[return-value]

        response = _msg("dossier_header", language)
        for d_read in dossiers:
            try:
                detail = await self._dossier.get_dossier_with_bola_check(
                    tenant, d_read.id, phone,
                )
                response += self._dossier.format_dossier_for_whatsapp(
                    detail, lang_enum,
                )
                response += "\n\n---\n\n"
            except Exception:
                # Skip dossiers that fail BOLA check (shouldn't happen
                # with get_dossiers_by_phone, but defensive)
                continue

        return {"response": response.rstrip("\n-")}  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_tracking_agent: TrackingAgent | None = None


def get_tracking_agent() -> TrackingAgent:
    """Get or create the TrackingAgent singleton."""
    global _tracking_agent  # noqa: PLW0603
    if _tracking_agent is None:
        _tracking_agent = TrackingAgent(
            otp_service=get_dossier_otp_service(),
            dossier_service=get_dossier_service(),
            state_manager=TrackingStateManager(),
        )
    return _tracking_agent
