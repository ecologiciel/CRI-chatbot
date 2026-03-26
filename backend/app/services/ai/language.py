"""Language detection service: FR, AR, EN.

Uses cost-ordered strategy:
1. Heuristic: Arabic Unicode character ratio (free, instant)
2. Heuristic: French vs English indicator words (free, instant)
3. Gemini fallback for ambiguous text (~10 tokens)
4. Default: French (most common for CRI users)
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from app.core.tenant import TenantContext
from app.models.enums import Language

logger = structlog.get_logger()

# ── Arabic Unicode ranges ──

_ARABIC_RANGES = (
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0xFB50, 0xFDFF),  # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),  # Arabic Presentation Forms-B
)

# ── Indicator word sets ──

_FRENCH_INDICATORS = frozenset({
    "le", "la", "les", "de", "du", "des", "un", "une",
    "et", "est", "en", "que", "qui", "dans", "pour",
    "sur", "avec", "par", "pas", "sont", "nous", "vous",
})

_ENGLISH_INDICATORS = frozenset({
    "the", "is", "are", "was", "were", "have", "has",
    "with", "this", "that", "for", "from", "not", "but",
    "they", "which", "will", "can", "been", "would",
})

# ── Thresholds ──

ARABIC_THRESHOLD = 0.30  # 30% of alphabetic chars must be Arabic
CONFIDENCE_RATIO = 2.0  # FR count must be > EN * 2 (or vice versa)
MIN_TEXT_LENGTH = 3  # Below this, default to FR


# ── Data class ──


@dataclass(frozen=True, slots=True)
class LanguageResult:
    """Result of language detection."""

    language: Language  # Language.fr, Language.ar, Language.en
    confidence: float  # 0.0 to 1.0
    method: str  # "heuristic_arabic", "heuristic_french", "heuristic_english", "gemini", "default"


# ── Service ──


class LanguageDetectionService:
    """Detects language using heuristics first, Gemini fallback for ambiguous text."""

    def __init__(self) -> None:
        self.logger = logger.bind(service="language_detection")

    async def detect(self, text: str, tenant: TenantContext) -> LanguageResult:
        """Detect the language of the input text.

        Strategy (ordered by cost):
        1. If text too short → default FR
        2. Arabic Unicode ratio check → AR
        3. French vs English indicator words → FR or EN
        4. Gemini fallback → any
        5. Final default → FR

        Args:
            text: Input text to analyze.
            tenant: Tenant context (needed for Gemini fallback billing).

        Returns:
            LanguageResult with language, confidence, and detection method.
        """
        stripped = text.strip()

        if len(stripped) < MIN_TEXT_LENGTH:
            return LanguageResult(
                language=Language.fr, confidence=0.5, method="default",
            )

        # Step 1: Arabic check
        arabic_result = self._detect_arabic(stripped)
        if arabic_result is not None:
            self.logger.debug(
                "language_detected",
                language="ar",
                method="heuristic_arabic",
                confidence=arabic_result.confidence,
                tenant=tenant.slug,
            )
            return arabic_result

        # Step 2: French vs English
        fr_en_result = self._detect_french_english(stripped)
        if fr_en_result is not None:
            self.logger.debug(
                "language_detected",
                language=fr_en_result.language.value,
                method=fr_en_result.method,
                confidence=fr_en_result.confidence,
                tenant=tenant.slug,
            )
            return fr_en_result

        # Step 3: Gemini fallback
        gemini_result = await self._gemini_detect(stripped, tenant)
        if gemini_result is not None:
            self.logger.info(
                "language_detected",
                language=gemini_result.language.value,
                method="gemini",
                tenant=tenant.slug,
            )
            return gemini_result

        # Step 4: Final default
        self.logger.debug(
            "language_default_fallback",
            tenant=tenant.slug,
            text_length=len(stripped),
        )
        return LanguageResult(
            language=Language.fr, confidence=0.3, method="default",
        )

    def _detect_arabic(self, text: str) -> LanguageResult | None:
        """Check if text contains significant Arabic characters.

        Returns LanguageResult if Arabic ratio >= ARABIC_THRESHOLD, else None.
        """
        arabic_count = 0
        alpha_count = 0

        for char in text:
            code = ord(char)
            is_arabic = any(start <= code <= end for start, end in _ARABIC_RANGES)
            if is_arabic:
                arabic_count += 1
                alpha_count += 1
            elif char.isalpha():
                alpha_count += 1

        if alpha_count == 0:
            return None

        ratio = arabic_count / alpha_count

        if ratio >= ARABIC_THRESHOLD:
            return LanguageResult(
                language=Language.ar,
                confidence=min(ratio, 1.0),
                method="heuristic_arabic",
            )

        return None

    def _detect_french_english(self, text: str) -> LanguageResult | None:
        """Count French and English indicator words.

        Returns LanguageResult if one language clearly dominates (2x ratio),
        else None (ambiguous).
        """
        words = set(text.lower().split())

        fr_count = len(words & _FRENCH_INDICATORS)
        en_count = len(words & _ENGLISH_INDICATORS)

        if fr_count == 0 and en_count == 0:
            return None

        if fr_count > 0 and (en_count == 0 or fr_count > en_count * CONFIDENCE_RATIO):
            return LanguageResult(
                language=Language.fr,
                confidence=0.85,
                method="heuristic_french",
            )

        if en_count > 0 and (fr_count == 0 or en_count > fr_count * CONFIDENCE_RATIO):
            return LanguageResult(
                language=Language.en,
                confidence=0.85,
                method="heuristic_english",
            )

        return None  # Ambiguous

    async def _gemini_detect(
        self, text: str, tenant: TenantContext,
    ) -> LanguageResult | None:
        """Fallback: ask Gemini to detect language (~10 tokens).

        Truncates input to 200 chars for cost efficiency.
        Returns None on any error (never breaks the pipeline).
        """
        try:
            # Local import to avoid circular dependency
            from app.services.ai.gemini import get_gemini_service

            gemini = get_gemini_service()
            system_prompt = (
                "Détecte la langue du texte suivant. "
                "Réponds UNIQUEMENT par un seul mot: fr, ar, ou en"
            )
            result = await gemini.generate_simple(
                prompt=text[:200],
                tenant=tenant,
                system_prompt=system_prompt,
            )

            detected = result.strip().lower()
            if detected in {"fr", "ar", "en"}:
                return LanguageResult(
                    language=Language(detected),
                    confidence=0.7,
                    method="gemini",
                )

            self.logger.warning(
                "gemini_language_unexpected",
                result=detected,
                tenant=tenant.slug,
            )
            return None

        except Exception as exc:
            self.logger.warning(
                "gemini_language_failed",
                error=str(exc),
                tenant=tenant.slug,
            )
            return None


# ── Singleton ──

_language_service: LanguageDetectionService | None = None


def get_language_service() -> LanguageDetectionService:
    """Get or create the singleton LanguageDetectionService."""
    global _language_service
    if _language_service is None:
        _language_service = LanguageDetectionService()
    return _language_service
