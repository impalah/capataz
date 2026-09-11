from __future__ import annotations

import asyncio
import json
import shlex
import signal
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest

from capataz_runner.actions import (
    ActionConfigurationError,
    ResolvedPortainerAction,
    ResolvedSshAction,
    resolve_action,
)
from capataz_runner.config import Settings
from capataz_runner.executor import (
    PersistentWorkerAutomationExecutor,
    PortainerClient,
    ProcessResult,
    build_ansible_command,
    build_ssh_command,
    collect_known_secrets,
    materialized_secrets,
    parse_ansible_result,
    parse_ssh_result,
    run_subprocess,
)
from capataz_runner.ports import AutomationJob, ExecutionResult

RUNNER_ROOT = Path(__file__).resolve().parents[1]
HOMELAB = {
    "inventory": "inventories/homelab.yml",
    "private_key": "k",
    "known_hosts": "kh",
    "vault_password": "v",
}
SSH_TARGET = {"host": "mole.home.arpa", "port": 22, "user": "capataz"}
PORTAINER = {"url": "https://portainer.home.arpa", "token": "portainer_token", "verify_tls": True}
CREDENTIALS = {
    "private_key": Path("/secrets/private_key"),
    "known_hosts": Path("/secrets/known_hosts"),
    "vault_password": Path("/secrets/vault_password"),
}


def configured_settings(secrets_dir: Path, **overrides: Any) -> Settings:
    return Settings(secrets_dir=secrets_dir, project_root=RUNNER_ROOT, **overrides)


def portainer_job(**overrides: Any) -> AutomationJob:
    values: dict[str, Any] = {
        "execution_id": "e",
        "service_id": "open-webui",
        "action_type": "portainer",
        "action_config": {"operation": "restart", "target": "selected_containers"},
        "connector_config": PORTAINER,
        "runtime": {"environment_id": "3", "containers": [{"name": "open-webui"}]},
        "secrets": {"token": b"portainer-super-secret\n"},
    }
    return AutomationJob(**{**values, **overrides})


def mock_portainer(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "capataz_runner.executor.httpx.AsyncClient",
        lambda *args, **kwargs: real_async_client(*args, transport=transport, **kwargs),
    )


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


# --- credentials ----------------------------------------------------------------------------


def test_materialized_secrets_are_owner_only_and_removed_afterwards() -> None:
    with materialized_secrets({"private_key": b"KEY", "vault_password": b"v"}) as paths:
        directory = paths["private_key"].parent
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        for path in paths.values():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        # OpenSSH needs a trailing newline on key files; the vault password is left untouched.
        assert paths["private_key"].read_bytes() == b"KEY\n"
        assert paths["vault_password"].read_bytes() == b"v"
    assert not directory.exists()


def test_materialized_secrets_are_removed_even_when_the_execution_raises() -> None:
    with pytest.raises(RuntimeError), materialized_secrets({"known_hosts": b"kh\n"}) as paths:
        directory = paths["known_hosts"].parent
        raise RuntimeError
    assert not directory.exists()


def test_known_secrets_include_decrypted_resources_and_their_long_lines(secrets_dir: Path) -> None:
    key = b"-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END-----\n"
    job = portainer_job(secrets={"token": b"tok-123\n", "private_key": key})
    secrets = collect_known_secrets(configured_settings(secrets_dir), job)
    assert "postgres-super-secret" in secrets and "redis-super-secret" in secrets
    assert "tok-123" in secrets
    assert "b3BlbnNzaC1rZXktdjEAAAAA" in secrets
    assert key.decode().strip() in secrets


