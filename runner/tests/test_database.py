from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from capataz_runner.database import claim_execution
from capataz_runner.models import Base, ExecutionRecord


@pytest.mark.asyncio
async def test_queued_execution_has_exactly_one_atomic_claimant() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            ExecutionRecord(
                id="22222222-2222-2222-2222-222222222222",
                service_id="service",
                action_definition_id="11111111-1111-1111-1111-111111111111",
                status="queued",
            )
        )
        await session.commit()

    async def contender() -> bool:
        async with factory() as session:
            claimed = await claim_execution(session, "22222222-2222-2222-2222-222222222222")
            await session.commit()
            return claimed

    results = await asyncio.gather(contender(), contender())
    assert sorted(results) == [False, True]
    async with factory() as session:
        execution = await session.get(ExecutionRecord, "22222222-2222-2222-2222-222222222222")
        assert execution is not None
        assert execution.status == "running"
    await engine.dispose()


@pytest.mark.asyncio
async def test_events_and_terminal_result_are_sanitized() -> None:
    from capataz_runner.database import append_event, mark_execution_terminal
    from capataz_runner.models import ExecutionEventRecord

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            ExecutionRecord(
                id="33333333-3333-3333-3333-333333333333",
                service_id="service",
                action_definition_id="11111111-1111-1111-1111-111111111111",
                status="running",
            )
        )
        await session.commit()
    async with factory() as session:
        event = await append_event(
            session,
            execution_id="33333333-3333-3333-3333-333333333333",
            level="error",
            event_type="failed",
            message="Bearer leaked-token",
            data={"token": "leaked-token"},
        )
        await mark_execution_terminal(
            session,
            execution_id="33333333-3333-3333-3333-333333333333",
            status="failed",
            summary="password=hunter2",
            error_code="failed",
        )
        await session.commit()
        assert event.sequence == 1
    async with factory() as session:
        stored = await session.get(ExecutionRecord, "33333333-3333-3333-3333-333333333333")
        event = await session.get(ExecutionEventRecord, event.id)
        assert stored is not None and "hunter2" not in (stored.error_summary or "")
        assert event is not None and event.data["token"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_mark_execution_terminal_reports_whether_it_actually_updated_a_row() -> None:
    from capataz_runner.database import mark_execution_terminal

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            ExecutionRecord(
                id="44444444-4444-4444-4444-444444444444",
                service_id="service",
                action_definition_id="11111111-1111-1111-1111-111111111111",
                status="failed",  # already terminal, e.g. reaped concurrently
            )
        )
        await session.commit()
    async with factory() as session:
        updated = await mark_execution_terminal(
            session,
            execution_id="44444444-4444-4444-4444-444444444444",
            status="succeeded",
            summary="too late",
        )
        await session.commit()
    assert updated is False
    await engine.dispose()


@pytest.mark.asyncio
async def test_reap_stuck_executions_only_fails_old_running_rows() -> None:
    from capataz_runner.database import reap_stuck_executions

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with factory() as session:
        session.add_all(
            [
                ExecutionRecord(
                    id="55555555-5555-5555-5555-555555555555",
                    service_id="service",
                    action_definition_id="11111111-1111-1111-1111-111111111111",
                    status="running",
                    started_at=now - timedelta(seconds=1000),
                ),
                ExecutionRecord(
                    id="66666666-6666-6666-6666-666666666666",
                    service_id="service",
                    action_definition_id="11111111-1111-1111-1111-111111111111",
                    status="running",
                    started_at=now - timedelta(seconds=5),
                ),
                ExecutionRecord(
                    id="77777777-7777-7777-7777-777777777777",
                    service_id="service",
                    action_definition_id="11111111-1111-1111-1111-111111111111",
                    status="succeeded",
                    started_at=now - timedelta(seconds=1000),
                ),
            ]
        )
        await session.commit()
    async with factory() as session:
        reaped = await reap_stuck_executions(session, max_age_seconds=60)
        await session.commit()
    assert reaped == ["55555555-5555-5555-5555-555555555555"]
    async with factory() as session:
        reaped_execution = await session.get(
            ExecutionRecord, "55555555-5555-5555-5555-555555555555"
        )
        recent_execution = await session.get(
            ExecutionRecord, "66666666-6666-6666-6666-666666666666"
        )
        assert reaped_execution is not None and reaped_execution.status == "failed"
        assert reaped_execution.error_code == "execution_reaped"
        assert recent_execution is not None and recent_execution.status == "running"
    await engine.dispose()
    await engine.dispose()
