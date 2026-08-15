from __future__ import annotations

from capataz_runner.sanitization import REDACTED, sanitize_data, sanitize_text


def test_sanitize_text_removes_tokens_vault_and_known_secret() -> None:
    text = "Bearer abc.def token=ignored password=hunter2 $ANSIBLE_VAULT;1.1;AES256 postgres-super-secret"
    sanitized = sanitize_text(text, ("postgres-super-secret",))
    assert "abc.def" not in sanitized
    assert "hunter2" not in sanitized
    assert "postgres-super-secret" not in sanitized
    assert "ANSIBLE_VAULT" not in sanitized
    assert REDACTED in sanitized


def test_sanitize_text_strips_nul_and_control_bytes_postgres_cannot_store() -> None:
    text = "line one\x00\x00\x00[GIN] 200 | 127.0.0.1 | GET /api/tags\nline\x0btwo\ttab\rcr"
    sanitized = sanitize_text(text)
    assert "\x00" not in sanitized
    assert "\x0b" not in sanitized
    assert "[GIN] 200" in sanitized
    assert "\n" in sanitized and "\t" in sanitized and "\r" in sanitized


def test_sanitize_data_redacts_sensitive_keys_recursively() -> None:
    payload = {
        "token": "do-not-store",
        "nested": {"private_key": "never", "message": "safe"},
        "items": [{"password": "nope"}],
    }
    assert sanitize_data(payload) == {
        "token": REDACTED,
        "nested": {"private_key": REDACTED, "message": "safe"},
        "items": [{"password": REDACTED}],
    }
