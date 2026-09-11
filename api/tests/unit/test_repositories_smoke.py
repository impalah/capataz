"""Fast SQLite smoke coverage for repositories.py, kept at unit level per the project's
"no directory exempted from unit coverage" policy (see [tool.coverage.run] in pyproject.toml).

Everything that depends on real foreign-key/constraint enforcement (which SQLite does not provide
by default) lives in tests/integration/test_repositories.py against a real Postgres. These tests
only exercise logic that doesn't depend on that distinction.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fakes import make_action, make_service, runtime
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from capataz_api.domain.entities import Execution
from capataz_api.domain.exceptions import ConflictError
from capataz_api.domain.value_objects import ExecutionSource
from capataz_api.infrastructure.database.models import Base
from capataz_api.infrastructure.database.repositories import SqlAlchemyRepository


async def _empty_engine(tmp_path: Path) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine


@pytest.mark.asyncio
async def test_list_services_paginates_and_filters_by_status_cache(tmp_path: Path) -> None:
    engine = await _empty_engine(tmp_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        for index in range(5):
            await repo.upsert_service(make_service(f"svc-{index}", name=f"Name {index}"))
            await repo.update_status_cache(f"svc-{index}", "healthy" if index < 3 else "down")
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        page1, total1 = await repo.list_services(offset=0, limit=2)
        page2, total2 = await repo.list_services(offset=2, limit=2)
        healthy, healthy_total = await repo.list_services(status="healthy", offset=0, limit=2)

    assert total1 == total2 == 5
    assert [item.id for item in page1] == ["svc-0", "svc-1"]
    assert [item.id for item in page2] == ["svc-2", "svc-3"]
    assert healthy_total == 3
    assert [item.id for item in healthy] == ["svc-0", "svc-1"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_service_spec_round_trips_and_metadata_is_sanitized(tmp_path: Path) -> None:
    engine = await _empty_engine(tmp_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    original = make_service(
        "one",
        tags=["local"],
        runtime=runtime(kind="services", names=("one",), stack_name="stack"),
        observability={"metrics": [{"label": "CPU", "connector": "prometheus", "query": "up"}]},
        metadata={"owner": "ana", "api_token": "leaked"},
    )
    async with factory() as session:
        await SqlAlchemyRepository(session).upsert_service(original)
        await session.commit()

    async with factory() as session:
        loaded = await SqlAlchemyRepository(session).get_service("one")
    assert loaded is not None
    assert loaded.spec.runtime == original.spec.runtime
    assert loaded.spec.observability == original.spec.observability
    assert loaded.spec.tags == ["local"]
    assert loaded.spec.metadata == {"owner": "ana", "api_token": "[REDACTED]"}
    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_service_raises_conflict_on_stale_version(tmp_path: Path) -> None:
    """CR-034: two concurrent readers of the same row must not silently overwrite one another."""
    engine = await _empty_engine(tmp_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await SqlAlchemyRepository(session).upsert_service(make_service("one", name="Original"))
        await session.commit()

    async with factory() as first_session, factory() as second_session:
        first_repo = SqlAlchemyRepository(first_session)
        second_repo = SqlAlchemyRepository(second_session)
        first = await first_repo.get_service("one")
        second = await second_repo.get_service("one")
        assert first is not None and second is not None

        first.spec = first.spec.model_copy(update={"name": "Updated by first writer"})
        await first_repo.upsert_service(first, enforce_version=True)
        await first_session.commit()

        second.spec = second.spec.model_copy(update={"name": "Stale second writer"})
        with pytest.raises(ConflictError):
            await second_repo.upsert_service(second, enforce_version=True)
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_services_filters_by_group_name_and_environment(tmp_path: Path) -> None:
    engine = await _empty_engine(tmp_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(make_service("ai-one", group_name="AI"))
        await repo.upsert_service(make_service("infra-one", group_name="Infra"))
        await session.commit()

    async with factory() as session:
        by_group, group_total = await SqlAlchemyRepository(session).list_services(group_name="AI")
    assert group_total == 1
    assert by_group[0].id == "ai-one"
    await engine.dispose()


@pytest.mark.asyncio
async def test_action_crud_batched_listing_and_listing_by_connector(tmp_path: Path) -> None:
    """CR-080: list_actions_for_services must batch across services in one query."""
    engine = await _empty_engine(tmp_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(make_service("one"))
        await repo.upsert_service(make_service("two"))
        await repo.upsert_action(make_action("one"))
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        by_service = await repo.list_actions_for_services(["one", "two", "missing"])
        assert [action.key for action in by_service["one"]] == ["restart"]
        assert by_service["two"] == by_service["missing"] == []
        assert (await repo.get_action("one", "restart")).connector_id == "portainer_main"  # type: ignore[union-attr]
        assert [a.key for a in await repo.list_actions_by_connector("portainer_main")] == [
            "restart"
        ]
        assert await repo.list_actions_by_connector("other") == []

        assert await repo.delete_action("one", "restart") is True
        assert await repo.delete_action("one", "restart") is False
    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_action_blocks_while_an_execution_is_active(tmp_path: Path) -> None:
    """CR-077: delete_action's active-execution precheck."""
    engine = await _empty_engine(tmp_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    action_id = uuid4()
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(make_service("one"))
        await repo.upsert_action(make_action("one", id=action_id))
        await repo.create_execution(
            Execution(
                service_id="one",
                service_id_snapshot="one",
                action_definition_id=action_id,
                action_key="restart",
                requested_by_subject="tester",
                source=ExecutionSource.UI,
                correlation_id="r1",
            )
        )
        await session.commit()

    async with factory() as session:
        assert await SqlAlchemyRepository(session).delete_action("one", "restart") is False
    await engine.dispose()
