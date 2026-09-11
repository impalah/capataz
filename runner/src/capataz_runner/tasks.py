"""Celery entry point: rehydrate and execute a persisted Capataz execution."""

from __future__ import annotations

import asyncio
import traceback

from celery import Task
from celery.utils.log import get_task_logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capataz_runner.actions import ActionConfigurationError
from capataz_runner.celery_app import app
from capataz_runner.config import Settings
from capataz_runner.crypto import ResourceDecryptionError, ResourceDecryptor
from capataz_runner.database import (
    append_event,
    claim_execution,
    create_engine_and_session_factory,
    mark_execution_terminal,
    reap_stuck_executions,
)
from capataz_runner.executor import (
    PersistentWorkerAutomationExecutor,
    collect_known_secrets,
    safe_result_data,
)
from capataz_runner.models import (
    ActionDefinitionRecord,
    ConnectorRecord,
    ExecutionRecord,
    ResourceRecord,
    ServiceRecord,
)
from capataz_runner.ports import AutomationJob, ExecutionResult
from capataz_runner.sanitization import sanitize_text

logger = get_task_logger(__name__)

# Which connector config fields reference an encrypted resource, per connector type that can run
# actions. Mirrors the API's domain.specs.connectors RESOURCE_FIELDS.
RESOURCE_FIELDS: dict[str, tuple[str, ...]] = {
    "portainer": ("token",),
    "ansible": ("private_key", "known_hosts", "vault_password"),
    "ssh": ("private_key", "known_hosts"),
}


def _known_secrets(settings: Settings, job: AutomationJob | None = None) -> tuple[str, ...]:
    """Best-effort collection of secret values to redact from an unexpected-exception traceback."""
    return collect_known_secrets(settings, job)


async def _load_job(
    session: AsyncSession, execution_id: str, decryptor: ResourceDecryptor
) -> AutomationJob:
    execution = await session.get(ExecutionRecord, execution_id)
    if execution is None:
        raise ActionConfigurationError("Execution does not exist")
    action = await session.get(ActionDefinitionRecord, execution.action_definition_id)
    service = await session.get(ServiceRecord, execution.service_id)
    if action is None or service is None or action.service_id != service.id:
        raise ActionConfigurationError("Execution references an invalid service or action")
    if not action.enabled:
        raise ActionConfigurationError("Action is disabled")
    connector = await session.get(ConnectorRecord, action.connector_id)
    if connector is None:
        raise ActionConfigurationError("Action references a connector that no longer exists")
    if connector.type != action.action_type:
        raise ActionConfigurationError("Action type does not match its connector type")
    config = dict(connector.config or {})
    secrets: dict[str, bytes] = {}
    for field_name in RESOURCE_FIELDS.get(connector.type, ()):
        resource_id = config.get(field_name)
        if resource_id is None:
            continue
        resource = await session.get(ResourceRecord, resource_id)
        if resource is None:
            raise ActionConfigurationError(
                f"Resource {resource_id!r} referenced by the connector does not exist"
            )
        try:
            secrets[field_name] = decryptor.decrypt(resource.ciphertext)
        except ResourceDecryptionError as exc:
            raise ActionConfigurationError(str(exc)) from exc
    return AutomationJob(
        execution_id=execution.id,
        service_id=service.id,
        action_type=action.action_type,
        action_config=action.config,
        connector_config=config,
        runtime=(service.spec or {}).get("runtime"),
        secrets=secrets,
        params=execution.params,
    )


