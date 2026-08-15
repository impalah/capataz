"""Unit tests for adapters/inbound/routers/deps.py's repo_dependency generator.

Every other deps.py function is already exercised indirectly through the router tests (which
override repo_dependency); this covers repo_dependency's own body directly with a fake
session/session_factory, since that's the one sanctioned place a real SqlAlchemyRepository is
constructed (see the import-linter exemption in pyproject.toml).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from capataz_api.adapters.inbound.routers.deps import repo_dependency
from capataz_api.infrastructure.database.repositories import SqlAlchemyRepository


class _FakeSessionCtx:
    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_repo_dependency_yields_repository_and_commits_on_success() -> None:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(session_factory=lambda: _FakeSessionCtx(session)))
    )

    agen = repo_dependency(request)
    repo = await agen.__anext__()
    assert isinstance(repo, SqlAlchemyRepository)
    assert repo.session is session

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_repo_dependency_rolls_back_and_reraises_on_failure() -> None:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(session_factory=lambda: _FakeSessionCtx(session)))
    )

    agen = repo_dependency(request)
    await agen.__anext__()

    with pytest.raises(RuntimeError, match="boom"):
        await agen.athrow(RuntimeError("boom"))
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
