from functools import lru_cache

from pydantic import AnyHttpUrl, Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # validate_assignment=True: the dev_mock/env invariant checked below must also hold after
    # construction (e.g. `settings.auth_mode = "dev_mock"` in a test or future dynamic
    # reconfiguration), not only when Settings() is first built (CR-027 in code-review-2026-08.md).
    model_config = SettingsConfigDict(
        env_prefix="CAPATAZ_", case_sensitive=False, extra="ignore", validate_assignment=True
    )
    env: str = "development"
    log_level: str = "INFO"
    log_json: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:8080"
    celery_queue: str = "automation"
    celery_concurrency: int = 2
    portainer_url: AnyHttpUrl | None = None
    grafana_url: AnyHttpUrl | None = None
    loki_url: AnyHttpUrl | None = None
    prometheus_url: AnyHttpUrl | None = None
    cognito_region: str = "eu-west-1"
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_uri: str = ""
    oidc_groups_claim: str = "groups"
    auth_mode: str = "cognito"
    initial_catalog_yaml_path: str | None = None
    http_timeout_seconds: float = Field(default=5, gt=0, le=60)
    health_allowed_host_suffixes: str = ".home.arpa"
    status_cache_ttl_seconds: int = Field(default=30, gt=0)

    @field_validator("auth_mode")
    @classmethod
    def development_mock_only(cls, value: str, info: ValidationInfo) -> str:
        # `env` must be declared before `auth_mode` in this class body: pydantic only populates
        # already-validated fields into info.data, in declaration order (CR-028).
        env = info.data.get("env", "development")
        if value not in {"cognito", "oidc", "dev_mock"}:
            raise ValueError("auth_mode must be cognito, oidc or dev_mock")
        if value == "dev_mock" and env != "development":
            raise ValueError(
                "dev_mock authentication is permitted only when CAPATAZ_ENV=development"
            )
        return value

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_cors_with_credentials(cls, value: str) -> str:
        # CORSMiddleware always sets allow_credentials=True (see bootstrap/factory.py), so a
        # literal wildcard origin would be both rejected by browsers and a real over-broadening.
        if any(item.strip() == "*" for item in value.split(",")):
            raise ValueError("cors_origins must not include '*' because credentials are allowed")
        return value

    @property
    def database_url(self) -> str:
        # The full DSN — including the password — is itself a Docker secret (rather than
        # assembled from separate CAPATAZ_POSTGRES_* parts plus a password secret): any
        # parameter that carries credentials is treated as sensitive in its entirety.
        from capataz_api.infrastructure.secrets.file_secret_reader import read_secret

        url = read_secret("database_url")
        assert url is not None  # required=True (the default) never returns None
        return url

    @property
    def redis_url(self) -> str:
        from capataz_api.infrastructure.secrets.file_secret_reader import read_secret

        url = read_secret("redis_url")
        assert url is not None  # required=True (the default) never returns None
        return url

    @property
    def health_suffixes(self) -> tuple[str, ...]:
        return tuple(
            item.strip().lower()
            for item in self.health_allowed_host_suffixes.split(",")
            if item.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
