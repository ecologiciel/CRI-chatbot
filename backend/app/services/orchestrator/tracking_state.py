"""Tracking flow state management — Redis-backed conversational state machine.

Manages the multi-step dossier tracking flow that spans multiple WhatsApp
messages: idle → awaiting_identifier → otp_sent → authenticated.

State is persisted in Redis (not LangGraph checkpoints) because each
WhatsApp message triggers a fresh ``graph.ainvoke()`` — LangGraph state
is ephemeral per invocation, while the tracking flow spans many messages.

All Redis keys are tenant-scoped: ``{tenant.slug}:tracking_state:{phone}``.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

import structlog

from app.core.redis import get_redis

if TYPE_CHECKING:
    from app.core.tenant import TenantContext

logger = structlog.get_logger()

# -- Constants ----------------------------------------------------------------

TRACKING_STATE_TTL = 1800  # 30 minutes (matches SESSION_TTL in otp.py)


# -- Enum ---------------------------------------------------------------------


class TrackingStep(str, Enum):
    """Steps in the dossier tracking conversational flow."""

    idle = "idle"
    awaiting_identifier = "awaiting_identifier"
    otp_sent = "otp_sent"
    authenticated = "authenticated"


# -- Dataclass ----------------------------------------------------------------


@dataclass
class TrackingUserState:
    """Per-user tracking flow state, serialized to Redis as JSON.

    Attributes:
        step: Current step in the tracking flow.
        identifier: Dossier numero or CIN entered by user.
        identifier_type: ``"numero"`` or ``"cin"``.
        otp_attempts: Number of OTP verification attempts in current flow.
        session_token: Authenticated session token (from DossierOTPService).
        dossier_ids: List of dossier IDs found for this user.
    """

    step: TrackingStep = TrackingStep.idle
    identifier: str | None = None
    identifier_type: str | None = None
    otp_attempts: int = 0
    session_token: str | None = None
    dossier_ids: list[str] = field(default_factory=list)


# -- State Manager ------------------------------------------------------------


class TrackingStateManager:
    """Redis-backed state manager for the dossier tracking flow.

    Follows the same pattern as ``DossierOTPService``: no constructor
    dependencies, uses ``get_redis()`` directly.
    """

    def __init__(self) -> None:
        self._logger = logger.bind(service="tracking_state")

    @staticmethod
    def _redis_key(tenant: TenantContext, phone: str) -> str:
        """Build tenant-scoped Redis key for tracking state."""
        return f"{tenant.slug}:tracking_state:{phone}"

    async def get_state(
        self, phone: str, tenant: TenantContext,
    ) -> TrackingUserState:
        """Load tracking state from Redis, or return default (idle).

        Args:
            phone: User's WhatsApp phone number (E.164).
            tenant: Current tenant context.

        Returns:
            Deserialized state, or a fresh ``TrackingUserState()`` if absent.
        """
        redis = get_redis()
        key = self._redis_key(tenant, phone)
        raw = await redis.get(key)

        if raw is None:
            return TrackingUserState()

        try:
            data = json.loads(raw)
            return TrackingUserState(
                step=TrackingStep(data.get("step", "idle")),
                identifier=data.get("identifier"),
                identifier_type=data.get("identifier_type"),
                otp_attempts=data.get("otp_attempts", 0),
                session_token=data.get("session_token"),
                dossier_ids=data.get("dossier_ids", []),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            self._logger.warning(
                "tracking_state_deserialize_error",
                phone_last4=phone[-4:],
                tenant=tenant.slug,
                error=str(exc),
            )
            return TrackingUserState()

    async def set_state(
        self,
        phone: str,
        state: TrackingUserState,
        tenant: TenantContext,
    ) -> None:
        """Persist tracking state to Redis with TTL.

        Args:
            phone: User's WhatsApp phone number (E.164).
            state: The tracking state to persist.
            tenant: Current tenant context.
        """
        redis = get_redis()
        key = self._redis_key(tenant, phone)
        data = dataclasses.asdict(state)
        # Serialize enum to its string value
        data["step"] = state.step.value
        await redis.set(key, json.dumps(data), ex=TRACKING_STATE_TTL)

        self._logger.debug(
            "tracking_state_saved",
            phone_last4=phone[-4:],
            tenant=tenant.slug,
            step=state.step.value,
        )

    async def clear_state(
        self, phone: str, tenant: TenantContext,
    ) -> None:
        """Delete tracking state from Redis (reset flow).

        Args:
            phone: User's WhatsApp phone number (E.164).
            tenant: Current tenant context.
        """
        redis = get_redis()
        key = self._redis_key(tenant, phone)
        await redis.delete(key)

        self._logger.debug(
            "tracking_state_cleared",
            phone_last4=phone[-4:],
            tenant=tenant.slug,
        )
