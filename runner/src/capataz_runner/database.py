"""Async SQLAlchemy helpers used by the Celery worker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from capataz_runner.models import ExecutionEventRecord, ExecutionRecord
from capataz_runner.sanitization import sanitize_data, sanitize_text


def create_engine_and_session_factory(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Build the runner's async PostgreSQL engine and session factory.

    Returns the engine alongside the factory so the caller can ``await engine.dispose()`` within
    the same event loop that created it. ``AsyncEngine``/``asyncpg`` tie their connection pool to
    the event loop that created it, so a caller that builds one of these per ``asyncio.run()`` call
    (as tasks.py does, once per Celery task) must dispose it before that loop closes — otherwise
    the pool's connections are neither reusable nor cleanly closeable once the loop is gone, and
    leak until the garbage collector eventually reaps the engine's reference cycle.
    """
    engine = create_async_engine(database_url, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def claim_execution(session: AsyncSession, execution_id: str) -> bool:
    """Atomically claim an execution only if it is still queued."""
    result = await session.execute(
        update(ExecutionRecord)
        .where(ExecutionRecord.id == execution_id, ExecutionRecord.status == "queued")
        .values(status="running", started_at=datetime.now(UTC))
    )
    return bool(getattr(result, "rowcount", 0))


async def reap_stuck_executions(session: AsyncSession, *, max_age_seconds: int) -> list[str]:
    """Fail executions left ``running`` past a worker-crash-tolerant age; returns their ids.

    Covers the case where a worker dies (crash, OOM, a hard Celery time limit) between
    ``claim_execution`` and ``mark_execution_terminal``: Celery's ``acks_late``/
    ``reject_on_worker_lost`` redelivery only re-attempts a still-``queued`` message, so a
    ``running`` row with no worker left to finish it would otherwise never reach a terminal state.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=max_age_seconds)
    result = await session.execute(
        update(ExecutionRecord)
        .where(ExecutionRecord.status == "running", ExecutionRecord.started_at < cutoff)
        .values(
            status="failed",
            finished_at=datetime.now(UTC),
            error_code="execution_reaped",
            error_summary="Execution was reaped after being stuck in running longer than expected",
        )
        .returning(ExecutionRecord.id)
    )
    return [str(row[0]) for row in result.all()]


async def append_event(
    session: AsyncSession,
    *,
    execution_id: str,
    level: str,
    event_type: str,
    message: str,
    data: dict[str, object] | None = None,
) -> ExecutionEventRecord:
    """Append a sanitised chronological event for API SSE consumers."""
    # CR-086: lock the parent execution row first so two concurrent appenders for the same
    # execution_id (the normal worker vs. a reaper racing it, see reap_stuck_executions) can
    # never both read the same max(sequence) before either has inserted — the second caller
    # blocks here until the first commits/rolls back, instead of both computing the same
    # next_sequence and one losing to the uq_execution_event_sequence constraint.
    await session.execute(
        select(ExecutionRecord.id).where(ExecutionRecord.id == execution_id).with_for_update()
    )
    next_sequence = await session.scalar(
        select(func.coalesce(func.max(ExecutionEventRecord.sequence), 0) + 1).where(
            ExecutionEventRecord.execution_id == execution_id
        )
    )
    event = ExecutionEventRecord(
        id=str(uuid4()),
        execution_id=execution_id,
        sequence=int(next_sequence or 1),
        level=level,
        event_type=event_type,
        message=sanitize_text(message),
        data=sanitize_data(data or {}),
    )
    session.add(event)
    return event


async def mark_execution_terminal(
    session: AsyncSession,
    *,
    execution_id: str,
    status: str,
    summary: str,
    error_code: str | None = None,
) -> bool:
    """Persist a terminal state without permitting a worker to overwrite another terminal result.

    Returns whether the row was actually updated (it was still ``running``); the caller should
    treat ``False`` as a desync worth logging, since an event describing this transition will
    still be appended regardless.
    """
    result = await session.execute(
        update(ExecutionRecord)
        .where(ExecutionRecord.id == execution_id, ExecutionRecord.status == "running")
        .values(
            status=status,
            finished_at=datetime.now(UTC),
            result_summary=sanitize_text(summary) if status == "succeeded" else None,
            error_code=error_code,
            error_summary=sanitize_text(summary) if status != "succeeded" else None,
        )
    )
    return bool(getattr(result, "rowcount", 0))
