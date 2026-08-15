"""Unit tests for infrastructure/database/session.py.

create_async_engine/async_sessionmaker don't connect until first use, so these can run
against a real (but never-contacted) sqlite+aiosqlite URL without needing a live database.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from capataz_api.core.settings import Settings
from capataz_api.infrastructure.database.session import (
    build_engine,
    build_session_factory,
    session_dependency,
)


def test_build_engine_uses_settings_database_url_and_pool_pre_ping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        Settings, "database_url", property(lambda self: "sqlite+aiosqlite:///:memory:")
    )
    settings = Settings()
    engine = build_engine(settings)
    assert isinstance(engine, AsyncEngine)
    # pool_pre_ping=True is forwarded straight to the sync pool underneath the async engine.
    assert engine.pool._pre_ping is True


def test_build_session_factory_returns_a_sessionmaker_with_expire_on_commit_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        Settings, "database_url", property(lambda self: "sqlite+aiosqlite:///:memory:")
    )
    engine = build_engine(Settings())
    factory = build_session_factory(engine)
    assert isinstance(factory, async_sessionmaker)
    assert factory.kw["expire_on_commit"] is False


@pytest.mark.asyncio
async def test_session_dependency_yields_a_session_from_the_factory() -> None:
    fake_session = MagicMock()

    class FakeCtx:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, *exc):
            return False

    factory = MagicMock(return_value=FakeCtx())

    agen = session_dependency(factory)
    session = await agen.__anext__()
    assert session is fake_session
    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()