async def process_execution_async(
    execution_id: str,
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    executor: PersistentWorkerAutomationExecutor | None = None,
) -> str:
    """Claim, execute and finalise one execution; duplicate Celery delivery is harmless."""
    async with session_factory() as session:
        claimed = await claim_execution(session, execution_id)
        await session.commit()
    if not claimed:
        return "not_claimed"

    job: AutomationJob | None = None
    try:
        async with session_factory() as session:
            job = await _load_job(
                session, execution_id, ResourceDecryptor(settings.resources_master_keys)
            )
            await append_event(
                session,
                execution_id=execution_id,
                level="info",
                event_type="execution_started",
                message="Execution claimed by persistent worker",
            )
            await session.commit()
        result = await (executor or PersistentWorkerAutomationExecutor(settings)).execute(job)
    except ActionConfigurationError as exc:
        result = ExecutionResult(
            "rejected", "Action configuration was rejected", error_code="action_rejected"
        )
        error_message = sanitize_text(str(exc), _known_secrets(settings, job))
        event_type = "execution_rejected"
        logger.warning("Execution %s rejected: %s", execution_id, error_message)
    except TimeoutError:
        result = ExecutionResult(
            "timed_out", "Execution exceeded its timeout", error_code="execution_timeout"
        )
        error_message = result.summary
        event_type = "execution_timed_out"
        logger.warning("Execution %s timed out", execution_id)
    except Exception:
        result = ExecutionResult(
            "failed",
            "Execution failed without exposing internal details",
            error_code="execution_failed",
        )
        error_message = result.summary
        event_type = "execution_failed"
        # Sanitize the traceback (not just str(exc)) before logging: an unexpected DB/connection
        # error can otherwise echo the DSN (which embeds the DB password) — or a decrypted
        # resource — into application logs.
        logger.error(
            "Execution %s failed unexpectedly: %s",
            execution_id,
            sanitize_text(traceback.format_exc(), _known_secrets(settings, job)),
        )
    else:
        error_message = result.summary
        event_type = "execution_finished"

    async with session_factory() as session:
        terminated = await mark_execution_terminal(
            session,
            execution_id=execution_id,
            status=result.status,
            summary=result.summary,
            error_code=result.error_code,
        )
        if not terminated:
            # The row was no longer 'running' (e.g. already reaped, or a concurrent write) —
            # the event below still gets appended, so surface the desync instead of hiding it.
            logger.warning(
                "Execution %s was not in 'running' state when finalizing as %s",
                execution_id,
                result.status,
            )
        await append_event(
            session,
            execution_id=execution_id,
            level="info" if result.status == "succeeded" else "error",
            event_type=event_type,
            message=error_message,
            data=safe_result_data(result),
        )
        await session.commit()
    return result.status


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="capataz_runner.tasks.process_execution",
    acks_late=True,
    reject_on_worker_lost=True,
    # No explicit time_limit/soft_time_limit here: inherit the app-wide defaults configured in
    # celery_app.py from Settings, so they stay in sync with the max action.timeout_seconds
    # allow-listed by actions.py instead of silently overriding it with a lower, stale literal.
)
def process_execution(task: Task, execution_id: str) -> str:
    """Task contract: the queue message carries only a persisted execution UUID."""
    del task
    settings = Settings()
    return asyncio.run(_process_execution_with_disposal(execution_id, settings))


async def _process_execution_with_disposal(execution_id: str, settings: Settings) -> str:
    """Build the engine inside this coroutine's own event loop and dispose it before returning.

    The engine/pool this creates is bound to the loop ``asyncio.run()`` is currently driving,
    so disposal must happen here, before that loop closes — not left to the garbage collector,
    which cannot close it cleanly once the loop is gone.
    """
    engine, factory = create_engine_and_session_factory(settings.database_url)
    try:
        return await process_execution_async(
            execution_id, settings=settings, session_factory=factory
        )
    finally:
        await engine.dispose()


async def reap_stuck_executions_async(
    *, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> list[str]:
    """Reconcile executions a dead/killed worker left stranded in 'running'."""
    # Generous relative to the Celery hard time limit: a genuinely running action should never
    # be flagged while a worker could still legitimately be executing it.
    max_age_seconds = settings.celery_hard_time_limit_seconds * 2
    async with session_factory() as session:
        reaped_ids = await reap_stuck_executions(session, max_age_seconds=max_age_seconds)
        for execution_id in reaped_ids:
            await append_event(
                session,
                execution_id=execution_id,
                level="error",
                event_type="execution_reaped",
                message="Execution was reaped after being stuck in running longer than expected",
            )
        await session.commit()
    if reaped_ids:
        logger.warning("Reaped %d stuck execution(s): %s", len(reaped_ids), reaped_ids)
    return reaped_ids


@app.task(name="capataz_runner.tasks.reap_stuck_executions")  # type: ignore[untyped-decorator]
def reap_stuck_executions_task() -> list[str]:
    """Periodic (Celery beat) entry point; safe to run redundantly across restarts/workers."""
    settings = Settings()
    return asyncio.run(_reap_stuck_executions_with_disposal(settings))


async def _reap_stuck_executions_with_disposal(settings: Settings) -> list[str]:
    """Same engine-lifecycle discipline as ``_process_execution_with_disposal`` — see CR-082."""
    engine, factory = create_engine_and_session_factory(settings.database_url)
    try:
        return await reap_stuck_executions_async(settings=settings, session_factory=factory)
    finally:
        await engine.dispose()
