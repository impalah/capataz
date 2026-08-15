"""Unit tests for core/settings.py's validators and secret-backed properties."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from capataz_api.core.settings import Settings, get_settings
from capataz_api.domain.exceptions import ConfigurationError


def test_dev_mock_is_rejected_outside_development_env() -> None:
    with pytest.raises(ValidationError, match="permitted only when CAPATAZ_ENV=development"):
        Settings(auth_mode="dev_mock", env="production")


def test_dev_mock_is_accepted_in_development_env() -> None:
    settings = Settings(auth_mode="dev_mock", env="development")
    assert settings.auth_mode == "dev_mock"


def test_invalid_auth_mode_is_rejected() -> None:
    with pytest.raises(ValidationError, match="auth_mode must be cognito, oidc or dev_mock"):
        Settings(auth_mode="basic")


def test_cors_wildcard_is_rejected_because_credentials_are_always_allowed() -> None:
    with pytest.raises(ValidationError, match="cors_origins must not include"):
        Settings(cors_origins="*")


def test_cors_wildcard_among_multiple_origins_is_also_rejected() -> None:
    with pytest.raises(ValidationError, match="cors_origins must not include"):
        Settings(cors_origins="https://a.home.arpa, *")


def test_cors_origins_without_wildcard_is_accepted() -> None:
    settings = Settings(cors_origins="https://a.home.arpa,https://b.home.arpa")
    assert settings.cors_origins == "https://a.home.arpa,https://b.home.arpa"


def test_validate_assignment_reruns_dev_mock_validator_after_construction() -> None:
    # auth_mode must be passed explicitly (not left to the ambient CAPATAZ_AUTH_MODE env var,
    # which CI sets to dev_mock for other tests) so construction itself doesn't fail here.
    settings = Settings(auth_mode="cognito", env="production")
    with pytest.raises(ValidationError, match="permitted only when CAPATAZ_ENV=development"):
        settings.auth_mode = "dev_mock"


def test_database_url_reads_docker_secret_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "database_url").write_text("postgresql+asyncpg://user:pass@db/capataz\n")
    monkeypatch.setattr(
        "capataz_api.infrastructure.secrets.file_secret_reader.FileSecretReader.__init__",
        lambda self, directory=tmp_path: setattr(self, "directory", tmp_path),
    )
    settings = Settings()
    assert settings.database_url == "postgresql+asyncpg://user:pass@db/capataz"


def test_redis_url_reads_docker_secret_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "redis_url").write_text("redis://redis:6379/0\n")
    monkeypatch.setattr(
        "capataz_api.infrastructure.secrets.file_secret_reader.FileSecretReader.__init__",
        lambda self, directory=tmp_path: setattr(self, "directory", tmp_path),
    )
    settings = Settings()
    assert settings.redis_url == "redis://redis:6379/0"


def test_missing_database_url_secret_raises_configuration_error(tmp_path: Path) -> None:
    settings = Settings()
    from capataz_api.infrastructure.secrets.file_secret_reader import FileSecretReader

    # No file created under tmp_path: exercises the "required secret is not mounted" branch.
    reader = FileSecretReader(tmp_path)
    with pytest.raises(ConfigurationError, match="not mounted"):
        reader.read("database_url")
    # Sanity: the property itself surfaces the same failure mode against the real /run/secrets
    # default location, which is not mounted in the unit-test environment either.
    with pytest.raises(ConfigurationError):
        _ = settings.database_url


def test_health_suffixes_splits_and_normalises_case_and_whitespace() -> None:
    settings = Settings(health_allowed_host_suffixes=" .Home.arpa , .example.com,, ")
    assert settings.health_suffixes == (".home.arpa", ".example.com")


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