def test_known_secrets_is_empty_when_every_secret_is_unreadable(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert collect_known_secrets(Settings(secrets_dir=empty_dir)) == ()


# --- commands -------------------------------------------------------------------------------


def test_build_ansible_command_is_a_fixed_argument_vector(secrets_dir: Path) -> None:
    action = resolve_action(
        "ansible",
        {
            "playbook": "playbooks/restart_service.yml",
            "limit": "node-ai-01",
            "extra_vars": {"service": "open-webui"},
        },
        connector_config={**HOMELAB, "user": "deploy"},
    )
    assert not isinstance(action, (ResolvedPortainerAction, ResolvedSshAction))
    command = build_ansible_command(action, configured_settings(secrets_dir), CREDENTIALS)
    assert command[0] == "ansible-playbook"
    assert command[command.index("--inventory") + 1] == str(RUNNER_ROOT / "inventories/homelab.yml")
    assert command[command.index("--private-key") + 1] == "/secrets/private_key"
    assert (
        "UserKnownHostsFile=/secrets/known_hosts" in command[command.index("--ssh-common-args") + 1]
    )
    assert command[command.index("--vault-password-file") + 1] == "/secrets/vault_password"
    assert command[command.index("--user") + 1] == "deploy"
    assert "open-webui" in command[command.index("--extra-vars") + 1]
    assert ";" not in " ".join(command)


def test_build_ansible_command_requires_the_key_resources(secrets_dir: Path) -> None:
    action = resolve_action(
        "ansible",
        {"playbook": "playbooks/restart_service.yml", "limit": "node-ai-01"},
        connector_config=HOMELAB,
    )
    assert not isinstance(action, (ResolvedPortainerAction, ResolvedSshAction))
    command = build_ansible_command(
        action,
        configured_settings(secrets_dir),
        {"private_key": CREDENTIALS["private_key"], "known_hosts": CREDENTIALS["known_hosts"]},
    )
    assert "--vault-password-file" not in command
    with pytest.raises(ActionConfigurationError, match="does not provide a known_hosts"):
        build_ansible_command(action, configured_settings(secrets_dir), {})
    with pytest.raises(ActionConfigurationError, match="does not provide a private_key"):
        build_ansible_command(
            action, configured_settings(secrets_dir), {"known_hosts": CREDENTIALS["known_hosts"]}
        )


def test_build_ssh_command_pins_host_keys_and_quotes_the_remote_argv() -> None:
    action = ResolvedSshAction(
        "disk_usage", ("df", "-h", "/srv/my data"), "mole.home.arpa", 2222, "capataz", 60
    )
    command = build_ssh_command(action, CREDENTIALS)
    assert command[:3] == ("ssh", "-i", "/secrets/private_key")
    for option in (
        "BatchMode=yes",
        "IdentitiesOnly=yes",
        "StrictHostKeyChecking=yes",
        "UserKnownHostsFile=/secrets/known_hosts",
    ):
        assert option in command
    assert command[command.index("-p") + 1] == "2222"
    assert command[command.index("-l") + 1] == "capataz"
    # The host comes after "--", so it can never be parsed as an ssh option.
    assert command[-3:-1] == ("--", "mole.home.arpa")
    assert shlex.split(command[-1]) == ["df", "-h", "/srv/my data"]


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
        stdout = FakeStream(b"ok secret-value")
        stderr = FakeStream(b"")

        async def wait(self) -> None:
            return None

    async def fake_exec(*args: object, **kwargs: object) -> Process:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr("capataz_runner.executor.asyncio.create_subprocess_exec", fake_exec)
    result = await run_subprocess(
        ("ansible-playbook", "playbooks/check_connectivity.yml"),
        cwd=Path("/tmp"),
        timeout_seconds=1,
        known_secrets=("secret-value",),
    )
    assert result.returncode == 0
    assert "secret-value" not in result.stdout
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

    result = await run_subprocess(
        ("ansible-playbook", "playbooks/check_connectivity.yml"),
        cwd=Path("/tmp"),
        timeout_seconds=0.01,  # type: ignore[arg-type]
        termination_grace_seconds=0.01,
    )
    assert result.timed_out is True
    assert killpg_calls == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]


@pytest.mark.asyncio
async def test_run_subprocess_caps_captured_stream_size(
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
    result = await run_subprocess(
        ("ansible-playbook", "playbooks/check_connectivity.yml"),
        cwd=Path("/tmp"),
        timeout_seconds=1,
    )
    assert result.stdout == "AAAAABBBBB"
    assert len(result.stdout) == 10


@pytest.mark.parametrize(
    ("process_result", "expected_status", "expected_code"),
    [
        (ProcessResult(0, "ok", ""), "succeeded", None),
        (ProcessResult(2, "", "failed"), "failed", "ansible_failed"),
        (ProcessResult(-1, "", "", timed_out=True), "timed_out", "ansible_timeout"),
    ],
)
def test_parse_ansible_results(
    process_result: ProcessResult, expected_status: str, expected_code: str | None
) -> None:
    result = parse_ansible_result(process_result)
    assert result.status == expected_status
    assert result.error_code == expected_code


def test_parse_ssh_results_use_their_own_error_codes() -> None:
    assert parse_ssh_result(ProcessResult(255, "", "denied")).error_code == "ssh_failed"
    assert parse_ssh_result(ProcessResult(-1, "", "", timed_out=True)).error_code == "ssh_timeout"
    assert parse_ssh_result(ProcessResult(0, "up 3 days", "")).data == {"output": "up 3 days"}


# --- selectors ------------------------------------------------------------------------------


def test_container_resolution_requires_service_selectors() -> None:
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


# --- Portainer ------------------------------------------------------------------------------


def test_portainer_client_is_built_from_the_connector_and_its_token(secrets_dir: Path) -> None:
    client = PortainerClient.from_job(portainer_job(), configured_settings(secrets_dir))
    assert client._token == "portainer-super-secret"
    assert client._base_url == "https://portainer.home.arpa"


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"connector_config": {**PORTAINER, "url": "http://portainer.home.arpa"}}, "HTTPS"),
        ({"secrets": {}}, "token"),
        ({"secrets": {"token": b"\n"}}, "empty"),
    ],
)
def test_portainer_client_rejects_plain_http_and_missing_tokens(
    secrets_dir: Path, overrides: dict[str, Any], match: str
) -> None:
    with pytest.raises(ActionConfigurationError, match=match):
        PortainerClient.from_job(portainer_job(**overrides), configured_settings(secrets_dir))


