"""Persistent V1 implementation of the runner automation port."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import shutil
import signal
import tempfile
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import SecretStr

from capataz_runner.actions import (
    ActionConfigurationError,
    ResolvedAnsibleAction,
    ResolvedPortainerAction,
    ResolvedSshAction,
    resolve_action,
)
from capataz_runner.config import Settings
from capataz_runner.ports import AutomationExecutorPort, AutomationJob, ExecutionResult
from capataz_runner.sanitization import sanitize_data, sanitize_text
from capataz_runner.ssh_commands import SshCommand, SshCommandsError, load_ssh_commands


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def _repo_file(project_root: Path, relative: str) -> Path:
    root = project_root.resolve()
    candidate = (root / relative).resolve()
    if root not in candidate.parents:
        raise ActionConfigurationError("Repository path escapes the controlled work directory")
    return candidate


# --- credentials ----------------------------------------------------------------------------

_NEWLINE_TERMINATED = frozenset({"private_key", "known_hosts"})


@contextlib.contextmanager
def materialized_secrets(secrets: Mapping[str, bytes]) -> Iterator[dict[str, Path]]:
    """Write decrypted resources to owner-only files for the duration of one execution.

    ansible-playbook/ssh only take key, known_hosts and vault material as file paths. The files
    live in a fresh 0700 directory, are created 0600 with O_EXCL, and are removed on exit —
    including when the execution raises or times out.
    """
    directory = Path(tempfile.mkdtemp(prefix="capataz-secrets-"))
    try:
        paths: dict[str, Path] = {}
        for name, content in secrets.items():
            if name in _NEWLINE_TERMINATED and not content.endswith(b"\n"):
                # OpenSSH rejects a key/known_hosts file whose last line isn't newline-terminated.
                content += b"\n"
            path = directory / name
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
            paths[name] = path
        yield paths
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _credential(credentials: Mapping[str, Path], name: str) -> Path:
    path = credentials.get(name)
    if path is None:
        raise ActionConfigurationError(f"Connector does not provide a {name} resource")
    return path


def collect_known_secrets(settings: Settings, job: AutomationJob | None = None) -> tuple[str, ...]:
    """Every secret value worth redacting from process output or a traceback (best effort).

    A missing/unreadable secret must not break the error-logging path itself: losing one
    redaction target is far better than losing the ability to log the original error.
    """
    values: list[str] = []
    getters: tuple[Callable[[], SecretStr], ...] = (
        lambda: settings.postgres_password,
        lambda: settings.redis_password,
    )
    for getter in getters:
        try:
            values.append(getter().get_secret_value())
        except Exception:
            continue
    for content in job.secrets.values() if job is not None else ():
        text = content.decode("utf-8", errors="ignore").strip()
        values.append(text)
        # A multi-line secret (a private key) can also leak one line at a time.
        values.extend(line.strip() for line in text.splitlines() if len(line.strip()) >= 16)
    return tuple(dict.fromkeys(value for value in values if value))


# --- commands -------------------------------------------------------------------------------


def build_ansible_command(
    action: ResolvedAnsibleAction, settings: Settings, credentials: Mapping[str, Path]
) -> tuple[str, ...]:
    """Build an argument vector; no user-provided text can become shell syntax."""
    playbook = _repo_file(settings.project_root, action.playbook)
    inventory = _repo_file(settings.project_root, action.inventory)
    known_hosts = _credential(credentials, "known_hosts")
    command = [
        "ansible-playbook",
        "--inventory",
        str(inventory),
        "--limit",
        action.limit,
        "--private-key",
        str(_credential(credentials, "private_key")),
        "--ssh-common-args",
        f"-o UserKnownHostsFile={known_hosts} -o StrictHostKeyChecking=yes",
    ]
    if action.user:
        command.extend(("--user", action.user))
    if "vault_password" in credentials:
        command.extend(("--vault-password-file", str(credentials["vault_password"])))
    if action.extra_vars:
        command.extend(
            ("--extra-vars", json.dumps(action.extra_vars, separators=(",", ":"), sort_keys=True))
        )
    command.append(str(playbook))
    return tuple(command)


def build_ssh_command(
    action: ResolvedSshAction, credentials: Mapping[str, Path]
) -> tuple[str, ...]:
    """The local argv is execve'd (no local shell). The remote command is a single string that
    the target's login shell parses, so every element is individually shell-quoted — on top of
    each parameter value already having matched its allow-listed pattern (defence in depth)."""
    known_hosts = _credential(credentials, "known_hosts")
    return (
        "ssh",
        "-i",
        str(_credential(credentials, "private_key")),
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-p",
        str(action.port),
        "-l",
        action.user,
        "--",
        action.host,
        shlex.join(action.argv),
    )


def minimal_subprocess_environment(home: str) -> dict[str, str]:
    """Return a deliberately small, deterministic environment for ansible/ssh subprocesses."""
    path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    return {
        "PATH": path,
        "HOME": home,
        "LANG": "C.UTF-8",
        "ANSIBLE_NOCOLOR": "1",
        "ANSIBLE_HOST_KEY_CHECKING": "True",
        "ANSIBLE_RETRY_FILES_ENABLED": "False",
    }


# CR-084: process.communicate() buffers a subprocess's entire stdout/stderr in memory with no
# upper bound. A verbose playbook (accidental -vvvv, a remote command that dumps a large file to
# stdout) could exhaust the worker container's memory well before timeout_seconds elapses —
# the parsers already only keep the last 4000 chars anyway, so nothing downstream needs more.
_MAX_CAPTURED_STREAM_BYTES = 2 * 1024 * 1024  # 2 MiB per stream


async def _read_bounded(stream: asyncio.StreamReader | None, limit: int) -> bytes:
    """Fully drain `stream` (so the subprocess is never blocked on a full pipe) but keep at

    most `limit` bytes of it in memory — later chunks are read and discarded, not buffered.
    """
    if stream is None:
        return b""
    chunks: list[bytes] = []
    captured = 0
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return b"".join(chunks)
        if captured < limit:
            take = chunk[: limit - captured]
            chunks.append(take)
            captured += len(take)


async def run_subprocess(
    command: tuple[str, ...],
    *,
    cwd: Path,
    timeout_seconds: int,
    known_secrets: tuple[str, ...] = (),
    termination_grace_seconds: float = 10.0,
) -> ProcessResult:
    """Run a fixed command through execve semantics and safely collect bounded diagnostics."""
    # A private, owner-only HOME (rather than a shared world-writable directory like /tmp)
    # so ansible's/ssh's config machinery can't be influenced by other processes on the host.
    home_dir = tempfile.mkdtemp(prefix="capataz-home-")
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            env=minimal_subprocess_environment(home_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # own process group, so per-host SSH children are reaped too
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                asyncio.gather(
                    _read_bounded(process.stdout, _MAX_CAPTURED_STREAM_BYTES),
                    _read_bounded(process.stderr, _MAX_CAPTURED_STREAM_BYTES),
                ),
                timeout=timeout_seconds,
            )
            await process.wait()
        except TimeoutError:
            await _terminate_process_group(process, termination_grace_seconds)
            return ProcessResult(-1, "", "execution timed out", timed_out=True)
        return ProcessResult(
            process.returncode if process.returncode is not None else -1,
            sanitize_text(stdout.decode("utf-8", errors="replace"), known_secrets),
            sanitize_text(stderr.decode("utf-8", errors="replace"), known_secrets),
        )
    finally:
        shutil.rmtree(home_dir, ignore_errors=True)


async def _terminate_process_group(
    process: asyncio.subprocess.Process, grace_seconds: float
) -> None:
    """Signal the whole process group and never block indefinitely on an unresponsive child."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), timeout=grace_seconds)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=grace_seconds)


