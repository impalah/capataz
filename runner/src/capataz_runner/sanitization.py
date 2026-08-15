"""Conservative redaction before data crosses the runner persistence boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "[REDACTED]"
SENSITIVE_KEY = re.compile(
    r"(secret|token|password|passwd|authorization|api[_-]?key|vault|private[_-]?key)", re.I
)
SENSITIVE_VALUE = re.compile(
    r"(?i)(bearer\s+)[^\s,;]+|(x-api-key\s*[:=]\s*)[^\s,;]+|"
    r"(password\s*[:=]\s*)[^\s,;]+|(ansible[_ -]?vault[^\n]*)"
)
# PostgreSQL text columns cannot store NUL and reject it at the wire protocol level; other C0
# control characters (besides tab/newline/carriage return) are similarly not meaningful text.
# Raw container/process output can legitimately contain these (e.g. Docker log framing noise).
UNSTORABLE_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def sanitize_text(value: str, known_secrets: Sequence[str] = ()) -> str:
    """Remove credential-shaped material and DB-unsafe bytes from a log string."""
    sanitized = UNSTORABLE_CONTROL_CHARS.sub("", value)
    for secret in known_secrets:
        if secret:
            sanitized = sanitized.replace(secret, REDACTED)
    return SENSITIVE_VALUE.sub(lambda match: f"{match.group(1) or ''}{REDACTED}", sanitized)


def sanitize_data(value: Any, known_secrets: Sequence[str] = ()) -> Any:
    """Recursively redact sensitive object members while preserving safe diagnostic metadata."""
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED
            if SENSITIVE_KEY.search(str(key))
            else sanitize_data(item, known_secrets)
            for key, item in value.items()
        }
    if isinstance(value, str):
        return sanitize_text(value, known_secrets)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [sanitize_data(item, known_secrets) for item in value]
    return value
