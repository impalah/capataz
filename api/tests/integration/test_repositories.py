"""Integration tests for repositories.py against a real Postgres (see conftest.py for why).

Originally unit tests against SQLite; moved here and migrated to testcontainers.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from capataz_api.domain.entities import ActionDefinition, Execution, Service
from capataz_api.domain.exceptions import ConflictError
from capataz_api.domain.value_objects import ActionType, ExecutionSource, ExecutionStatus, RiskLevel
from capataz_api.infrastructure.database.models import ExecutionEventModel, ExecutionModel
from capataz_api.infrastructure.database.repositories import SqlAlchemyRepository


def make_action(service_id: str, key: str = "restart") -> ActionDefinition:
    return ActionDefinition(
        service_id=service_id,
        key=key,
        label="Restart",
        action_type=ActionType.PORTAINER,
        risk_level=RiskLevel.OPERATE,
        config={"operation": "restart", "target": "selected_containers"},
    )


def make_execution(
    *,
    service_id: str = "one",
    action_definition_id: UUID,
    requested_by_subject: str = "tester",
    **overrides: Any,
) -> Execution:
    defaults: dict[str, Any] = {
        "service_id": service_id,
        "service_id_snapshot": service_id,
        "action_definition_id": action_definition_id,
        "action_key": "restart",
        "requested_by_subject": requested_by_subject,
        "source": ExecutionSource.UI,
        "correlation_id": "r1",
    }
    defaults.update(overrides)
    return Execution(**defaults)


@pytest.mark.asyncio
async def test_list_services_paginates_in_sql_not_in_python(pg_engine: AsyncEngine) -> None:
    """CR-032: offset/limit must be applied by the query, with a correct total across pages."""
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        for index in range(5):
            await repo.upsert_service(
                Service(id=f"svc-{index}", name=f"Name {index}", group_name="G", environment="dev")
            )
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        page1, total1 = await repo.list_services(offset=0, limit=2)
        page2, total2 = await repo.list_services(offset=2, limit=2)
        page3, total3 = await repo.list_services(offset=4, limit=2)

    assert total1 == total2 == total3 == 5
    assert [item.id for item in page1] == ["svc-0", "svc-1"]
    assert [item.id for item in page2] == ["svc-2", "svc-3"]
    assert [item.id for item in page3] == ["svc-4"]


@pytest.mark.asyncio
async def test_list_services_filters_by_status_cache_column_in_sql(pg_engine: AsyncEngine) -> None:
    """CR-063: status is a real SQL WHERE against the persisted status_cache column, with a

    total that reflects the whole filtered set across pages — not a page already truncated by
    offset/limit re-filtered in Python (the CR-016 bug).
    """
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        for index in range(5):
            await repo.upsert_service(
                Service(id=f"svc-{index}", name=f"Name {index}", group_name="G", environment="dev")
            )
        await session.commit()
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        for index in range(5):
            await repo.update_status_cache(f"svc-{index}", "healthy" if index < 3 else "down")
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        page1, total1 = await repo.list_services(status="healthy", offset=0, limit=2)
        page2, total2 = await repo.list_services(status="healthy", offset=2, limit=2)

    assert total1 == total2 == 3
    assert [item.id for item in page1] == ["svc-0", "svc-1"]
    assert [item.id for item in page2] == ["svc-2"]


@pytest.mark.asyncio
async def test_list_audit_paginates_with_correct_total(pg_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        for index in range(3):
            await repo.append_audit(
                {"actor": f"user-{index}", "action": "service.create", "resource": "one"}
            )
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        items, total = await repo.list_audit(offset=1, limit=1)
    assert total == 3
    assert len(items) == 1


@pytest.mark.asyncio
async def test_create_execution_translates_duplicate_id_to_conflict(pg_engine: AsyncEngine) -> None:
    """CR-033: a raw IntegrityError (duplicate PK) must surface as a domain ConflictError."""
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    action_id = uuid4()
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(Service(id="one", name="One", group_name="G", environment="dev"))
        action = make_action("one")
        action.id = action_id
        await repo.upsert_action(action)
        await session.commit()

    execution_id = uuid4()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.create_execution(make_execution(action_definition_id=action_id, id=execution_id))
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        with pytest.raises(ConflictError):
            await repo.create_execution(
                make_execution(action_definition_id=action_id, id=execution_id)
            )


@pytest.mark.asyncio
async def test_upsert_service_raises_conflict_on_stale_version(pg_engine: AsyncEngine) -> None:
    """CR-034: two concurrent readers of the same row must not silently overwrite one another."""
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
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


@pytest.mark.asyncio
async def test_upsert_service_without_enforce_version_overwrites_unconditionally(
    pg_engine: AsyncEngine,
) -> None:
    """Plain upsert (service creation, catalog import) intentionally has no expected version."""
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(
            Service(id="one", name="Original", group_name="G", environment="dev")
        )
        await repo.upsert_service(
            Service(id="one", name="Reimported", group_name="G", environment="dev")
        )
        await session.commit()
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        stored = await repo.get_service("one")
        assert stored is not None and stored.name == "Reimported"


@pytest.mark.asyncio
async def test_list_services_filters_by_group_name_and_environment(pg_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(
            Service(id="ai-one", name="AI One", group_name="AI", environment="homelab")
        )
        await repo.upsert_service(
            Service(id="infra-one", name="Infra One", group_name="Infra", environment="homelab")
        )
        await repo.upsert_service(
            Service(id="ai-staging", name="AI Staging", group_name="AI", environment="staging")
        )
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        by_group, group_total = await repo.list_services(group_name="AI")
        by_env, env_total = await repo.list_services(environment="staging")
    assert group_total == 2
    assert {item.id for item in by_group} == {"ai-one", "ai-staging"}
    assert env_total == 1
    assert by_env[0].id == "ai-staging"


@pytest.mark.asyncio
async def test_delete_service_returns_false_when_missing_and_blocks_active_executions(
    pg_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    action_id = uuid4()
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        assert await repo.delete_service("missing") is False

        await repo.upsert_service(Service(id="one", name="One", group_name="G", environment="dev"))
        action = make_action("one")
        action.id = action_id
        await repo.upsert_action(action)
        await repo.create_execution(make_execution(action_definition_id=action_id))
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        # A service with a queued/running execution must not be deletable out from under it.
        assert await repo.delete_service("one") is False


@pytest.mark.asyncio
async def test_delete_service_succeeds_once_no_active_executions_remain(
    pg_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(Service(id="one", name="One", group_name="G", environment="dev"))
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        assert await repo.delete_service("one") is True
        assert await repo.get_service("one") is None


@pytest.mark.asyncio
async def test_delete_service_with_historical_execution_succeeds_and_orphans_it(
    pg_engine: AsyncEngine,
) -> None:
    """CR-077: a *terminal* (non-active) execution must never block deleting its service — the

    old behaviour crashed with a misleading "already exists" ConflictError from an unhandled FK
    violation (confirmed empirically against real Postgres during the review). SET NULL should
    let the delete succeed and leave the execution's service_id_snapshot intact for display.
    """
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    action_id = uuid4()
    execution_id = uuid4()
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(Service(id="one", name="One", group_name="G", environment="dev"))
        action = make_action("one")
        action.id = action_id
        await repo.upsert_action(action)
        execution = make_execution(action_definition_id=action_id, id=execution_id)
        execution.status = ExecutionStatus.SUCCEEDED
        await repo.create_execution(execution)
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        assert await repo.delete_service("one") is True
        assert await repo.get_service("one") is None
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        orphaned = await repo.get_execution(execution_id)
        assert orphaned is not None
        assert orphaned.service_id is None
        assert orphaned.service_id_snapshot == "one"


@pytest.mark.asyncio
async def test_delete_action_blocks_on_active_execution_and_succeeds_once_it_finishes(
    pg_engine: AsyncEngine,
) -> None:
    """CR-077: delete_action needed the same active-execution precheck delete_service already

    had — previously missing entirely, so it relied on the FK violation to (confusingly) fail.
    """
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    action_id = uuid4()
    execution_id = uuid4()
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(Service(id="one", name="One", group_name="G", environment="dev"))
        action = make_action("one")
        action.id = action_id
        await repo.upsert_action(action)
        await repo.create_execution(make_execution(action_definition_id=action_id, id=execution_id))
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        assert await repo.delete_action("one", "restart") is False

    async with factory() as session:
        execution = await session.get(ExecutionModel, execution_id)
        assert execution is not None
        execution.status = "succeeded"
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        assert await repo.delete_action("one", "restart") is True
        assert await repo.get_action("one", "restart") is None
        await session.commit()


@pytest.mark.asyncio
async def test_action_crud_list_get_update_and_delete(pg_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(Service(id="one", name="One", group_name="G", environment="dev"))
        await repo.upsert_action(make_action("one", "restart"))
        await repo.upsert_action(make_action("one", "stop"))
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        listed = await repo.list_actions("one")
        assert [action.key for action in listed] == ["restart", "stop"]  # ordered by key

        fetched = await repo.get_action("one", "restart")
        assert fetched is not None and fetched.label == "Restart"
        assert await repo.get_action("one", "missing") is None

        fetched.label = "Restart (updated)"
        updated = await repo.upsert_action(fetched)
        assert updated.label == "Restart (updated)"
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        again = await repo.get_action("one", "restart")
        assert again is not None and again.label == "Restart (updated)"

        assert await repo.delete_action("one", "restart") is True
        assert await repo.delete_action("one", "restart") is False
        assert await repo.get_action("one", "restart") is None


@pytest.mark.asyncio
async def test_get_execution_returns_none_when_missing(pg_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        assert await repo.get_execution(uuid4()) is None


@pytest.mark.asyncio
async def test_list_executions_filters_by_service_status_actor_and_source(
    pg_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    action_id = uuid4()
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(Service(id="one", name="One", group_name="G", environment="dev"))
        action = make_action("one")
        action.id = action_id
        await repo.upsert_action(action)

        await repo.create_execution(
            make_execution(action_definition_id=action_id, requested_by_subject="alice")
        )
        await repo.create_execution(
            make_execution(
                action_definition_id=action_id, requested_by_subject="bob", correlation_id="r2"
            )
        )
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        items, total = await repo.list_executions(
            service_id="one",
            status=ExecutionStatus.QUEUED,
            actor="alice",
            source=ExecutionSource.UI,
        )
    assert total == 1
    assert items[0].requested_by_subject == "alice"


@pytest.mark.asyncio
async def test_events_returns_execution_events_ordered_by_sequence(pg_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    action_id = uuid4()
    execution_id = uuid4()
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(Service(id="one", name="One", group_name="G", environment="dev"))
        action = make_action("one")
        action.id = action_id
        await repo.upsert_action(action)
        await repo.create_execution(make_execution(action_definition_id=action_id, id=execution_id))
        session.add(
            ExecutionEventModel(
                execution_id=execution_id,
                sequence=2,
                level="info",
                event_type="log",
                message="second",
                data={},
            )
        )
        session.add(
            ExecutionEventModel(
                execution_id=execution_id,
                sequence=1,
                level="info",
                event_type="log",
                message="first",
                data={},
            )
        )
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        events = await repo.events(execution_id)
    assert [event["message"] for event in events] == ["first", "second"]
    assert events[0]["sequence"] == 1


@pytest.mark.asyncio
async def test_list_audit_returns_full_event_shape(pg_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.append_audit(
            {
                "actor": "admin",
                "actor_name": "Admin User",
                "actor_email": "admin@example.com",
                "action": "service.create",
                "resource": "one",
                "request_id": "r1",
                "metadata": {"foo": "bar"},
            }
        )
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        items, total = await repo.list_audit()
    assert total == 1
    event = items[0]
    assert event["actor"] == "admin"
    assert event["actor_name"] == "Admin User"
    assert event["outcome"] == "success"
    assert event["metadata"] == {"foo": "bar"}