def _parse_process_result(result: ProcessResult, tool: str, code: str) -> ExecutionResult:
    """Translate process output without treating it as trusted structured data."""
    if result.timed_out:
        return ExecutionResult(
            "timed_out", f"{tool} exceeded its timeout", error_code=f"{code}_timeout"
        )
    output = (result.stdout + "\n" + result.stderr).strip()
    if result.returncode == 0:
        return ExecutionResult("succeeded", f"{tool} completed", {"output": output[-4000:]})
    return ExecutionResult(
        "failed", f"{tool} failed", {"output": output[-4000:]}, error_code=f"{code}_failed"
    )


def parse_ansible_result(result: ProcessResult) -> ExecutionResult:
    return _parse_process_result(result, "Ansible playbook", "ansible")


def parse_ssh_result(result: ProcessResult) -> ExecutionResult:
    return _parse_process_result(result, "SSH command", "ssh")


# --- Portainer ------------------------------------------------------------------------------


def _declared_container_names(selectors: Mapping[str, Any]) -> set[str]:
    """Extract the allow-listed container names from a service runtime's selectors.

    The persisted shape is the API's RuntimeSpec: ``{"containers": [{"name": ..., "required":
    ..., "critical": ...}, ...], ...}`` — the same shape the API's own status adapter consumes.
    """
    declared = selectors.get("containers")
    if not isinstance(declared, list):
        raise ActionConfigurationError("Service runtime selectors have an invalid shape")
    return {
        str(item["name"]).removeprefix("/")
        for item in declared
        if isinstance(item, Mapping) and item.get("name")
    }


