import re
from typing import Any

SENSITIVE_KEY = re.compile(
    r"(secret|token|password|authorization|api[_-]?key|private[_-]?key|vault)", re.I
)
TOKEN_VALUE = re.compile(r"(?i)(bearer\s+)[^\s]+|\b(?:eyJ[a-zA-Z0-9_=\-]+\.){2}[a-zA-Z0-9_=\-]+\b")


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SENSITIVE_KEY.search(key) else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return TOKEN_VALUE.sub(r"\1[REDACTED]", value)
    return value
