from __future__ import annotations

import asyncio
import json
import signal
from pathlib import Path
from typing import Any

import httpx
import pytest

from capataz_runner.actions import ResolvedPortainerAction, resolve_action
from capataz_runner.config import Settings
from capataz_runner.executor import (
    AnsibleProcessResult,
    PortainerClient,
    build_ansible_command,
    parse_ansible_result,
    run_ansible_subprocess,
)


def configured_settings(secrets_dir: Path) -> Settings:
    return Settings(
        secrets_dir=secrets_dir, project_root=Path("/home/user/workspace/capataz/runner")
    )


def test_build_command_is_fixed_argument_vector(secrets_dir: Path) -> None:
    action = resolve_action(
        "ansible",
        {
            "playbook": "playbooks/restart_service.yml",
            "inventory": "inventories/homelab.yml",
            "limit": "node-ai-01",
            "extra_vars": {"service": "open-webui"},
        },
    )
    command = build_ansible_command(action, configured_settings(secrets_dir))
    assert command[0] == "ansible-playbook"
    assert ";" not in " ".join(command)
    assert "shell" not in command
    assert "open-webui" in command[command.index("--extra-vars") + 1]


@pytest.mark.asyncio
async def test_subprocess_execution_never_requests_a_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeStream:
        def __init__(self, data: bytes) -> None:
            self._data = data

        async def read(self, n: int = -1) -> bytes:
            data, self._data = self._data, b""
            return data

    class Process:
        returncode = 0
        stdout = FakeStream(b"ok")
        stderr = FakeStream(b"")

        async def wait(self) -> None:
            return None

    async def fake_exec(*args: object, **kwargs: object) -> Process:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr("capataz_runner.executor.asyncio.create_subprocess_exec", fake_exec)
    result = await run_ansible_subprocess(
        ("ansible-playbook", "playbooks/check_connectivity.yml"),
        cwd=Path("/tmp"),
        timeout_seconds=1,
    )
    assert result.returncode == 0
    assert captured["args"] == ("ansible-playbook", "playbooks/check_connectivity.yml")
    assert "shell" not in captured["kwargs"]


@pytest.mark.asyncio
async def test_timeout_signals_the_process_group_and_falls_back_to_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killpg_calls: list[tuple[int, int]] = []

    def fake_killpg(pid: int, sig: int) -> None:
        killpg_calls.append((pid, sig))

    class HangingStream:
        async def read(self, n: int = -1) -> bytes:
            await asyncio.sleep(10)
            return b""

    class HangingProcess:
        pid = 4242
        returncode = None
        stdout = HangingStream()
        stderr = HangingStream()

        async def wait(self) -> None:
            # Never responds to SIGTERM within the grace period, forcing the SIGKILL fallback.
            await asyncio.sleep(10)

    async def fake_exec(*args: object, **kwargs: object) -> HangingProcess:
        assert kwargs.get("start_new_session") is True
        return HangingProcess()

    monkeypatch.setattr("capataz_runner.executor.asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr("capataz_runner.executor.os.killpg", fake_killpg)

    result = await run_ansible_subprocess(
        ("ansible-playbook", "playbooks/check_connectivity.yml"),
        cwd=Path("/tmp"),
        timeout_seconds=0.01,
        termination_grace_seconds=0.01,
    )
    assert result.timed_out is True
    assert killpg_calls == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]