def _matches_container(container: Mapping[str, Any], names: set[str]) -> bool:
    raw_names = container.get("Names", [])
    container_names = {str(name).removeprefix("/") for name in raw_names if isinstance(name, str)}
    return bool(container_names & names)


def resolve_selected_container_ids(
    containers: list[Mapping[str, Any]], selectors: Mapping[str, Any]
) -> list[str]:
    """Return IDs received from Portainer only when service-owned selectors match."""
    names = _declared_container_names(selectors)
    if not names:
        raise ActionConfigurationError("Service must declare container selectors")
    ids: list[str] = []
    for container in containers:
        identifier = container.get("Id")
        if isinstance(identifier, str) and _matches_container(container, names):
            ids.append(identifier)
    if not ids:
        raise ActionConfigurationError("No Portainer containers match the service selectors")
    return ids


def _declared_service_specs(selectors: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Same role as ``_declared_container_names`` but for the ``services`` selector shape."""
    declared = selectors.get("services")
    if not isinstance(declared, list):
        raise ActionConfigurationError("Service runtime selectors have an invalid shape")
    return {
        str(item["name"]).removeprefix("/"): item
        for item in declared
        if isinstance(item, Mapping) and item.get("name")
    }


def _full_swarm_service_name(stack_name: object, name: str) -> str:
    return f"{stack_name}_{name}" if isinstance(stack_name, str) and stack_name else name


def resolve_selected_services(
    services: list[Mapping[str, Any]], selectors: Mapping[str, Any], stack_name: object
) -> list[tuple[str, Mapping[str, Any], Mapping[str, Any]]]:
    """Return (service_id, raw Portainer service, declared selector spec) for matching services.

    Matched by ``{stack_name}_{name}`` (Docker's own service naming for a stack deploy) rather
    than by container name, since Swarm mangles per-task container names on every reschedule.
    """
    declared = _declared_service_specs(selectors)
    if not declared:
        raise ActionConfigurationError("Service must declare service selectors")
    by_full_name = {
        _full_swarm_service_name(stack_name, name): spec for name, spec in declared.items()
    }
    matched: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
    for service in services:
        identifier = service.get("ID")
        full_name = service.get("Spec", {}).get("Name")
        if isinstance(identifier, str) and isinstance(full_name, str) and full_name in by_full_name:
            matched.append((identifier, service, by_full_name[full_name]))
    if not matched:
        raise ActionConfigurationError("No Portainer services match the service selectors")
    return matched


class PortainerClient:
    """Small async Portainer Docker-proxy client limited to already selected containers/services."""

    def __init__(self, base_url: str, token: str, timeout: float, verify: bool = True) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ActionConfigurationError("Portainer connector URL must be an HTTPS base URL")
        if not token:
            raise ActionConfigurationError("Portainer connector token is empty")
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._verify = verify

    @classmethod
    def from_job(cls, job: AutomationJob, settings: Settings) -> PortainerClient:
        token = job.secrets.get("token")
        if token is None:
            raise ActionConfigurationError("Portainer connector does not provide a token resource")
        return cls(
            str(job.connector_config.get("url", "")),
            token.decode("utf-8").strip(),
            settings.http_timeout_seconds,
            bool(job.connector_config.get("verify_tls", True)),
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout, headers={"X-API-Key": self._token}, verify=self._verify
        )

    async def execute(
        self,
        operation: ResolvedPortainerAction,
        environment_id: str,
        selectors: Mapping[str, Any],
        stack_name: object = None,
    ) -> ExecutionResult:
        if operation.target == "selected_services":
            return await self._execute_service(operation, environment_id, selectors, stack_name)
        return await self._execute_container(operation, environment_id, selectors)

    async def _execute_container(
        self, operation: ResolvedPortainerAction, environment_id: str, selectors: Mapping[str, Any]
    ) -> ExecutionResult:
        base = f"{self._base_url}/api/endpoints/{environment_id}/docker/containers"
        async with self._client() as client:
            response = await client.get(f"{base}/json", params={"all": "true"})
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
                raise ActionConfigurationError("Portainer returned an invalid container listing")
            ids = resolve_selected_container_ids(payload, selectors)
            if operation.operation == "logs":
                logs: dict[str, str] = {}
                for container_id in ids:
                    log_response = await client.get(
                        f"{base}/{container_id}/logs",
                        params={"stdout": "true", "stderr": "true", "tail": "100"},
                    )
                    log_response.raise_for_status()
                    logs[container_id] = sanitize_text(log_response.text)[-4000:]
                return ExecutionResult("succeeded", "Portainer logs collected", {"logs": logs})
            for container_id in ids:
                response = await client.post(f"{base}/{container_id}/{operation.operation}")
                # Docker reuses 304 to mean "container already in the requested state" for
                # start/stop/restart; httpx treats any 3xx as an unfollowed redirect and would
                # otherwise raise, even though this is the desired outcome, not a failure.
                if response.status_code != 304:
                    response.raise_for_status()
        return ExecutionResult(
            "succeeded", f"Portainer {operation.operation} completed", {"containers": len(ids)}
        )

    async def _execute_service(
        self,
        operation: ResolvedPortainerAction,
        environment_id: str,
        selectors: Mapping[str, Any],
        stack_name: object,
    ) -> ExecutionResult:
        base = f"{self._base_url}/api/endpoints/{environment_id}/docker/services"
        async with self._client() as client:
            response = await client.get(base)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
                raise ActionConfigurationError("Portainer returned an invalid service listing")
            matched = resolve_selected_services(payload, selectors, stack_name)
            if operation.operation == "logs":
                logs = {}
                for service_id, _service, _spec in matched:
                    log_response = await client.get(
                        f"{base}/{service_id}/logs",
                        params={"stdout": "true", "stderr": "true", "tail": "100"},
                    )
                    log_response.raise_for_status()
                    logs[service_id] = sanitize_text(log_response.text)[-4000:]
                return ExecutionResult("succeeded", "Portainer logs collected", {"logs": logs})
            for service_id, _service, spec in matched:
                replicas = None
                if operation.operation == "stop":
                    replicas = 0
                elif operation.operation == "start":
                    replicas = int(spec.get("replicas", 1))
                await self._force_update_service(client, base, service_id, replicas)
        return ExecutionResult(
            "succeeded", f"Portainer {operation.operation} completed", {"services": len(matched)}
        )

    async def _force_update_service(
        self, client: httpx.AsyncClient, base: str, service_id: str, replicas: int | None
    ) -> None:
        """Re-post the service's own spec with ForceUpdate bumped (and Replicas set, if given).

        Docker's Swarm Services API has no partial-update/start/stop verb: every ``restart`` is
        implemented as a "force update" (redeploy every task, same as ``docker service update
        --force``) and every scale change is a full spec re-post with only ``Replicas`` changed.
        The spec/version below always come straight from Docker's own inspect response, never
        from client input, so nothing here can smuggle in arbitrary service configuration.
        """
        inspect_response = await client.get(f"{base}/{service_id}")
        inspect_response.raise_for_status()
        payload = inspect_response.json()
        version = payload["Version"]["Index"]
        spec = payload["Spec"]
        task_template = spec.setdefault("TaskTemplate", {})
        task_template["ForceUpdate"] = int(task_template.get("ForceUpdate", 0)) + 1
        if replicas is not None:
            mode = spec.get("Mode", {})
            if "Replicated" not in mode:
                raise ActionConfigurationError(
                    "Service is not in replicated mode; start/stop is unsupported"
                )
            mode["Replicated"]["Replicas"] = replicas
        update_response = await client.post(
            f"{base}/{service_id}/update", params={"version": str(version)}, json=spec
        )
        update_response.raise_for_status()


# --- executor -------------------------------------------------------------------------------


class PersistentWorkerAutomationExecutor(AutomationExecutorPort):
    """V1 executor which runs jobs within the long-lived Celery worker process."""

    def __init__(self, settings: Settings, portainer_client: PortainerClient | None = None) -> None:
        self._settings = settings
        self._portainer_client = portainer_client

    async def execute(self, job: AutomationJob) -> ExecutionResult:
        action = resolve_action(
            job.action_type,
            job.action_config,
            job.params,
            job.connector_config,
            self._ssh_commands(job),
        )
        if isinstance(action, ResolvedPortainerAction):
            return await self._execute_portainer(action, job)
        # settings.execution_timeout_seconds is an operator-configurable ceiling below the
        # allow-listed maximum — defaults to 900 (a no-op) but can be tightened per deployment.
        timeout_seconds = min(action.timeout_seconds, self._settings.execution_timeout_seconds)
        parse: Callable[[ProcessResult], ExecutionResult]
        with materialized_secrets(job.secrets) as credentials:
            if isinstance(action, ResolvedAnsibleAction):
                command = build_ansible_command(action, self._settings, credentials)
                parse = parse_ansible_result
            else:
                command = build_ssh_command(action, credentials)
                parse = parse_ssh_result
            result = await run_subprocess(
                command,
                cwd=self._settings.project_root,
                timeout_seconds=timeout_seconds,
                termination_grace_seconds=self._settings.termination_grace_seconds,
                known_secrets=collect_known_secrets(self._settings, job),
            )
        return parse(result)

    async def _execute_portainer(
        self, action: ResolvedPortainerAction, job: AutomationJob
    ) -> ExecutionResult:
        runtime = job.runtime or {}
        environment_id = runtime.get("environment_id")
        if not environment_id:
            raise ActionConfigurationError("Service declares no Portainer runtime")
        client = self._portainer_client or PortainerClient.from_job(job, self._settings)
        return await client.execute(action, str(environment_id), runtime, runtime.get("stack_name"))

    def _ssh_commands(self, job: AutomationJob) -> dict[str, SshCommand] | None:
        if job.action_type != "ssh":
            return None
        try:
            return load_ssh_commands(self._settings.ssh_commands_path)
        except SshCommandsError as exc:
            raise ActionConfigurationError(f"SSH command allow-list is invalid: {exc}") from exc


def safe_result_data(result: ExecutionResult) -> dict[str, Any]:
    """Sanitize executor data once more at the persistence boundary."""
    data = sanitize_data(result.data)
    return data if isinstance(data, dict) else {}
