"""Configuration and file-backed Docker secret access for the runner."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from urllib.parse import unquote, urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SecretNotFoundError(RuntimeError):
    """Raised when a required Docker secret is not mounted."""


def read_secret(name: str, secrets_dir: Path) -> SecretStr:
    """Read a non-empty secret from a Docker secrets file without logging it."""
    path = secrets_dir / name
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SecretNotFoundError(f"Required secret file is unavailable: {path}") from exc
    if not value:
        raise SecretNotFoundError(f"Required secret file is empty: {path}")
    return SecretStr(value)


class Settings(BaseSettings):
    """Non-sensitive settings are supplied with the CAPATAZ_ environment prefix."""

    model_config = SettingsConfigDict(env_prefix="CAPATAZ_", case_sensitive=False, extra="ignore")

    env: str = "development"
    log_level: str = "INFO"
    log_json: bool = False
    celery_queue: str = "automation"
    celery_concurrency: int = 2
    portainer_url: str = "https://portainer.home.arpa"
    http_timeout_seconds: float = 5.0
    # actions.py allow-lists action.timeout_seconds in [1, 900]; these three defaults keep enough
    # margin above that real max (a shipped example action already uses 600s) so that neither the
    # per-execution ceiling nor the Celery worker kill an action before its own timeout can fire.
    execution_timeout_seconds: int = 900
    celery_soft_time_limit_seconds: int = 930
    celery_hard_time_limit_seconds: int = 960
    # Grace window run_ansible_subprocess gives a timed-out process between SIGTERM and SIGKILL
    # (each direction, see _terminate_process_group in executor.py) — a Settings field, not a
    # hardcoded default, so the timeout-margin validator below can account for it explicitly
    # instead of assuming a number that lives only in executor.py (CR-085).
    termination_grace_seconds: float = 10.0
    project_root: Path = Path("/app")
    secrets_dir: Path = Field(default=Path("/run/secrets"))

    @field_validator("env")
    @classmethod
    def validate_env(cls, value: str) -> str:
        if value not in {"development", "production"}:
            raise ValueError("CAPATAZ_ENV must be development or production")
        return value

    @field_validator("celery_concurrency")
    @classmethod
    def validate_concurrency(cls, value: int) -> int:
        if value < 1:
            raise ValueError("CAPATAZ_CELERY_CONCURRENCY must be positive")
        return value

    @field_validator(
        "execution_timeout_seconds",
        "celery_soft_time_limit_seconds",
        "celery_hard_time_limit_seconds",
    )
    @classmethod
    def validate_positive_timeout(cls, value: int) -> int:
        if value < 1:
            raise ValueError("timeout/time-limit settings must be positive")
        return value

    @model_validator(mode="after")
    def validate_timeout_margins(self) -> Settings:
        # CR-085: CR-042 (a hardcoded Celery hard limit killing an action before its own timeout
        # could fire/clean up) must not be reintroducible just by misconfiguring these three
        # independently — fail fast at startup instead of failing silently in production.
        from capataz_runner.actions import MAX_ACTION_TIMEOUT_SECONDS

        if self.celery_soft_time_limit_seconds >= self.celery_hard_time_limit_seconds:
            raise ValueError(
                "celery_soft_time_limit_seconds must be strictly less than "
                "celery_hard_time_limit_seconds"
            )
        required_margin = MAX_ACTION_TIMEOUT_SECONDS + 2 * self.termination_grace_seconds
        if self.celery_soft_time_limit_seconds < required_margin:
            raise ValueError(
                "celery_soft_time_limit_seconds must exceed "
                f"MAX_ACTION_TIMEOUT_SECONDS ({MAX_ACTION_TIMEOUT_SECONDS}) + "
                f"2 * termination_grace_seconds ({self.termination_grace_seconds}) = "
                f"{required_margin}, got {self.celery_soft_time_limit_seconds}"
            )
        return self

    @cached_property
    def portainer_token(self) -> SecretStr:
        return read_secret("portainer_token", self.secrets_dir)

    @cached_property
    def runner_ssh_private_key_path(self) -> Path:
        path = self.secrets_dir / "runner_ssh_private_key"
        if not path.is_file():
            raise SecretNotFoundError(f"Required secret file is unavailable: {path}")
        return path

    @cached_property
    def runner_known_hosts_path(self) -> Path:
        path = self.secrets_dir / "runner_known_hosts"
        if not path.is_file():
            raise SecretNotFoundError(f"Required secret file is unavailable: {path}")
        return path

    @cached_property
    def ansible_vault_password(self) -> SecretStr:
        return read_secret("ansible_vault_password", self.secrets_dir)

    @cached_property
    def ansible_vault_password_path(self) -> Path:
        path = self.secrets_dir / "ansible_vault_password"
        if not path.is_file():
            raise SecretNotFoundError(f"Required secret file is unavailable: {path}")
        return path

    @cached_property
    def database_url(self) -> str:
        # The full DSN — including the password — is itself a Docker secret (rather than
        # assembled from separate CAPATAZ_POSTGRES_* parts plus a password secret): any
        # parameter that carries credentials is treated as sensitive in its entirety.
        return read_secret("database_url", self.secrets_dir).get_secret_value()

    @cached_property
    def redis_url(self) -> str:
        return read_secret("redis_url", self.secrets_dir).get_secret_value()

    @cached_property
    def postgres_password(self) -> SecretStr:
        return SecretStr(unquote(urlsplit(self.database_url).password or ""))

    @cached_property
    def redis_password(self) -> SecretStr:
        return SecretStr(unquote(urlsplit(self.redis_url).password or ""))
