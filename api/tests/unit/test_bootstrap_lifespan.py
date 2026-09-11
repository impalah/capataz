"""Unit tests for bootstrap/lifespan.py: verifies app.state wiring without a real Postgres/Redis.

`build_engine`, `Redis.from_url` and `CeleryExecutionPublisher` are monkeypatched so the lifespan
context manager can run end to end and be asserted on, entirely in-process.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from capataz_api.adapters.outbound.connector_factory import DefaultConnectorClientFactory
from capataz_api.bootstrap import lifespan as lifespan_module
from capataz_api.core.settings import Settings
from capataz_api.domain.exceptions import ConfigurationError
from capataz_api.infrastructure.crypto import FernetResourceCipher
from capataz_api.infrastructure.resources import FileSystemResourceSourceLoader

MASTER_KEY = "8tqAJmPr27f8r7U4yZZMgMC8TR44rrc-Zdrdru4ONDo="


@pytest.fixture(autouse=True)
def _fake_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    # Settings.redis_url reads the redis_url Docker secret lazily through file_secret_reader.
    monkeypatch.setattr(
        "capataz_api.infrastructure.secrets.file_secret_reader.read_secret",
        lambda name, required=True: "redis://fake:6379/0",
    )
    # lifespan binds read_secret at import time and only reads the master key through it.
    monkeypatch.setattr(
        lifespan_module,
        "read_secret",
        lambda name, required=True: MASTER_KEY if name == "resources_master_key" else None,
    )


def _patch_infrastructure(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr(lifespan_module, "build_engine", lambda settings: fake_engine)
    monkeypatch.setattr(lifespan_module, "build_session_factory", lambda engine: MagicMock())
    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()
    monkeypatch.setattr(lifespan_module.Redis, "from_url", lambda *a, **k: fake_redis)
    monkeypatch.setattr(lifespan_module, "CeleryExecutionPublisher", lambda *a, **k: MagicMock())
    return fake_engine, fake_redis


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "auth_mode": "dev_mock",
        "env": "development",
        "initial_catalog_yaml_path": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_lifespan_wires_dev_mock_cipher_connectors_and_disposes_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine, fake_redis = _patch_infrastructure(monkeypatch)
    app = FastAPI()
    app.state.configured_settings = _settings(resources_dir=Path("/srv/capataz-resources"))

    async with lifespan_module.lifespan(app):
        assert app.state.identity_provider.__class__.__name__ == "DevMockIdentityProvider"
        assert app.state.engine is fake_engine
        assert isinstance(app.state.resource_cipher, FernetResourceCipher)
        assert isinstance(app.state.status_service.factory, DefaultConnectorClientFactory)
        context = app.state.catalog_context
        assert context.cipher is app.state.resource_cipher
        assert isinstance(context.loader, FileSystemResourceSourceLoader)
        assert context.inline_permitted is True  # development
        assert context.allowed_suffixes == app.state.settings.health_suffixes

    fake_redis.aclose.assert_awaited_once()
    fake_engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_refuses_inline_resources_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_infrastructure(monkeypatch)
    app = FastAPI()
    app.state.configured_settings = _settings(auth_mode="cognito", env="production")
    async with lifespan_module.lifespan(app):
        assert app.state.catalog_context.inline_permitted is False


@pytest.mark.asyncio
async def test_lifespan_fails_fast_without_the_resources_master_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_infrastructure(monkeypatch)

    def missing(name: str, required: bool = True) -> str:
        raise ConfigurationError(f"Required secret {name!r} is not mounted")

    monkeypatch.setattr(lifespan_module, "read_secret", missing)
    app = FastAPI()
    app.state.configured_settings = _settings()
    with pytest.raises(ConfigurationError, match="resources_master_key"):
        async with lifespan_module.lifespan(app):
            pass


@pytest.mark.asyncio
async def test_lifespan_selects_oidc_provider_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_infrastructure(monkeypatch)
    app = FastAPI()
    app.state.configured_settings = _settings(
        auth_mode="oidc",
        oidc_issuer="https://idp.home.arpa/application/o/capataz/",
        oidc_audience="capataz-client",
    )
    async with lifespan_module.lifespan(app):
        assert app.state.identity_provider.__class__.__name__ == "OidcIdentityProvider"


@pytest.mark.asyncio
async def test_lifespan_selects_cognito_provider_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_infrastructure(monkeypatch)
    app = FastAPI()
    app.state.configured_settings = _settings(auth_mode="cognito")
    async with lifespan_module.lifespan(app):
        assert app.state.identity_provider.__class__.__name__ == "CognitoIdentityProvider"


class _FakeSessionCtx:
    def __init__(self, session: MagicMock) -> None:
        self.session = session

    async def __aenter__(self) -> MagicMock:
        return self.session

    async def __aexit__(self, *exc: object) -> bool:
        return False


@pytest.mark.asyncio
async def test_lifespan_imports_initial_catalog_with_the_catalog_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_infrastructure(monkeypatch)
    session = MagicMock()
    session.commit = AsyncMock()
    monkeypatch.setattr(
        lifespan_module, "build_session_factory", lambda engine: lambda: _FakeSessionCtx(session)
    )
    calls: list[tuple[str, object]] = []

    async def fake_import(repo: object, path: str, context: object) -> None:
        calls.append((path, context))

    monkeypatch.setattr(lifespan_module, "import_startup_catalog", fake_import)
    catalog_path = tmp_path / "catalog.yml"
    catalog_path.write_text("version: 2\n")
    app = FastAPI()
    app.state.configured_settings = _settings(initial_catalog_yaml_path=str(catalog_path))

    async with lifespan_module.lifespan(app):
        assert calls == [(str(catalog_path), app.state.catalog_context)]
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_rolls_back_and_reraises_when_initial_catalog_import_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_infrastructure(monkeypatch)
    session = MagicMock()
    session.rollback = AsyncMock()
    monkeypatch.setattr(
        lifespan_module, "build_session_factory", lambda engine: lambda: _FakeSessionCtx(session)
    )

    async def failing_import(repo: object, path: str, context: object) -> None:
        raise RuntimeError("bad catalog")

    monkeypatch.setattr(lifespan_module, "import_startup_catalog", failing_import)
    catalog_path = tmp_path / "catalog.yml"
    catalog_path.write_text("version: 2\n")
    app = FastAPI()
    app.state.configured_settings = _settings(initial_catalog_yaml_path=str(catalog_path))

    with pytest.raises(RuntimeError, match="bad catalog"):
        async with lifespan_module.lifespan(app):
            pass
    session.rollback.assert_awaited_once()
