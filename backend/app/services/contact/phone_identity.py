"""Canonical comparison for already-international telephone identifiers.

This deliberately does not infer a country, strip punctuation or reinterpret
local numbers: doing so could join two different citizens' records.
"""

from __future__ import annotations

import re

_INTERNATIONAL = re.compile(r"^[+]?[1-9][0-9]{6,14}$", re.ASCII)


def phone_variants(phone: str) -> tuple[str, ...]:
    """Return the two supported spellings, or the original opaque value."""
    if not _INTERNATIONAL.fullmatch(phone):
        return (phone,)
    digits = phone.removeprefix("+")
    return (digits, f"+{digits}")
