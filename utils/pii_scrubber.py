"""
PII detection and scrubbing for GDPR compliance (Article 5 — data minimisation).
All text written to logs or audit trails passes through scrub() first.
Never store raw PII in logs — use scrub_dict() for structured data.
"""
import re
from typing import Any, Dict, List, Optional, Set, Union

# Regex patterns for common PII types — compiled once at import time
_PATTERNS: Dict[str, re.Pattern] = {
    "email":      re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    "phone_us":   re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "phone_intl": re.compile(r"\+\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}\b"),
    "ssn":        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card":re.compile(r"\b(?:\d[ \-]?){13,16}\b"),
}

# Keys in dicts that are always fully redacted regardless of value
_ALWAYS_REDACT: Set[str] = {
    "name", "full_name", "first_name", "last_name",
    "email", "phone", "address", "street", "city", "zip", "postal_code",
    "resume_text", "cover_letter_text",
    "api_key", "password", "token", "secret", "credential",
    "ssn", "dob", "date_of_birth",
}


def scrub(text: str, replacement: str = "[REDACTED]") -> str:
    """
    Remove known PII patterns from a string.
    Safe to call on any text before writing to logs.
    Returns the original string if no PII is found (no copy overhead).
    """
    if not text:
        return text
    for pii_type, pattern in _PATTERNS.items():
        text = pattern.sub(f"[{pii_type.upper()}_REDACTED]", text)
    return text


def scrub_dict(
    data: Dict[str, Any],
    sensitive_keys: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    Recursively scrub PII from a dict.
    - Keys in sensitive_keys (or _ALWAYS_REDACT) are fully replaced with '[REDACTED]'
    - String values are passed through scrub() to catch inline PII
    - Lists are processed element by element
    - Non-string scalar values (int, float, bool, None) are passed through unchanged
    """
    keys_to_redact = _ALWAYS_REDACT | (sensitive_keys or set())
    return _scrub_value(data, keys_to_redact)


def _scrub_value(value: Any, keys_to_redact: Set[str]) -> Any:
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if k.lower() in keys_to_redact else _scrub_value(v, keys_to_redact)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub_value(item, keys_to_redact) for item in value]
    if isinstance(value, str):
        return scrub(value)
    return value  # int, float, bool, None — pass through unchanged


def is_pii_free(text: str) -> bool:
    """Return True if no PII patterns are found in the text. Useful in tests."""
    return all(pattern.search(text) is None for pattern in _PATTERNS.values())
