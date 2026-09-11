"""Integration tests for repositories.py against a real Postgres (see conftest.py for why).

Originally unit tests against SQLite; moved here and migrated to testcontainers.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from capataz_api.domain.entities import ActionDefinition, Connector, Execution, Service
from capataz_api.domain.exceptions import ConflictError
from capataz_api.domain.specs import CONNECTOR_SPEC_ADAPTER, ServiceSpec
from capataz_api.domain.value_objects import ActionType, ExecutionSource, ExecutionStatus, RiskLevel
from capataz_api.infrastructure.database.models import ExecutionEventModel, ExecutionModel
from capataz_api.infrastructure.database.repositories import SqlAlchemyRepository


def make_service(
    service_id: str, name: str | None = None, group_name: str = "G", environment: str = "dev"
) -> Service:
    return Service(
        id=service_id,
        spec=ServiceSpec(name=name or service_id, group_name=group_name, environment=environment),
    )


def portainer() -> Connector:
    return Connector(
        spec=CONNECTOR_SPEC_ADAPTER.validate_python(
            {
                "id": "portainer_main",
                "type": "portainer",
                "config": {"url": "https://portainer.home.arpa", "token": "portainer_token"},
            }
        )
    )


def make_action(service_id: str, key: str = "restart") -> ActionDefinition:
    return ActionDefinition(
        service_id=service_id,
        key=key,
        label="Restart",
        action_type=ActionType.PORTAINER,
        risk_level=RiskLevel.OPERATE,
        connector_id="portainer_main",
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


async def seed_service_with_action(
    repo: SqlAlchemyRepository, action_id: UUID | None = None
) -> UUID:
    await repo.upsert_connector(portainer())
    await repo.upsert_service(make_service("one"))
    action = make_action("one")
    if action_id is not None:
        action.id = action_id
    await repo.upsert_action(action)
    return action.id


@pytest.mark.asyncio
async def test_list_services_paginates_in_sql_not_in_python(pg_engine: AsyncEngine) -> None:
    """CR-032: offset/limit must be applied by the query, with a correct total across pages."""
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        for index in range(5):
            await repo.upsert_service(make_service(f"svc-{index}", name=f"Name {index}"))
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
    """CR-063: status is a real SQL WHERE against the persisted status_cache column."""
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        for index in range(5):
            await repo.upsert_service(make_service(f"svc-{index}", name=f"Name {index}"))
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
async def test_service_spec_round_trips_through_jsonb(pg_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    spec = ServiceSpec.model_validate(
        {
            "name": "Authentik",
            "group_name": "Security",
            "environment": "homelab",
            "runtime": {
                "connector": "portainer_main",
                "environment_id": "7",
                "stack_name": "authentik",
                "services": [{"name": "authentik-server", "replicas": 2}],
            },
            "observability": {
                "dashboards": [{"connector": "grafana", "uid": "abc", "slug": "authentik"}]
            },
        }
    )
    async with factory() as session:
        await SqlAlchemyRepository(session).upsert_service(Service(id="authentik", spec=spec))
        await session.commit()
    async with factory() as session:
        loaded = await SqlAlchemyRepository(session).get_service("authentik")
    assert loaded is not None and loaded.spec == spec


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
        items, total = await SqlAlchemyRepository(session).list_audit(offset=1, limit=1)
    assert total == 3
    assert len(items) == 1


@pytest.mark.asyncio
async def test_create_execution_translates_duplicate_id_to_conflict(pg_engine: AsyncEngine) -> None:
    """CR-033: a raw IntegrityError (duplicate PK) must surface as a domain ConflictError."""
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        action_id = await seed_service_with_action(SqlAlchemyRepository(session))
        await session.commit()

    execution_id = uuid4()
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.create_execution(make_execution(action_definition_id=action_id, id=execution_id))
        await session.commit()

    async with factory() as session:
        with pytest.raises(ConflictError):
            await SqlAlchemyRepository(session).create_execution(
                make_execution(action_definition_id=action_id, id=execution_id)
            )


@pytest.mark.asyncio
async def test_upsert_service_raises_conflict_on_stale_version(pg_engine: AsyncEngine) -> None:
    """CR-034: two concurrent readers of the same row must not silently overwrite one another."""
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
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


@pytest.mark.asyncio
async def test_upsert_service_without_enforce_version_overwrites_unconditionally(
    pg_engine: AsyncEngine,
) -> None:
    """Plain upsert (service creation, catalog import) intentionally has no expected version."""
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(make_service("one", name="Original"))
        await repo.upsert_service(make_service("one", name="Reimported"))
        await session.commit()
    async with factory() as session:
        stored = await SqlAlchemyRepository(session).get_service("one")
    assert stored is not None and stored.name == "Reimported"


@pytest.mark.asyncio
async def test_list_services_filters_by_group_name_and_environment(pg_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_service(make_service("ai-one", group_name="AI", environment="homelab"))
        await repo.upsert_service(
            make_service("infra-one", group_name="Infra", environment="homelab")
        )
        await repo.upsert_service(
            make_service("ai-staging", group_name="AI", environment="staging")
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
async def test_a_connector_still_used_by_an_action_cannot_be_deleted(
    pg_engine: AsyncEngine,
) -> None:
    """action_definitions.connector_id is ON DELETE RESTRICT."""
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        await seed_service_with_action(SqlAlchemyRepository(session))
        await session.commit()

    async with factory() as session:
        with pytest.raises(ConflictError):
            await SqlAlchemyRepository(session).delete_connector("portainer_main")


@pytest.mark.asyncio
async def test_delete_service_returns_false_when_missing_and_blocks_active_executions(
    pg_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        assert await repo.delete_service("missing") is False
        action_id = await seed_service_with_action(repo)
        await repo.create_execution(make_execution(action_definition_id=action_id))
        await session.commit()

    async with factory() as session:
        # A service with a queued/running execution must not be deletable out from under it.
        assert await SqlAlchemyRepository(session).delete_service("one") is False


@pytest.mark.asyncio
async def test_delete_service_succeeds_once_no_active_executions_remain(
    pg_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        await SqlAlchemyRepository(session).upsert_service(make_service("one"))
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        assert await repo.delete_service("one") is True
        assert await repo.get_service("one") is None


@pytest.mark.asyncio
async def test_delete_service_with_historical_execution_succeeds_and_orphans_it(
    pg_engine: AsyncEngine,
) -> None:
    """CR-077: a terminal execution never blocks deleting its service; SET NULL keeps history."""
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    execution_id = uuid4()
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        action_id = await seed_service_with_action(repo)
        execution = make_execution(action_definition_id=action_id, id=execution_id)
        execution.status = ExecutionStatus.SUCCEEDED
        await repo.create_execution(execution)
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        assert await repo.delete_service("one") is True
        await session.commit()

    async with factory() as session:
        orphaned = await SqlAlchemyRepository(session).get_execution(execution_id)
    assert orphaned is not None
    assert orphaned.service_id is None
    assert orphaned.service_id_snapshot == "one"


@pytest.mark.asyncio
async def test_delete_action_blocks_on_active_execution_and_succeeds_once_it_finishes(
    pg_engine: AsyncEngine,
) -> None:
    """CR-077: delete_action has the same active-execution precheck delete_service has."""
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    execution_id = uuid4()
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        action_id = await seed_service_with_action(repo)
        await repo.create_execution(make_execution(action_definition_id=action_id, id=execution_id))
        await session.commit()

    async with factory() as session:
        assert await SqlAlchemyRepository(session).delete_action("one", "restart") is False

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
        await seed_service_with_action(repo)
        await repo.upsert_action(make_action("one", "stop"))
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        assert [action.key for action in await repo.list_actions("one")] == ["restart", "stop"]
        fetched = await repo.get_action("one", "restart")
        assert fetched is not None and fetched.connector_id == "portainer_main"
        assert await repo.get_action("one", "missing") is None
        fetched.label = "Restart (updated)"
        assert (await repo.upsert_action(fetched)).label == "Restart (updated)"
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        again = await repo.get_action("one", "restart")
        assert again is not None and again.label == "Restart (updated)"
        assert await repo.delete_action("one", "restart") is True
        assert await repo.delete_action("one", "restart") is False


@pytest.mark.asyncio
async def test_get_execution_returns_none_when_missing(pg_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        assert await SqlAlchemyRepository(session).get_execution(uuid4()) is None


@pytest.mark.asyncio
async def test_list_executions_filters_by_service_status_actor_and_source(
    pg_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        action_id = await seed_service_with_action(repo)
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
        items, total = await SqlAlchemyRepository(session).list_executions(
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
    execution_id = uuid4()
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        action_id = await seed_service_with_action(repo)
        await repo.create_execution(make_execution(action_definition_id=action_id, id=execution_id))
        for sequence, message in ((2, "second"), (1, "first")):
            session.add(
                ExecutionEventModel(
                    execution_id=execution_id,
                    sequence=sequence,
                    level="info",
                    event_type="log",
                    message=message,
                    data={},
                )
            )
        await session.commit()

    async with factory() as session:
        events = await SqlAlchemyRepository(session).events(execution_id)
    assert [event["message"] for event in events] == ["first", "second"]
    assert events[0]["sequence"] == 1


@pytest.mark.asyncio
async def test_list_audit_returns_full_event_shape(pg_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        await SqlAlchemyRepository(session).append_audit(
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
        items, total = await SqlAlchemyRepository(session).list_audit()
    assert total == 1
    event = items[0]
    assert (event["actor"], event["actor_name"], event["outcome"]) == (
        "admin",
        "Admin User",
        "success",
    )
    assert event["metadata"] == {"foo": "bar"}
