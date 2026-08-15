"""Fast SQLite smoke coverage for repositories.py, kept at unit level per the project's

"no directory exempted from unit coverage" policy (see the comment on [tool.coverage.run] in
pyproject.toml). The full correctness suite — including everything that depends on real foreign
-key/constraint enforcement, which SQLite does not provide by default — lives in
tests/integration/test_repositories.py against a real Postgres. These tests only exercise logic
that doesn't depend on that distinction: pagination, filtering, and the optimistic-concurrency
compare-and-swap.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from capataz_api.domain.entities import ActionDefinition, Execution, Service
from capataz_api.domain.exceptions import ConflictError
from capataz_api.domain.value_objects import ActionType, ExecutionSource, RiskLevel
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
            await repo.upsert_service(
                Service(id=f"svc-{index}", name=f"Name {index}", group_name="G", environment="dev")
            )
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
async def test_upsert_service_raises_conflict_on_stale_version(tmp_path: Path) -> None:
    """CR-034: two concurrent readers of the same row must not silently overwrite one another."""
    engine = await _empty_engine(tmp_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(
            Service(id="one", name="Original", group_name="G", environment="dev")
        )
        await session.commit()

    async with factory() as first_session, factory() as second_session:
        first_repo = SqlAlchemyRepository(first_session)
        second_repo = SqlAlchemyRepository(second_session)
        first_service = await first_repo.get_service("one")
        second_service = await second_repo.get_service("one")
        assert first_service is not None and second_service is not None

        first_service.name = "Updated by first writer"
        await first_repo.upsert_service(first_service, enforce_version=True)
        await first_session.commit()

        second_service.name = "Updated by second writer (stale)"
        with pytest.raises(ConflictError):
            await second_repo.upsert_service(second_service, enforce_version=True)
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_services_filters_by_group_name_and_environment(tmp_path: Path) -> None:
    engine = await _empty_engine(tmp_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(
            Service(id="ai-one", name="AI One", group_name="AI", environment="homelab")
        )
        await repo.upsert_service(
            Service(id="infra-one", name="Infra One", group_name="Infra", environment="homelab")
        )
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        by_group, group_total = await repo.list_services(group_name="AI")
    assert group_total == 1
    assert by_group[0].id == "ai-one"
    await engine.dispose()


@pytest.mark.asyncio
async def test_action_crud_and_batched_list_actions_for_services(tmp_path: Path) -> None:
    """CR-080: list_actions_for_services must batch across services in one query."""
    engine = await _empty_engine(tmp_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(Service(id="one", name="One", group_name="G", environment="dev"))
        await repo.upsert_service(Service(id="two", name="Two", group_name="G", environment="dev"))
        await repo.upsert_action(
            ActionDefinition(
                service_id="one",
                key="restart",
                label="Restart",
                action_type=ActionType.PORTAINER,
                risk_level=RiskLevel.OPERATE,
                config={"operation": "restart", "target": "selected_containers"},
            )
        )
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        by_service = await repo.list_actions_for_services(["one", "two", "missing"])
        assert [action.key for action in by_service["one"]] == ["restart"]
        assert by_service["two"] == []
        assert by_service["missing"] == []

        assert await repo.delete_action("one", "restart") is True
        assert await repo.delete_action("one", "restart") is False
        assert await repo.get_action("one", "restart") is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_action_blocks_while_an_execution_is_active(tmp_path: Path) -> None:
    """CR-077: delete_action's active-execution precheck (previously absent entirely)."""
    engine = await _empty_engine(tmp_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    action_id = uuid4()
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(Service(id="one", name="One", group_name="G", environment="dev"))
        action = ActionDefinition(
            id=action_id,
            service_id="one",
            key="restart",
            label="Restart",
            action_type=ActionType.PORTAINER,
            risk_level=RiskLevel.OPERATE,
            config={"operation": "restart", "target": "selected_containers"},
        )
        await repo.upsert_action(action)
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
        repo = SqlAlchemyRepository(session)
        assert await repo.delete_action("one", "restart") is False
    await engine.dispose()
