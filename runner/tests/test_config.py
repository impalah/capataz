from __future__ import annotations

from pathlib import Path

import pytest

from capataz_runner.config import SecretNotFoundError, Settings, read_secret


def test_file_secrets_are_used_in_database_and_redis_urls(secrets_dir: Path) -> None:
    settings = Settings(secrets_dir=secrets_dir)
    assert "postgres-super-secret" in settings.database_url
    assert "redis-super-secret" in settings.redis_url
    assert settings.postgres_password.get_secret_value() == "postgres-super-secret"
    assert settings.redis_password.get_secret_value() == "redis-super-secret"
    assert settings.runner_ssh_private_key_path == secrets_dir / "runner_ssh_private_key"
    assert settings.runner_known_hosts_path == secrets_dir / "runner_known_hosts"
    assert settings.ansible_vault_password.get_secret_value() == "vault-super-secret"


def test_missing_or_empty_file_secret_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SecretNotFoundError):
        read_secret("missing", tmp_path)
    (tmp_path / "empty").write_text("\n", encoding="utf-8")
    with pytest.raises(SecretNotFoundError):
        read_secret("empty", tmp_path)


@pytest.mark.parametrize("field,value", [("env", "unsafe"), ("celery_concurrency", 0)])
def test_settings_reject_invalid_operational_values(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        Settings(**{field: value})


@pytest.mark.parametrize(
    "field",
    [
        "execution_timeout_seconds",
        "celery_soft_time_limit_seconds",
        "celery_hard_time_limit_seconds",
    ],
)
def test_settings_reject_non_positive_timeouts(field: str) -> None:
    with pytest.raises(ValueError):
        Settings(**{field: 0})


def test_settings_reject_soft_limit_not_below_hard_limit() -> None:
    """CR-085: soft must be strictly less than hard, or a soft-timeout can never fire first."""
    with pytest.raises(ValueError, match="strictly less than"):
        Settings(celery_soft_time_limit_seconds=960, celery_hard_time_limit_seconds=960)


def test_settings_reject_soft_limit_without_margin_over_max_action_timeout() -> None:
    """CR-085: reproduces the original CR-042 bug at Settings-construction time — a hard limit

    configured without headroom over actions.py's 900s max must fail fast at startup, not kill a
    long-running action's worker silently in production.
    """
    with pytest.raises(ValueError, match="MAX_ACTION_TIMEOUT_SECONDS"):
        Settings(celery_soft_time_limit_seconds=300, celery_hard_time_limit_seconds=330)


def test_settings_default_timeout_margins_are_internally_consistent() -> None:
    """The shipped defaults must satisfy the very validator introduced to police them."""
    settings = Settings()
    assert settings.celery_soft_time_limit_seconds < settings.celery_hard_time_limit_seconds
    assert settings.celery_soft_time_limit_seconds >= 900 + 2 * settings.termination_grace_seconds