@pytest.mark.asyncio
async def test_run_ansible_subprocess_caps_captured_stream_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-084: a subprocess dumping far more output than the cap must not grow the capture

    unboundedly — the stream is still fully drained (so the subprocess is never blocked writing
    to a full pipe), but only the first _MAX_CAPTURED_STREAM_BYTES are kept.
    """
    from capataz_runner import executor as executor_module

    monkeypatch.setattr(executor_module, "_MAX_CAPTURED_STREAM_BYTES", 10)

    class ChunkyStream:
        def __init__(self, chunks: list[bytes]) -> None:
            self._chunks = list(chunks)

        async def read(self, n: int = -1) -> bytes:
            return self._chunks.pop(0) if self._chunks else b""

    class Process:
        returncode = 0
        # 6 chunks of 5 bytes = 30 bytes total, well past the 10-byte cap.
        stdout = ChunkyStream([b"AAAAA", b"BBBBB", b"CCCCC", b"DDDDD", b"EEEEE", b"FFFFF"])
        stderr = ChunkyStream([b""])

        async def wait(self) -> None:
            return None

    async def fake_exec(*args: object, **kwargs: object) -> Process:
        return Process()

    monkeypatch.setattr("capataz_runner.executor.asyncio.create_subprocess_exec", fake_exec)
    result = await run_ansible_subprocess(
        ("ansible-playbook", "playbooks/check_connectivity.yml"),
        cwd=Path("/tmp"),
        timeout_seconds=1,
    )
    assert result.stdout == "AAAAABBBBB"
    assert len(result.stdout) == 10


@pytest.mark.parametrize(
    ("process_result", "expected_status", "expected_code"),
    [
        (AnsibleProcessResult(0, "ok", ""), "succeeded", None),
        (AnsibleProcessResult(2, "", "failed"), "failed", "ansible_failed"),
        (AnsibleProcessResult(-1, "", "", timed_out=True), "timed_out", "ansible_timeout"),
    ],
)
def test_parse_ansible_results(
    process_result: AnsibleProcessResult, expected_status: str, expected_code: str | None
) -> None:
    result = parse_ansible_result(process_result)
    assert result.status == expected_status
    assert result.error_code == expected_code


def test_container_resolution_requires_service_selectors() -> None:
    from capataz_runner.actions import ActionConfigurationError
    from capataz_runner.executor import resolve_selected_container_ids

    containers = [
        {"Id": "untrusted-id", "Names": ["/open-webui"], "Labels": {"capataz.service": "ai"}},
        {"Id": "other-id", "Names": ["/other"], "Labels": {}},
    ]
    selectors = {
        "containers": [{"name": "open-webui", "required": True}],
        "aggregation": "all_required",
    }
    assert resolve_selected_container_ids(containers, selectors) == ["untrusted-id"]
    with pytest.raises(ActionConfigurationError):
        resolve_selected_container_ids(containers, {})
    with pytest.raises(ActionConfigurationError):
        resolve_selected_container_ids(containers, {"containers": [{"name": "no-match"}]})


def test_service_resolution_requires_service_selectors() -> None:
    from capataz_runner.actions import ActionConfigurationError
    from capataz_runner.executor import resolve_selected_services

    services = [
        {"ID": "svc-1", "Spec": {"Name": "homelab-swarm_authentik-server"}},
        {"ID": "svc-2", "Spec": {"Name": "homelab-swarm_other"}},
    ]
    selectors = {"services": [{"name": "authentik-server", "replicas": 1}]}
    matched = resolve_selected_services(services, selectors, "homelab-swarm")
    assert [service_id for service_id, _service, _spec in matched] == ["svc-1"]
    with pytest.raises(ActionConfigurationError):
        resolve_selected_services(services, {}, "homelab-swarm")
    with pytest.raises(ActionConfigurationError):
        resolve_selected_services(services, {"services": [{"name": "no-match"}]}, "homelab-swarm")


@pytest.mark.asyncio
async def test_portainer_client_force_updates_swarm_service_on_restart(
    monkeypatch: pytest.MonkeyPatch, secrets_dir: Path
) -> None:
    """restart on a selected_services target must re-post the spec with ForceUpdate bumped."""
    update_calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/services"):
            return httpx.Response(
                200, json=[{"ID": "svc-1", "Spec": {"Name": "homelab-swarm_authentik-server"}}]
            )
        if request.url.path.endswith("/svc-1"):
            return httpx.Response(
                200,
                json={
                    "Version": {"Index": 7},
                    "Spec": {
                        "Name": "homelab-swarm_authentik-server",
                        "TaskTemplate": {"ForceUpdate": 0},
                        "Mode": {"Replicated": {"Replicas": 1}},
                    },
                },
            )
        if request.url.path.endswith("/svc-1/update"):
            update_calls.append({"params": dict(request.url.params), "body": request.content})
            return httpx.Response(200, json={"Warnings": []})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "capataz_runner.executor.httpx.AsyncClient",
        lambda *args, **kwargs: real_async_client(*args, transport=transport, **kwargs),
    )
    client = PortainerClient(configured_settings(secrets_dir))
    result = await client.execute(
        ResolvedPortainerAction(operation="restart", target="selected_services"),
        "7",
        {"services": [{"name": "authentik-server", "replicas": 1}]},
        "homelab-swarm",
    )
    assert result.status == "succeeded"
    assert update_calls[0]["params"]["version"] == "7"
    body = json.loads(update_calls[0]["body"])
    assert body["TaskTemplate"]["ForceUpdate"] == 1
    assert body["Mode"]["Replicated"]["Replicas"] == 1


@pytest.mark.asyncio
async def test_portainer_client_scales_swarm_service_on_stop(
    monkeypatch: pytest.MonkeyPatch, secrets_dir: Path
) -> None:
    """stop on a selected_services target must scale replicas to 0, not remove the service."""
    update_calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/services"):
            return httpx.Response(
                200, json=[{"ID": "svc-1", "Spec": {"Name": "homelab-swarm_authentik-server"}}]
            )
        if request.url.path.endswith("/svc-1") and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "Version": {"Index": 3},
                    "Spec": {
                        "Name": "homelab-swarm_authentik-server",
                        "TaskTemplate": {},
                        "Mode": {"Replicated": {"Replicas": 2}},
                    },
                },
            )
        if request.url.path.endswith("/svc-1/update"):
            update_calls.append(json.loads(request.content))
            return httpx.Response(200, json={"Warnings": []})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "capataz_runner.executor.httpx.AsyncClient",
        lambda *args, **kwargs: real_async_client(*args, transport=transport, **kwargs),
    )
    client = PortainerClient(configured_settings(secrets_dir))
    result = await client.execute(
        ResolvedPortainerAction(operation="stop", target="selected_services"),
        "7",
        {"services": [{"name": "authentik-server", "replicas": 3}]},
        "homelab-swarm",
    )
    assert result.status == "succeeded"
    assert update_calls[0]["Mode"]["Replicated"]["Replicas"] == 0


@pytest.mark.asyncio
async def test_execution_timeout_is_capped_by_settings_ceiling(
    monkeypatch: pytest.MonkeyPatch, secrets_dir: Path
) -> None:
    """settings.execution_timeout_seconds caps action.timeout_seconds, never extends it."""
    from capataz_runner.executor import PersistentWorkerAutomationExecutor
    from capataz_runner.ports import AutomationJob

    captured: dict[str, Any] = {}

    async def fake_run_ansible_subprocess(
        command: object, *, cwd: object, timeout_seconds: int, **kwargs: object
    ) -> AnsibleProcessResult:
        captured["timeout_seconds"] = timeout_seconds
        return AnsibleProcessResult(0, "ok", "")

    monkeypatch.setattr(
        "capataz_runner.executor.run_ansible_subprocess", fake_run_ansible_subprocess
    )
    settings = Settings(
        secrets_dir=secrets_dir,
        project_root=Path("/home/user/workspace/capataz/runner"),
        execution_timeout_seconds=120,
    )
    job = AutomationJob(
        execution_id="e",
        service_id="open-webui",
        action_type="ansible",
        action_config={
            "playbook": "playbooks/backup_service.yml",
            "inventory": "inventories/homelab.yml",
            "limit": "node-ai-01",
            "timeout_seconds": 600,
        },
        service_container_selectors={},
        portainer_environment_id=None,
    )
    executor = PersistentWorkerAutomationExecutor(settings)
    result = await executor.execute(job)
    assert result.status == "succeeded"
    assert captured["timeout_seconds"] == 120


@pytest.mark.asyncio
async def test_persistent_executor_uses_portainer_only_for_selected_containers(
    secrets_dir: Path,
) -> None:
    from capataz_runner.executor import PersistentWorkerAutomationExecutor
    from capataz_runner.ports import AutomationJob, ExecutionResult

    selectors = {
        "containers": [{"name": "open-webui", "required": True}],
        "aggregation": "all_required",
    }

    class FakePortainer:
        async def execute(
            self,
            operation: object,
            environment_id: str,
            selectors: object,
            stack_name: object = None,
        ) -> ExecutionResult:
            assert environment_id == "3"
            assert selectors == {
                "containers": [{"name": "open-webui", "required": True}],
                "aggregation": "all_required",
            }
            return ExecutionResult("succeeded", "selected only", {"containers": 1})

    job = AutomationJob(
        execution_id="e",
        service_id="open-webui",
        action_type="portainer",
        action_config={"operation": "restart", "target": "selected_containers"},
        service_container_selectors=selectors,
        portainer_environment_id="3",
    )
    executor = PersistentWorkerAutomationExecutor(configured_settings(secrets_dir), FakePortainer())  # type: ignore[arg-type]
    result = await executor.execute(job)
    assert result.status == "succeeded"


@pytest.mark.asyncio
async def test_portainer_client_treats_304_as_already_in_desired_state(
    monkeypatch: pytest.MonkeyPatch, secrets_dir: Path
) -> None:
    """Docker reuses 304 to mean "already started/stopped"; it must not be treated as an error."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/json"):
            return httpx.Response(200, json=[{"Id": "c1", "Names": ["/ollama"]}])
        if request.url.path.endswith("/start"):
            return httpx.Response(304)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "capataz_runner.executor.httpx.AsyncClient",
        lambda *args, **kwargs: real_async_client(*args, transport=transport, **kwargs),
    )
    client = PortainerClient(configured_settings(secrets_dir))
    result = await client.execute(
        ResolvedPortainerAction(operation="start"),
        "5",
        {"containers": [{"name": "ollama"}], "aggregation": "all_required"},
    )
    assert result.status == "succeeded"


