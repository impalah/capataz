import re
from typing import Any

SENSITIVE_KEY = re.compile(
    r"(secret|token|password|authorization|api[_-]?key|private[_-]?key|vault)", re.I
)
# The base64url alphabet a JWT segment (header/payload/signature) is written in.
_JWT_SEGMENT = r"[a-zA-Z0-9_=\-]+"
TOKEN_VALUE = re.compile(rf"(?i)(bearer\s+)[^\s]+|\b(?:eyJ{_JWT_SEGMENT}\.){{2}}{_JWT_SEGMENT}\b")


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