@pytest.mark.asyncio
async def test_portainer_client_sends_the_connector_token(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("X-API-Key"))
        if request.url.path.endswith("/json"):
            return httpx.Response(200, json=[{"Id": "c1", "Names": ["/ollama"]}])
        return httpx.Response(204)

    mock_portainer(monkeypatch, handler)
    client = PortainerClient("https://portainer.home.arpa/", "tok", 5.0)
    result = await client.execute(
        ResolvedPortainerAction(operation="restart"), "5", {"containers": [{"name": "ollama"}]}
    )
    assert result.status == "succeeded"
    assert seen == ["tok", "tok"]


@pytest.mark.asyncio
async def test_portainer_client_force_updates_swarm_service_on_restart(
    monkeypatch: pytest.MonkeyPatch,
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

    mock_portainer(monkeypatch, handler)
    client = PortainerClient("https://portainer.home.arpa", "tok", 5.0)
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
    monkeypatch: pytest.MonkeyPatch,
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

    mock_portainer(monkeypatch, handler)
    client = PortainerClient("https://portainer.home.arpa", "tok", 5.0)
    result = await client.execute(
        ResolvedPortainerAction(operation="stop", target="selected_services"),
        "7",
        {"services": [{"name": "authentik-server", "replicas": 3}]},
        "homelab-swarm",
    )
    assert result.status == "succeeded"
    assert update_calls[0]["Mode"]["Replicated"]["Replicas"] == 0


@pytest.mark.asyncio
async def test_portainer_client_treats_304_as_already_in_desired_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Docker reuses 304 to mean "already started/stopped"; it must not be treated as an error."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/json"):
            return httpx.Response(200, json=[{"Id": "c1", "Names": ["/ollama"]}])
        if request.url.path.endswith("/start"):
            return httpx.Response(304)
        return httpx.Response(404)

    mock_portainer(monkeypatch, handler)
    client = PortainerClient("https://portainer.home.arpa", "tok", 5.0)
    result = await client.execute(
        ResolvedPortainerAction(operation="start"),
        "5",
        {"containers": [{"name": "ollama"}], "aggregation": "all_required"},
    )
    assert result.status == "succeeded"


