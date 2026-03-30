"""PIIMasker — detect and mask Moroccan PII patterns via compiled regex.

Synchronous, stateless, thread-safe. Created once at startup, shared across requests.
Masks CIN, phone numbers, emails, amounts (MAD/DH), IBAN, and dossier numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PIIMatch:
    """A single detected PII occurrence."""

    original: str  # The actual PII value found, e.g. "AB123456"
    masked: str  # The replacement token, e.g. "[CIN_1]"
    pii_type: str  # "cin", "phone", "email", "amount", "iban", "dossier"
    start: int  # Start position in the *original* text
    end: int  # End position in the *original* text


@dataclass(frozen=True, slots=True)
class PIIMaskResult:
    """Result of a PII masking operation."""

    masked_text: str  # Text with PII replaced by tokens
    pii_found: list[PIIMatch]  # All PII occurrences detected
    pii_count: int  # Total count of PII items found


# ---------------------------------------------------------------------------
# Compiled regex patterns (module-level for performance)
# ---------------------------------------------------------------------------

# Moroccan CIN: 1-2 uppercase letters + 5-6 digits (e.g. AB123456, Z12345)
_CIN_RE = re.compile(r"\b[A-Z]{1,2}\d{5,6}\b")

# Moroccan IBAN: MA + 2 check digits + 24 alphanumeric (checked before phone)
_IBAN_RE = re.compile(r"\bMA\d{2}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}\b")

# Moroccan phone: +212 or 0 prefix, then 6 or 7, then 8 digits
# Handles: +212612345678, +212 6 12 34 56 78, 0612345678, 06-12-34-56-78
_PHONE_RE = re.compile(r"(?:\+212[\s.-]?|0)[67][\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2}\b")

# Standard email
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Amounts in dirhams: digits followed by MAD, DH, or dirhams
_AMOUNT_RE = re.compile(r"\b\d[\d\s.,]*\s*(?:MAD|DH|dirhams?)\b", re.IGNORECASE)

# CRI dossier/file numbers: RC-12345, INV-2024-001, DOS-20240001, DSR/12345
_DOSSIER_RE = re.compile(r"\b(?:RC|INV|DOS|DSR|D)[-/]\d{4,}(?:[-/]\d+)*\b", re.IGNORECASE)

# Ordered list: (regex, type_label). Order matters for overlap resolution.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (_CIN_RE, "cin"),
    (_IBAN_RE, "iban"),
    (_PHONE_RE, "phone"),
    (_EMAIL_RE, "email"),
    (_AMOUNT_RE, "amount"),
    (_DOSSIER_RE, "dossier"),
]


# ---------------------------------------------------------------------------
# PIIMasker service
# ---------------------------------------------------------------------------


class PIIMasker:
    """Detect and mask Moroccan PII patterns via compiled regex.

    Thread-safe, synchronous. Uses right-to-left replacement to preserve
    match positions when multiple PII items are found in the same text.
    """

    def __init__(self) -> None:
        self._logger = logger.bind(service="pii_masker")

    def mask(self, text: str) -> PIIMaskResult:
        """Detect and mask all PII in the input text.

        Replaces each PII occurrence with a type-indexed token: [CIN_1], [PHONE_1], etc.

        Args:
            text: Input text to scan for PII.

        Returns:
            PIIMaskResult with masked text, list of matches, and count.
        """
        if not text:
            return PIIMaskResult(masked_text=text, pii_found=[], pii_count=0)

        # Collect all matches across all patterns
        raw_matches: list[tuple[int, int, str, str]] = []  # (start, end, original, type)

        for pattern, pii_type in _PATTERNS:
            for match in pattern.finditer(text):
                raw_matches.append((match.start(), match.end(), match.group(), pii_type))

        if not raw_matches:
            return PIIMaskResult(masked_text=text, pii_found=[], pii_count=0)

        # Sort by start position, then longest match first for overlap resolution
        raw_matches.sort(key=lambda m: (m[0], -(m[1] - m[0])))

        # Remove overlapping matches (keep the first/longest at each position)
        filtered: list[tuple[int, int, str, str]] = []
        last_end = -1
        for start, end, original, pii_type in raw_matches:
            if start >= last_end:
                filtered.append((start, end, original, pii_type))
                last_end = end

        # Build replacement tokens with per-type counters
        type_counters: dict[str, int] = {}
        pii_found: list[PIIMatch] = []
        replacements: list[tuple[int, int, str]] = []  # (start, end, token)

        for start, end, original, pii_type in filtered:
            type_counters[pii_type] = type_counters.get(pii_type, 0) + 1
            token = f"[{pii_type.upper()}_{type_counters[pii_type]}]"
            pii_found.append(
                PIIMatch(
                    original=original,
                    masked=token,
                    pii_type=pii_type,
                    start=start,
                    end=end,
                )
            )
            replacements.append((start, end, token))

        # Replace right-to-left to preserve earlier positions
        masked = text
        for start, end, token in reversed(replacements):
            masked = masked[:start] + token + masked[end:]

        self._logger.info(
            "pii_masked",
            count=len(pii_found),
            types=[m.pii_type for m in pii_found],
        )

        return PIIMaskResult(
            masked_text=masked,
            pii_found=pii_found,
            pii_count=len(pii_found),
        )

    def unmask(self, masked_text: str, pii_found: list[PIIMatch]) -> str:
        """Restore original PII values in masked text.

        For admin back-office display only — NEVER for external output.

        Args:
            masked_text: Text containing [TYPE_N] tokens.
            pii_found: The PIIMatch list from a previous mask() call.

        Returns:
            Text with tokens replaced by original PII values.
        """
        result = masked_text
        for match in pii_found:
            result = result.replace(match.masked, match.original, 1)
        return result


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_pii_masker: PIIMasker | None = None


def get_pii_masker() -> PIIMasker:
    """Get or create the PIIMasker singleton."""
    global _pii_masker  # noqa: PLW0603
    if _pii_masker is None:
        _pii_masker = PIIMasker()
    return _pii_masker
