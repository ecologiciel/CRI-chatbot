"""OutputGuardService — validate and sanitize LLM output before sending to user.

Pipeline:
1. PII masking — remove any PII that leaked into the LLM response
2. Confidence check — flag low-confidence responses
3. Tone check — detect informal language
4. Disclaimer — append if confidence is low
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog
from prometheus_client import Counter

from app.services.guardrails.pii_masker import get_pii_masker

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
GUARDRAIL_OUTPUT_CHECKS = Counter(
    "cri_guardrail_output_checks_total",
    "Total output guard checks",
    ["tenant", "result"],  # pass, flagged
)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutputGuardResult:
    """Result of output validation."""

    is_valid: bool  # True if output passes all checks (possibly with modifications)
    cleaned_text: str  # Output text after PII masking and corrections
    issues: list[str]  # List of issue descriptions found
    pii_masked_count: int  # Number of PII items masked in the output
    confidence_ok: bool  # Whether confidence met the threshold


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD = 0.7

# Informal/unprofessional language patterns
_INFORMAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Tutoiement (French informal "tu" verb forms)
    (re.compile(r"\btu\s+(?:es|as|veux|peux|dois|sais|fais|vas)\b", re.IGNORECASE), "tutoiement"),
    # Internet slang
    (re.compile(r"\b(?:mdr|lol|ptdr|omg|wtf|xd)\b", re.IGNORECASE), "internet_slang"),
    # Exclamation overuse (3+ exclamation marks)
    (re.compile(r"!{3,}"), "exclamation_overuse"),
]

# Trilingual disclaimers for low-confidence responses
_DISCLAIMERS = {
    "fr": (
        "\n\n_Cette information est fournie à titre indicatif. Pour des "
        "renseignements officiels, veuillez contacter votre CRI directement._"
    ),
    "ar": (
        "\n\n_هذه المعلومات إرشادية فقط. للحصول على معلومات رسمية، يرجى "
        "الاتصال بمركز الاستثمار الجهوي الخاص بكم._"
    ),
    "en": (
        "\n\n_This information is provided for guidance only. For official "
        "information, please contact your CRI directly._"
    ),
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class OutputGuardService:
    """Validate and sanitize LLM output before sending to the user.

    Steps (in order):
    1. PII masking — remove any PII that leaked into the LLM response
    2. Confidence check — flag low-confidence responses
    3. Tone check — detect informal language
    4. Disclaimer — append if confidence is low

    Thread-safe, async-only. Created once at startup, shared across requests.
    """

    def __init__(self) -> None:
        self._masker = get_pii_masker()
        self._logger = logger.bind(service="output_guard")

    async def check(
        self,
        text: str,
        confidence: float,
        language: str = "fr",
        tenant_slug: str = "",
    ) -> OutputGuardResult:
        """Validate and clean LLM output.

        Args:
            text: Raw LLM-generated text.
            confidence: RAG confidence score from retrieval [0.0, 1.0].
            language: Response language code (fr/ar/en).
            tenant_slug: Tenant slug for metrics labeling.

        Returns:
            OutputGuardResult with cleaned text and issue report.
        """
        issues: list[str] = []

        # 1. PII masking
        pii_result = self._masker.mask(text)
        cleaned = pii_result.masked_text

        if pii_result.pii_count > 0:
            issues.append(f"pii_found: {pii_result.pii_count} item(s) masked")

        # 2. Confidence check
        confidence_ok = confidence >= CONFIDENCE_THRESHOLD

        if not confidence_ok:
            issues.append(f"low_confidence: {confidence:.2f} < {CONFIDENCE_THRESHOLD}")
            disclaimer = self._get_disclaimer(language)
            cleaned = cleaned + disclaimer

        # 3. Tone check
        tone_issues = self._check_tone(cleaned)
        issues.extend(tone_issues)

        # Metrics and logging
        result_label = "pass" if not issues else "flagged"
        GUARDRAIL_OUTPUT_CHECKS.labels(tenant=tenant_slug, result=result_label).inc()

        if issues:
            self._logger.info(
                "output_flagged",
                issues=issues,
                pii_count=pii_result.pii_count,
                confidence=confidence,
            )

        return OutputGuardResult(
            is_valid=True,
            cleaned_text=cleaned,
            issues=issues,
            pii_masked_count=pii_result.pii_count,
            confidence_ok=confidence_ok,
        )

    def _check_tone(self, text: str) -> list[str]:
        """Detect informal language patterns.

        Args:
            text: Text to check for informal patterns.

        Returns:
            List of issue strings for each informal pattern found.
        """
        issues: list[str] = []
        for pattern, label in _INFORMAL_PATTERNS:
            if pattern.search(text):
                issues.append(f"informal_tone: {label}")
        return issues

    def _get_disclaimer(self, language: str) -> str:
        """Get the appropriate low-confidence disclaimer for the language.

        Args:
            language: Language code (fr/ar/en).

        Returns:
            Disclaimer text in the specified language (defaults to French).
        """
        return _DISCLAIMERS.get(language, _DISCLAIMERS["fr"])


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_output_guard_service: OutputGuardService | None = None


def get_output_guard_service() -> OutputGuardService:
    """Get or create the OutputGuardService singleton."""
    global _output_guard_service  # noqa: PLW0603
    if _output_guard_service is None:
        _output_guard_service = OutputGuardService()
    return _output_guard_service