@pytest.mark.asyncio
async def test_portainer_client_logs_operation_redacts_known_patterns_but_not_unrecognized_secrets(
    monkeypatch: pytest.MonkeyPatch,
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

    mock_portainer(monkeypatch, handler)
    client = PortainerClient("https://portainer.home.arpa", "tok", 5.0)
    result = await client.execute(
        ResolvedPortainerAction(operation="logs"),
        "5",
        {"containers": [{"name": "ollama"}], "aggregation": "all_required"},
    )
    assert result.status == "succeeded"
    logs = result.data["logs"]["c1"]
    assert "Bearer xyz" not in logs
    assert "DB_PASS=hunter2" in logs


# --- executor -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persistent_executor_uses_portainer_only_for_the_runtime_selectors(
    secrets_dir: Path,
) -> None:
    runtime = {
        "environment_id": "3",
        "stack_name": "ai",
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
            assert (environment_id, selectors, stack_name) == ("3", runtime, "ai")
            return ExecutionResult("succeeded", "selected only", {"containers": 1})

    executor = PersistentWorkerAutomationExecutor(configured_settings(secrets_dir), FakePortainer())  # type: ignore[arg-type]
    result = await executor.execute(portainer_job(runtime=runtime))
    assert result.status == "succeeded"


@pytest.mark.asyncio
async def test_persistent_executor_rejects_a_portainer_action_without_runtime(
    secrets_dir: Path,
) -> None:
    executor = PersistentWorkerAutomationExecutor(configured_settings(secrets_dir))
    with pytest.raises(ActionConfigurationError, match="runtime"):
        await executor.execute(portainer_job(runtime=None))


@pytest.mark.asyncio
async def test_ansible_execution_materializes_credentials_and_caps_the_timeout(
    monkeypatch: pytest.MonkeyPatch, secrets_dir: Path
) -> None:
    """settings.execution_timeout_seconds caps action.timeout_seconds, never extends it; the
    credential files exist while the process runs and are gone afterwards."""
    captured: dict[str, Any] = {}

    async def fake_run_subprocess(
        command: tuple[str, ...], *, cwd: object, timeout_seconds: int, **kwargs: Any
    ) -> ProcessResult:
        key_path = Path(command[command.index("--private-key") + 1])
        captured.update(
            timeout_seconds=timeout_seconds,
            key_path=key_path,
            key=_read_bytes(key_path),
            known_secrets=kwargs["known_secrets"],
        )
        return ProcessResult(0, "ok", "")

    monkeypatch.setattr("capataz_runner.executor.run_subprocess", fake_run_subprocess)
    job = AutomationJob(
        execution_id="e",
        service_id="open-webui",
        action_type="ansible",
        action_config={
            "playbook": "playbooks/backup_service.yml",
            "limit": "node-ai-01",
            "timeout_seconds": 600,
        },
        connector_config=HOMELAB,
        secrets={
            "private_key": b"PRIVATE-KEY-MATERIAL",
            "known_hosts": b"kh\n",
            "vault_password": b"v",
        },
    )
    executor = PersistentWorkerAutomationExecutor(
        configured_settings(secrets_dir, execution_timeout_seconds=120)
    )
    result = await executor.execute(job)
    assert result.status == "succeeded"
    assert captured["timeout_seconds"] == 120
    assert captured["key"] == b"PRIVATE-KEY-MATERIAL\n"
    assert "PRIVATE-KEY-MATERIAL" in captured["known_secrets"]
    assert not captured["key_path"].exists()


@pytest.mark.asyncio
async def test_ssh_execution_runs_an_allow_listed_command(
    monkeypatch: pytest.MonkeyPatch, secrets_dir: Path
) -> None:
    captured: dict[str, Any] = {}

    async def fake_run_subprocess(
        command: tuple[str, ...], *, cwd: object, timeout_seconds: int, **kwargs: Any
    ) -> ProcessResult:
        captured.update(command=command, timeout_seconds=timeout_seconds)
        return ProcessResult(0, "Filesystem  Size", "")

    monkeypatch.setattr("capataz_runner.executor.run_subprocess", fake_run_subprocess)
    job = AutomationJob(
        execution_id="e",
        service_id="mole",
        action_type="ssh",
        action_config={"command_id": "disk_usage", "params": {"path": "/srv"}},
        connector_config={**SSH_TARGET, "private_key": "k", "known_hosts": "kh"},
        secrets={"private_key": b"KEY", "known_hosts": b"kh"},
    )
    result = await PersistentWorkerAutomationExecutor(configured_settings(secrets_dir)).execute(job)
    assert result.status == "succeeded"
    assert captured["command"][-2:] == ("mole.home.arpa", "df -h /srv")
    assert captured["timeout_seconds"] == 60


@pytest.mark.asyncio
async def test_ssh_execution_rejects_unknown_commands_and_a_broken_allow_list(
    tmp_path: Path, secrets_dir: Path
) -> None:
    job = AutomationJob(
        execution_id="e",
        service_id="mole",
        action_type="ssh",
        action_config={"command_id": "rm_everything"},
        connector_config=SSH_TARGET,
    )
    executor = PersistentWorkerAutomationExecutor(configured_settings(secrets_dir))
    with pytest.raises(ActionConfigurationError, match="not allow-listed"):
        await executor.execute(job)
    (tmp_path / "ssh_commands.yml").write_text("commands: [\n", encoding="utf-8")
    broken = PersistentWorkerAutomationExecutor(
        Settings(secrets_dir=secrets_dir, project_root=tmp_path)
    )
    with pytest.raises(ActionConfigurationError, match="allow-list is invalid"):
        await broken.execute(job)


def test_automation_job_repr_never_contains_decrypted_secrets() -> None:
    assert "portainer-super-secret" not in repr(portainer_job())
