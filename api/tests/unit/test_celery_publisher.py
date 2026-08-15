"""Unit tests for infrastructure/celery/publisher.py."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from capataz_api.infrastructure.celery.publisher import CeleryExecutionPublisher


@pytest.mark.asyncio
async def test_enqueue_sends_task_with_string_execution_id_and_configured_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = CeleryExecutionPublisher("redis://fake:6379/0", queue="automation")

    fake_result = MagicMock()
    fake_result.id = "task-abc"
    send_task = MagicMock(return_value=fake_result)
    monkeypatch.setattr(publisher.app, "send_task", send_task)

    execution_id = uuid4()
    task_id = await publisher.enqueue(execution_id)

    assert task_id == "task-abc"
    send_task.assert_called_once_with(
        "capataz_runner.tasks.process_execution",
        kwargs={"execution_id": str(execution_id)},
        queue="automation",
    )


@pytest.mark.asyncio
async def test_enqueue_uses_default_queue_name_when_not_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = CeleryExecutionPublisher("redis://fake:6379/0")
    assert publisher.queue == "automation"

    fake_result = MagicMock()
    fake_result.id = "task-xyz"
    monkeypatch.setattr(publisher.app, "send_task", MagicMock(return_value=fake_result))

    task_id = await publisher.enqueue(uuid4())
    assert task_id == "task-xyz"
