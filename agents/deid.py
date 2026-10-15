"""Best-effort scrubbing of identifying text before it is sent to an AI model.

This is a safety net, not a guarantee. Regexes catch structured identifiers
(phone numbers, emails, dates, addresses, long ID numbers) and we remove the
patient's own name and any names the caller supplies, but free-text names we
have no way to know about can still slip through. For production use, put a
managed de-identification service (e.g. Google Cloud Sensitive Data Protection)
in front of this and have the sponsor's compliance team review the result.

Clinical values (blood pressure like 120/80, SpO2 98, glucose 110, temperature
101.5) are deliberately left intact.
"""

from __future__ import annotations
import re
from typing import Callable, Iterable

_MONTHS = (
    "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    "sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)

# Order matters: more specific patterns first.
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[EMAIL]"),
    (re.compile(r"https?://\S+|www\.\S+", re.I), "[URL]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[ID]"),                                           # SSN
    (re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"), "[PHONE]"),
    (re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"), "[DATE]"),                           # 3/14/1948
    (re.compile(rf"\b(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b", re.I), "[DATE]"),
    (re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTHS})\.?(?:,?\s+\d{{4}})?\b", re.I), "[DATE]"),
    (re.compile(r"\b\d{1,6}\s+(?:[A-Z][\w.]*\s+){1,3}(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|court|ct|way|place|pl)\b\.?", re.I), "[ADDRESS]"),
    (re.compile(r"\b\d{5}(?:-\d{4})?\b"), "[ZIP]"),
    (re.compile(r"\b\d{7,}\b"), "[ID]"),                                                      # MRN-style numbers
    (re.compile(r"\b(?i:dr|doctor|nurse|mr|mrs|ms|miss)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"), "[NAME]"),
    (re.compile(r"\b(?i:my name is|i am called)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"), "[NAME]"),
]


def make_scrubber(known_names: Iterable[str] = ()) -> Callable[[str], str]:
    """Return a function that scrubs text. `known_names` are removed wherever they appear."""
    tokens: set[str] = set()
    for name in known_names:
        for part in re.split(r"\s+", (name or "").strip()):
            if len(part) >= 3:
                tokens.add(part)
    name_re = (
        re.compile(r"\b(?:" + "|".join(re.escape(t) for t in sorted(tokens, key=len, reverse=True)) + r")\b", re.I)
        if tokens else None
    )

    def scrub(text: str) -> str:
        for pattern, tag in _PATTERNS:
            text = pattern.sub(tag, text)
        if name_re:
            text = name_re.sub("[NAME]", text)
        return text

    return scrub
