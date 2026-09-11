from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_MASTER_KEY
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from capataz_runner.models import (
    ActionDefinitionRecord,
    Base,
    ConnectorRecord,
    ExecutionEventRecord,
    ExecutionRecord,
    ResourceRecord,
    ServiceRecord,
)
from capataz_runner.ports import AutomationJob, ExecutionResult

LOCAL_ANSIBLE = {
    "inventory": "inventories/local.yml",
    "private_key": "local_key",
    "known_hosts": "local_known_hosts",
}


def _encrypt(content: bytes) -> bytes:
    return Fernet(TEST_MASTER_KEY.encode()).encrypt(content)


def _seed_service_and_connector(
    session: Any,
    *,
    connector_type: str = "ansible",
    connector_config: dict[str, Any] | None = None,
    resources: dict[str, bytes] | None = None,
) -> None:
    session.add(
        ServiceRecord(
            id="service",
            name="Service",
            spec={"name": "Service", "runtime": {"environment_id": "1", "containers": []}},
        )
    )
    session.add(
        ConnectorRecord(id="local", type=connector_type, config=connector_config or LOCAL_ANSIBLE)
    )
    default_resources = {"local_key": b"KEY-MATERIAL\n", "local_known_hosts": b"kh\n"}
    for resource_id, content in (resources if resources is not None else default_resources).items():
        session.add(ResourceRecord(id=resource_id, type="file", ciphertext=_encrypt(content)))


@pytest.mark.asyncio
async def test_task_processing_rehydrates_records_and_persists_events(secrets_dir: object) -> None:
    from capataz_runner.config import Settings
    from capataz_runner.tasks import process_execution_async

    class SuccessfulExecutor:
        async def execute(self, job: object) -> ExecutionResult:
            return ExecutionResult("succeeded", "completed", {"token": "must-not-persist"})

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        _seed_service_and_connector(session)
        session.add(
            ActionDefinitionRecord(
                id="11111111-1111-1111-1111-111111111111",
                service_id="service",
                key="restart",
                connector_id="local",
                action_type="ansible",
                enabled=True,
                config={"playbook": "playbooks/restart_service.yml", "limit": "local-mock"},
            )
        )
        session.add(
            ExecutionRecord(
                id="44444444-4444-4444-4444-444444444444",
                service_id="service",
                action_definition_id="11111111-1111-1111-1111-111111111111",
                status="queued",
            )
        )
        await session.commit()

    result = await process_execution_async(
        "44444444-4444-4444-4444-444444444444",
        settings=Settings(secrets_dir=secrets_dir),
        session_factory=factory,
        executor=SuccessfulExecutor(),  # type: ignore[arg-type]
    )
    assert result == "succeeded"
    async with factory() as session:
        execution = await session.get(ExecutionRecord, "44444444-4444-4444-4444-444444444444")
        events = list(
            (
                await session.scalars(
                    select(ExecutionEventRecord).order_by(ExecutionEventRecord.sequence)
                )
            ).all()
        )
        assert execution is not None and execution.status == "succeeded"
        assert [event.event_type for event in events] == ["execution_started", "execution_finished"]
        assert events[-1].data["token"] == "[REDACTED]"
    await engine.dispose()


