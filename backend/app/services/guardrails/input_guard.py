"""InputGuardService — validate user input before LLM processing.

Check order (cheapest first):
1. Length check (instant, free)
2. Injection regex patterns (instant, free)
3. Gemini topic classification (~20 tokens, async)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog
from prometheus_client import Counter

from app.core.tenant import TenantContext
from app.schemas.ai import GeminiRequest
from app.services.ai.gemini import get_gemini_service

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
GUARDRAIL_INPUT_CHECKS = Counter(
    "cri_guardrail_input_checks_total",
    "Total input guard checks",
    ["result"],  # allow, block, warn
)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InputGuardResult:
    """Result of input safety check."""

    is_safe: bool  # True if input passes all checks
    action: str  # "allow", "block", "warn"
    reason: str  # Human-readable reason (for logs/admin)
    category: str  # "safe", "injection", "off_topic", "too_long"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_INPUT_LENGTH = 2000  # Maximum message length in characters

# Injection regex patterns — English + French + Arabic
# Each tuple: (compiled_regex, subcategory_label)
_INJECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Instruction override
    (re.compile(r"ignore\s+(all\s+)?(previous\s+)?instructions?", re.IGNORECASE), "instruction_override"),
    (re.compile(r"oublie\s+(toutes?\s+)?(les\s+)?instructions?", re.IGNORECASE), "instruction_override"),
    (re.compile(r"disregard\s+(all\s+)?(prior\s+)?instructions?", re.IGNORECASE), "instruction_override"),
    (re.compile(r"forget\s+(all\s+)?(your\s+)?instructions?", re.IGNORECASE), "instruction_override"),
    (re.compile(r"ignore[zr]?\s+(toutes?\s+)?(les\s+)?instructions?\s+pr[ée]c[ée]dentes?", re.IGNORECASE), "instruction_override"),
    (re.compile(r"override\s+(your\s+)?(instructions?|programming|rules)", re.IGNORECASE), "instruction_override"),
    (re.compile(r"new\s+instructions?\s*:", re.IGNORECASE), "instruction_override"),
    # Role-play / persona hijacking
    (re.compile(r"you\s+are\s+now\s+(a|an|my)", re.IGNORECASE), "role_play"),
    (re.compile(r"tu\s+es\s+(maintenant|d[ée]sormais)", re.IGNORECASE), "role_play"),
    (re.compile(r"act\s+as\s+(a|an|if)", re.IGNORECASE), "role_play"),
    (re.compile(r"pretend\s+(you\s+are|to\s+be)", re.IGNORECASE), "role_play"),
    (re.compile(r"joue\s+le\s+r[oô]le\s+", re.IGNORECASE), "role_play"),
    (re.compile(r"role[\s-]?play(?:ing)?\s+as", re.IGNORECASE), "role_play"),
    # System prompt extraction
    (re.compile(r"(show|display|print|reveal|repeat)\s+(me\s+)?(your\s+)?(system\s+)?prompt", re.IGNORECASE), "prompt_extraction"),
    (re.compile(r"(montre|affiche|r[eé]p[eè]te)\s+(moi\s+)?(ton\s+)?prompt", re.IGNORECASE), "prompt_extraction"),
    (re.compile(r"what\s+(?:are|is)\s+your\s+(?:system\s+)?(?:prompt|instructions?|rules)", re.IGNORECASE), "prompt_extraction"),
    (re.compile(r"repeat\s+(?:the|your)\s+(?:system|initial)\s+(?:prompt|instructions?)", re.IGNORECASE), "prompt_extraction"),
    # DAN / jailbreak
    (re.compile(r"\bDAN\b.*\bmode\b", re.IGNORECASE), "jailbreak"),
    (re.compile(r"jailbreak", re.IGNORECASE), "jailbreak"),
    (re.compile(r"developer\s+mode", re.IGNORECASE), "jailbreak"),
    (re.compile(r"do\s+anything\s+now", re.IGNORECASE), "jailbreak"),
    (re.compile(r"bypass\s+(your\s+)?(rules|restrictions|filters|safety)", re.IGNORECASE), "jailbreak"),
    # System tag injection
    (re.compile(r"^system\s*:", re.IGNORECASE | re.MULTILINE), "system_tag"),
    (re.compile(r"<\s*system\s*>", re.IGNORECASE), "system_tag"),
    # Arabic injection variants
    (re.compile(r"تجاهل\s+(كل\s+)?التعليمات"), "instruction_override_ar"),
    (re.compile(r"أنت\s+الآن\s+"), "role_play_ar"),
]

# Topic classification prompt — minimal tokens
_TOPIC_SYSTEM_PROMPT = (
    "Tu es un classificateur de pertinence. Le contexte est un Centre Régional "
    "d'Investissement (CRI) au Maroc. Réponds UNIQUEMENT par 'oui' ou 'non'. "
    "La question concerne-t-elle l'investissement, la création d'entreprise, "
    "les procédures administratives CRI, les incitations fiscales, ou le suivi de dossier?"
)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class InputGuardService:
    """Validate user input before LLM processing.

    Runs checks in cost-ascending order: length → injection regex → Gemini topic.
    Thread-safe, async-only. Created once at startup, shared across requests.
    """

    def __init__(self) -> None:
        self._gemini = get_gemini_service()
        self._logger = logger.bind(service="input_guard")

    async def check(
        self,
        text: str,
        tenant: TenantContext,
        language: str = "fr",
    ) -> InputGuardResult:
        """Run all input guards in cost-ascending order.

        Args:
            text: Raw user input text.
            tenant: Tenant context for Gemini cost tracking.
            language: Detected language code (fr/ar/en).

        Returns:
            InputGuardResult with safety verdict and reason.
        """
        if not text or not text.strip():
            GUARDRAIL_INPUT_CHECKS.labels(result="allow").inc()
            return InputGuardResult(
                is_safe=True, action="allow", reason="Empty input", category="safe",
            )

        stripped = text.strip()

        # 1. Length check (instant)
        length_result = self._check_length(stripped)
        if length_result is not None:
            GUARDRAIL_INPUT_CHECKS.labels(result=length_result.action).inc()
            self._logger.warning(
                "input_blocked",
                category=length_result.category,
                reason=length_result.reason,
                tenant=tenant.slug,
            )
            return length_result

        # 2. Injection regex (instant)
        injection_result = self._check_injection(stripped)
        if injection_result is not None:
            GUARDRAIL_INPUT_CHECKS.labels(result=injection_result.action).inc()
            self._logger.warning(
                "input_blocked",
                category=injection_result.category,
                tenant=tenant.slug,
            )
            return injection_result

        # 3. Topic classification via Gemini (~20 tokens)
        topic_result = await self._check_topic(stripped, tenant, language)
        if topic_result is not None:
            GUARDRAIL_INPUT_CHECKS.labels(result=topic_result.action).inc()
            self._logger.info(
                "input_warned",
                category=topic_result.category,
                tenant=tenant.slug,
            )
            return topic_result

        # All checks passed
        GUARDRAIL_INPUT_CHECKS.labels(result="allow").inc()
        return InputGuardResult(
            is_safe=True,
            action="allow",
            reason="All checks passed",
            category="safe",
        )

    def _check_length(self, text: str) -> InputGuardResult | None:
        """Return block result if text exceeds MAX_INPUT_LENGTH, else None."""
        if len(text) > MAX_INPUT_LENGTH:
            return InputGuardResult(
                is_safe=False,
                action="block",
                reason=f"Message too long: {len(text)} chars (max {MAX_INPUT_LENGTH})",
                category="too_long",
            )
        return None

    def _check_injection(self, text: str) -> InputGuardResult | None:
        """Return block result if injection patterns found, else None."""
        for pattern, subcategory in _INJECTION_PATTERNS:
            match = pattern.search(text)
            if match:
                return InputGuardResult(
                    is_safe=False,
                    action="block",
                    reason=f"Prompt injection detected ({subcategory})",
                    category="injection",
                )
        return None

    async def _check_topic(
        self,
        text: str,
        tenant: TenantContext,
        language: str,
    ) -> InputGuardResult | None:
        """Ask Gemini if the topic is CRI-related (~20 tokens).

        Returns warn result for off-topic, None for on-topic.
        Fail-open: on Gemini failure, returns None (input allowed through).

        Args:
            text: User input text.
            tenant: Tenant context for cost tracking.
            language: Detected language code.

        Returns:
            InputGuardResult with warn action if off-topic, None if on-topic.
        """
        try:
            request = GeminiRequest(
                contents=text,
                system_instruction=_TOPIC_SYSTEM_PROMPT,
                max_output_tokens=10,
                temperature=0.0,
            )
            response = await self._gemini.generate(request, tenant)
            answer = response.text.strip().lower()

            if "non" in answer:
                return InputGuardResult(
                    is_safe=False,
                    action="warn",
                    reason="Message appears to be off-topic for CRI services",
                    category="off_topic",
                )
            # "oui" or anything else → on-topic
            return None

        except Exception as exc:
            # Fail-open: if Gemini is down, skip topic check
            self._logger.warning(
                "topic_check_failed",
                error=str(exc),
                tenant=tenant.slug,
            )
            return None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_input_guard_service: InputGuardService | None = None


def get_input_guard_service() -> InputGuardService:
    """Get or create the InputGuardService singleton."""
    global _input_guard_service  # noqa: PLW0603
    if _input_guard_service is None:
        _input_guard_service = InputGuardService()
    return _input_guard_service
