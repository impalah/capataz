"""Unit tests for bootstrap/lifespan.py: verifies app.state wiring without a real Postgres/Redis.

`create_async_engine`, `Redis.from_url` and `CeleryExecutionPublisher` are monkeypatched so the
lifespan context manager can run end to end and be asserted on, entirely in-process.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from capataz_api.bootstrap import lifespan as lifespan_module
from capataz_api.core.settings import Settings


@pytest.fixture(autouse=True)
def _fake_redis_url_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    # Settings.redis_url reads a Docker secret file (required=True); lifespan() always reads it
    # to build the Redis client, so every test in this module needs it stubbed out.
    monkeypatch.setattr(
        "capataz_api.infrastructure.secrets.file_secret_reader.read_secret",
        lambda name, required=True: "redis://fake:6379/0",
    )


def _settings(**overrides: object) -> Settings:
    return Settings(auth_mode="dev_mock", env="development", **overrides)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_lifespan_wires_dev_mock_provider_and_disposes_resources_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr(lifespan_module, "build_engine", lambda settings: fake_engine)
    monkeypatch.setattr(lifespan_module, "build_session_factory", lambda engine: MagicMock())

    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()
    monkeypatch.setattr(lifespan_module.Redis, "from_url", lambda *a, **k: fake_redis)

    fake_publisher = MagicMock()
    monkeypatch.setattr(lifespan_module, "CeleryExecutionPublisher", lambda *a, **k: fake_publisher)

    app = FastAPI()
    app.state.configured_settings = _settings(portainer_url=None, initial_catalog_yaml_path=None)

    async with lifespan_module.lifespan(app):
        assert app.state.identity_provider.__class__.__name__ == "DevMockIdentityProvider"
        assert app.state.queue is fake_publisher
        assert app.state.engine is fake_engine
        assert app.state.status_service is not None

    fake_redis.aclose.assert_awaited_once()
    fake_engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_selects_oidc_provider_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr(lifespan_module, "build_engine", lambda settings: fake_engine)
    monkeypatch.setattr(lifespan_module, "build_session_factory", lambda engine: MagicMock())

    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()
    monkeypatch.setattr(lifespan_module.Redis, "from_url", lambda *a, **k: fake_redis)
    monkeypatch.setattr(lifespan_module, "CeleryExecutionPublisher", lambda *a, **k: MagicMock())

    app = FastAPI()
    app.state.configured_settings = Settings(
        auth_mode="oidc",
        oidc_issuer="https://idp.home.arpa/application/o/capataz/",
        oidc_audience="capataz-client",
        portainer_url=None,
        initial_catalog_yaml_path=None,
    )

    async with lifespan_module.lifespan(app):
        assert app.state.identity_provider.__class__.__name__ == "OidcIdentityProvider"


@pytest.mark.asyncio
async def test_lifespan_selects_cognito_provider_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr(lifespan_module, "build_engine", lambda settings: fake_engine)
    monkeypatch.setattr(lifespan_module, "build_session_factory", lambda engine: MagicMock())

    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()
    monkeypatch.setattr(lifespan_module.Redis, "from_url", lambda *a, **k: fake_redis)
    monkeypatch.setattr(lifespan_module, "CeleryExecutionPublisher", lambda *a, **k: MagicMock())

    app = FastAPI()
    app.state.configured_settings = Settings(
        auth_mode="cognito", portainer_url=None, initial_catalog_yaml_path=None
    )

    async with lifespan_module.lifespan(app):
        assert app.state.identity_provider.__class__.__name__ == "CognitoIdentityProvider"


@pytest.mark.asyncio
async def test_lifespan_wires_portainer_platform_when_url_and_token_are_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr(lifespan_module, "build_engine", lambda settings: fake_engine)
    monkeypatch.setattr(lifespan_module, "build_session_factory", lambda engine: MagicMock())

    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()
    monkeypatch.setattr(lifespan_module.Redis, "from_url", lambda *a, **k: fake_redis)
    monkeypatch.setattr(lifespan_module, "CeleryExecutionPublisher", lambda *a, **k: MagicMock())
    monkeypatch.setattr(lifespan_module, "read_secret", lambda name, required=True: "token-123")

    captured: dict[str, object] = {}

    class FakePortainerClient:
        def __init__(self, url: str, token: str, timeout: float) -> None:
            captured["url"] = url
            captured["token"] = token

    monkeypatch.setattr(lifespan_module, "PortainerClient", FakePortainerClient)

    app = FastAPI()
    app.state.configured_settings = _settings(
        portainer_url="https://portainer.home.arpa", initial_catalog_yaml_path=None
    )

    async with lifespan_module.lifespan(app):
        assert app.state.status_service.platform is not None
        assert captured["token"] == "token-123"


@pytest.mark.asyncio
async def test_lifespan_leaves_platform_none_when_portainer_token_secret_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr(lifespan_module, "build_engine", lambda settings: fake_engine)
    monkeypatch.setattr(lifespan_module, "build_session_factory", lambda engine: MagicMock())

    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()
    monkeypatch.setattr(lifespan_module.Redis, "from_url", lambda *a, **k: fake_redis)
    monkeypatch.setattr(lifespan_module, "CeleryExecutionPublisher", lambda *a, **k: MagicMock())
    # required=False and no secret mounted: read_secret legitimately returns None here.
    monkeypatch.setattr(lifespan_module, "read_secret", lambda name, required=True: None)

    app = FastAPI()
    app.state.configured_settings = _settings(
        portainer_url="https://portainer.home.arpa", initial_catalog_yaml_path=None
    )

    async with lifespan_module.lifespan(app):
        assert app.state.status_service.platform is None


@pytest.mark.asyncio
async def test_lifespan_imports_initial_catalog_when_path_is_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr(lifespan_module, "build_engine", lambda settings: fake_engine)

    class FakeSessionCtx:
        async def __aenter__(self):
            session = MagicMock()
            session.commit = AsyncMock()
            return session

        async def __aexit__(self, *exc):
            return False

    def fake_session_factory():
        return FakeSessionCtx()

    monkeypatch.setattr(
        lifespan_module, "build_session_factory", lambda engine: fake_session_factory
    )

    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()
    monkeypatch.setattr(lifespan_module.Redis, "from_url", lambda *a, **k: fake_redis)
    monkeypatch.setattr(lifespan_module, "CeleryExecutionPublisher", lambda *a, **k: MagicMock())

    catalog_path = tmp_path / "catalog.yml"
    catalog_path.write_text("version: 1\nservices: []\n")

    calls: list[str] = []

    async def fake_import(repo, path) -> None:
        calls.append(path)

    monkeypatch.setattr(lifespan_module, "import_startup_catalog", fake_import)

    app = FastAPI()
    app.state.configured_settings = _settings(
        portainer_url=None, initial_catalog_yaml_path=str(catalog_path)
    )

    async with lifespan_module.lifespan(app):
        pass

    assert calls == [str(catalog_path)]


@pytest.mark.asyncio
async def test_lifespan_rolls_back_and_reraises_when_initial_catalog_import_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr(lifespan_module, "build_engine", lambda settings: fake_engine)

    session = MagicMock()
    session.rollback = AsyncMock()

    class FakeSessionCtx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(
        lifespan_module, "build_session_factory", lambda engine: lambda: FakeSessionCtx()
    )

    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()
    monkeypatch.setattr(lifespan_module.Redis, "from_url", lambda *a, **k: fake_redis)
    monkeypatch.setattr(lifespan_module, "CeleryExecutionPublisher", lambda *a, **k: MagicMock())

    catalog_path = tmp_path / "catalog.yml"
    catalog_path.write_text("version: 1\nservices: []\n")

    async def failing_import(repo, path) -> None:
        raise RuntimeError("bad catalog")

    monkeypatch.setattr(lifespan_module, "import_startup_catalog", failing_import)

    app = FastAPI()
    app.state.configured_settings = _settings(
        portainer_url=None, initial_catalog_yaml_path=str(catalog_path)
    )

    with pytest.raises(RuntimeError, match="bad catalog"):
        async with lifespan_module.lifespan(app):
            pass

    session.rollback.assert_awaited_once()