@pytest.mark.asyncio
async def test_portainer_client_logs_operation_redacts_known_patterns_but_not_unrecognized_secrets(
    monkeypatch: pytest.MonkeyPatch, secrets_dir: Path
) -> None:
    """CR-083: pins the documented residual risk in docs/06-security.en.md (CR-047) — the ``logs``

    branch of ``PortainerClient.execute`` sanitizes container log text with ``sanitize_text``
    alone, *without* passing the action's ``known_secrets``. Generic patterns (like a bearer
    token) are still redacted by ``sanitize_text``'s built-in rules, but a homelab-specific
    secret value with no generic shape (e.g. a raw password behind ``DB_PASS=``) is not — this
    test must start failing loudly, not silently, if that behavior ever changes.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/json"):
            return httpx.Response(200, json=[{"Id": "c1", "Names": ["/ollama"]}])
        if request.url.path.endswith("/logs"):
            return httpx.Response(
                200, text="Authorization: Bearer xyz\nDB_PASS=hunter2\nstarted ok"
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "capataz_runner.executor.httpx.AsyncClient",
        lambda *args, **kwargs: real_async_client(*args, transport=transport, **kwargs),
    )
    client = PortainerClient(configured_settings(secrets_dir))
    result = await client.execute(
        ResolvedPortainerAction(operation="logs"),
        "5",
        {"containers": [{"name": "ollama"}], "aggregation": "all_required"},
    )
    assert result.status == "succeeded"
    logs = result.data["logs"]["c1"]
    assert "Bearer xyz" not in logs
    assert "DB_PASS=hunter2" in logs