@pytest.mark.asyncio
async def test_reap_stuck_executions_async_marks_and_logs_stale_running_rows(
    secrets_dir: object,
) -> None:
    from datetime import UTC, datetime, timedelta

    from capataz_runner.config import Settings
    from capataz_runner.tasks import reap_stuck_executions_async

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        _seed_service_and_connector(session)
        session.add(
            ActionDefinitionRecord(
                id="11111111-1111-1111-1111-111111111111",
                service_id="service",
                key="restart",
                connector_id="local",
                action_type="ansible",
                enabled=True,
                config={},
            )
        )
        session.add(
            ExecutionRecord(
                id="88888888-8888-8888-8888-888888888888",
                service_id="service",
                action_definition_id="11111111-1111-1111-1111-111111111111",
                status="running",
                started_at=datetime.now(UTC) - timedelta(hours=2),
            )
        )
        await session.commit()

    settings = Settings(secrets_dir=secrets_dir)
    reaped = await reap_stuck_executions_async(settings=settings, session_factory=factory)
    assert reaped == ["88888888-8888-8888-8888-888888888888"]
    async with factory() as session:
        execution = await session.get(ExecutionRecord, "88888888-8888-8888-8888-888888888888")
        events = list(
            (
                await session.scalars(
                    select(ExecutionEventRecord).order_by(ExecutionEventRecord.sequence)
                )
            ).all()
        )
        assert execution is not None and execution.status == "failed"
        assert execution.error_code == "execution_reaped"
        assert [event.event_type for event in events] == ["execution_reaped"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_reap_stuck_executions_task_disposes_the_engine_before_returning(
    secrets_dir: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-082: each Celery task wraps its coroutine in ``asyncio.run()``, which closes the event

    loop the moment the coroutine returns. The engine built for that run is bound to that loop, so
    it must be disposed *inside* the coroutine — before the loop closes — or its connection pool
    leaks (unreachable, un-disposable) once the loop is gone. This pins the fix in
    ``_reap_stuck_executions_with_disposal``/``_process_execution_with_disposal`` (tasks.py).
    """
    from capataz_runner import tasks
    from capataz_runner.config import Settings

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    dispose_calls: list[None] = []
    original_dispose = type(engine).dispose

    async def spy_dispose(self: object, *args: object, **kwargs: object) -> None:
        dispose_calls.append(None)
        await original_dispose(self, *args, **kwargs)

    # AsyncEngine.dispose is a read-only instance attribute (backed by __slots__), so the spy has
    # to replace it on the class, not the instance — scoped to this test by monkeypatch.
    monkeypatch.setattr(type(engine), "dispose", spy_dispose)
    monkeypatch.setattr(
        tasks, "create_engine_and_session_factory", lambda database_url: (engine, factory)
    )

    settings = Settings(secrets_dir=secrets_dir)
    result = await tasks._reap_stuck_executions_with_disposal(settings)

    assert result == []
    assert len(dispose_calls) == 1


async def _seed_queued_execution(
    factory: async_sessionmaker[object], execution_id: str = "77777777-7777-7777-7777-777777777777"
) -> None:
    async with factory() as session:
        _seed_service_and_connector(session)
        session.add(
            ActionDefinitionRecord(
                id="11111111-1111-1111-1111-111111111111",
                service_id="service",
                key="restart",
                connector_id="local",
                action_type="ansible",
                enabled=True,
                config={"playbook": "playbooks/restart_service.yml", "limit": "local-mock"},
            )
        )
        session.add(
            ExecutionRecord(
                id=execution_id,
                service_id="service",
                action_definition_id="11111111-1111-1111-1111-111111111111",
                status="queued",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_process_execution_async_classifies_action_configuration_error_as_rejected(
    secrets_dir: object,
) -> None:
    """CR-067: pins the `except ActionConfigurationError` branch (part of CR-042/044's fix area,

    previously untested) — status must be `rejected`, not the generic `failed`.
    """
    from capataz_runner.actions import ActionConfigurationError
    from capataz_runner.config import Settings
    from capataz_runner.tasks import process_execution_async

    class RejectingExecutor:
        async def execute(self, job: object) -> ExecutionResult:
            raise ActionConfigurationError("container selectors are empty")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    execution_id = "77777777-7777-7777-7777-777777777771"
    await _seed_queued_execution(factory, execution_id)

    result = await process_execution_async(
        execution_id,
        settings=Settings(secrets_dir=secrets_dir),
        session_factory=factory,
        executor=RejectingExecutor(),  # type: ignore[arg-type]
    )
    assert result == "rejected"
    async with factory() as session:
        execution = await session.get(ExecutionRecord, execution_id)
        events = list(
            (
                await session.scalars(
                    select(ExecutionEventRecord).order_by(ExecutionEventRecord.sequence)
                )
            ).all()
        )
        assert execution is not None
        assert execution.status == "rejected"
        assert execution.error_code == "action_rejected"
        assert [event.event_type for event in events] == ["execution_started", "execution_rejected"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_process_execution_async_classifies_timeout_error_as_timed_out(
    secrets_dir: object,
) -> None:
    """CR-067: pins the `except TimeoutError` branch."""
    from capataz_runner.config import Settings
    from capataz_runner.tasks import process_execution_async

    class TimingOutExecutor:
        async def execute(self, job: object) -> ExecutionResult:
            raise TimeoutError

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    execution_id = "77777777-7777-7777-7777-777777777772"
    await _seed_queued_execution(factory, execution_id)

    result = await process_execution_async(
        execution_id,
        settings=Settings(secrets_dir=secrets_dir),
        session_factory=factory,
        executor=TimingOutExecutor(),  # type: ignore[arg-type]
    )
    assert result == "timed_out"
    async with factory() as session:
        execution = await session.get(ExecutionRecord, execution_id)
        assert execution is not None
        assert execution.status == "timed_out"
        assert execution.error_code == "execution_timeout"
    await engine.dispose()


@pytest.mark.asyncio
async def test_process_execution_async_sanitizes_a_secret_embedded_in_an_unexpected_exception(
    secrets_dir: object, caplog: pytest.LogCaptureFixture
) -> None:
    """CR-044/CR-067: the exact scenario that motivated CR-044 — an unexpected exception (e.g. a

    DB/connection error) whose message embeds a real secret must never reach the logs verbatim.
    Only the generic `except Exception` branch sanitizes with `known_secrets`, not just
    `sanitize_text`'s built-in patterns — this proves that specific redaction actually fires.
    """
    from capataz_runner.config import Settings
    from capataz_runner.tasks import process_execution_async

    settings = Settings(secrets_dir=secrets_dir)
    leaked_password = settings.postgres_password.get_secret_value()

    class FailingExecutor:
        async def execute(self, job: object) -> ExecutionResult:
            raise RuntimeError(f"connect failed: postgresql://user:{leaked_password}@host/db")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    execution_id = "77777777-7777-7777-7777-777777777773"
    await _seed_queued_execution(factory, execution_id)

    with caplog.at_level("ERROR"):
        result = await process_execution_async(
            execution_id,
            settings=settings,
            session_factory=factory,
            executor=FailingExecutor(),  # type: ignore[arg-type]
        )
    assert result == "failed"
    assert leaked_password not in caplog.text
    async with factory() as session:
        execution = await session.get(ExecutionRecord, execution_id)
        assert execution is not None
        assert execution.status == "failed"
        assert execution.error_code == "execution_failed"
        # The persisted summary is a static message, never the raw exception (defence in depth
        # beyond the log sanitization above).
        assert leaked_password not in (execution.error_summary or "")
    await engine.dispose()


def test_known_secrets_collects_the_database_and_redis_credentials(secrets_dir: object) -> None:
    """CR-067: `_known_secrets` (introduced by CR-044) had no test of its own."""
    from capataz_runner.config import Settings
    from capataz_runner.tasks import _known_secrets

    settings = Settings(secrets_dir=secrets_dir)
    secrets = _known_secrets(settings)
    assert settings.postgres_password.get_secret_value() in secrets
    assert settings.redis_password.get_secret_value() in secrets
    assert len(secrets) == 2


def test_known_secrets_skips_a_getter_that_raises_instead_of_failing_outright(
    tmp_path: Path,
) -> None:
    """A missing/unreadable secret file must not crash the error-logging path itself — losing

    one redaction target is far better than losing the ability to log the original error at all.
    """
    from capataz_runner.config import Settings
    from capataz_runner.tasks import _known_secrets

    # A subdirectory, not tmp_path itself: the autouse capataz_test_environment fixture (via its
    # own secrets_dir dependency) already populates tmp_path with fake-but-real secret files —
    # this needs a genuinely empty directory to exercise "every secret read raises".
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    settings = Settings(secrets_dir=empty_dir)
    assert _known_secrets(settings) == ()


@pytest.mark.asyncio
async def test_process_execution_sync_wrapper_disposes_the_engine_before_returning(
    secrets_dir: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-067/CR-082: `process_execution` (the real `@app.task`, not `process_execution_async`)

    had zero test coverage — including no coverage of its own engine-disposal wrapper.
    """
    import asyncio

    from capataz_runner import tasks
    from capataz_runner.config import Settings

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    execution_id = "77777777-7777-7777-7777-777777777774"
    await _seed_queued_execution(factory, execution_id)

    dispose_calls: list[None] = []
    original_dispose = type(engine).dispose

    async def spy_dispose(self: object, *args: object, **kwargs: object) -> None:
        dispose_calls.append(None)
        await original_dispose(self, *args, **kwargs)

    monkeypatch.setattr(type(engine), "dispose", spy_dispose)
    monkeypatch.setattr(
        tasks, "create_engine_and_session_factory", lambda database_url: (engine, factory)
    )
    monkeypatch.setattr(tasks, "Settings", lambda: Settings(secrets_dir=secrets_dir))

    class RejectingExecutor:
        async def execute(self, job: object) -> ExecutionResult:
            from capataz_runner.actions import ActionConfigurationError

            raise ActionConfigurationError("no selectors")

    monkeypatch.setattr(
        tasks, "PersistentWorkerAutomationExecutor", lambda settings: RejectingExecutor()
    )

    # bind=True on the @app.task decorator injects the task instance as the first positional
    # argument automatically — passing it explicitly would collide with Celery's own injection.
    result = await asyncio.to_thread(tasks.process_execution, execution_id)

    assert result == "rejected"
    assert len(dispose_calls) == 1


async def _load(
    *,
    connector_type: str = "ansible",
    action_type: str = "ansible",
    connector_config: dict[str, Any] | None = None,
    resources: dict[str, bytes] | None = None,
    ciphertext_override: bytes | None = None,
) -> AutomationJob:
    from capataz_runner.crypto import ResourceDecryptor
    from capataz_runner.tasks import _load_job

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            _seed_service_and_connector(
                session,
                connector_type=connector_type,
                connector_config=connector_config,
                resources=resources,
            )
            if ciphertext_override is not None:
                await session.flush()
                resource = await session.get(ResourceRecord, "local_key")
                assert resource is not None
                resource.ciphertext = ciphertext_override
            session.add(
                ActionDefinitionRecord(
                    id="11111111-1111-1111-1111-111111111111",
                    service_id="service",
                    key="restart",
                    connector_id="local",
                    action_type=action_type,
                    enabled=True,
                    config={"playbook": "playbooks/restart_service.yml", "limit": "local-mock"},
                )
            )
            session.add(
                ExecutionRecord(
                    id="99999999-9999-9999-9999-999999999999",
                    service_id="service",
                    action_definition_id="11111111-1111-1111-1111-111111111111",
                    params={"service": "x"},
                )
            )
            await session.commit()
        async with factory() as session:
            return await _load_job(
                session,
                "99999999-9999-9999-9999-999999999999",
                ResourceDecryptor((TEST_MASTER_KEY,)),
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_load_job_decrypts_the_connector_resources_in_memory() -> None:
    job = await _load()
    assert job.action_type == "ansible"
    assert job.connector_config == LOCAL_ANSIBLE
    assert job.runtime == {"environment_id": "1", "containers": []}
    assert job.params == {"service": "x"}
    assert job.secrets == {"private_key": b"KEY-MATERIAL\n", "known_hosts": b"kh\n"}


@pytest.mark.asyncio
async def test_load_job_rejects_a_connector_whose_type_differs_from_the_action() -> None:
    from capataz_runner.actions import ActionConfigurationError

    with pytest.raises(ActionConfigurationError, match="does not match"):
        await _load(connector_type="ssh")


@pytest.mark.asyncio
async def test_load_job_rejects_a_missing_resource() -> None:
    from capataz_runner.actions import ActionConfigurationError

    with pytest.raises(ActionConfigurationError, match="local_known_hosts"):
        await _load(resources={"local_key": b"KEY"})


@pytest.mark.asyncio
async def test_load_job_turns_an_undecryptable_resource_into_a_rejection() -> None:
    from capataz_runner.actions import ActionConfigurationError

    wrong_key = Fernet(Fernet.generate_key()).encrypt(b"KEY")
    with pytest.raises(ActionConfigurationError):
        await _load(ciphertext_override=wrong_key)
