"""Validation and resolution of declarative automation actions.

The runner is the single source of truth for what is actually executable: the API only validates
shapes early, and anything here that is not an explicit allow-list member is rejected.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from capataz_runner.ssh_commands import SshCommand, SshCommandsError

ALLOWED_ACTION_TYPES = frozenset({"ansible", "portainer", "ssh"})
ALLOWED_PORTAINER_OPERATIONS = frozenset({"start", "stop", "restart", "logs"})
ALLOWED_PORTAINER_TARGETS = frozenset({"selected_containers", "selected_services"})
ALLOWED_PLAYBOOKS = frozenset(
    {
        "playbooks/restart_service.yml",
        "playbooks/backup_service.yml",
        "playbooks/check_connectivity.yml",
    }
)
ALLOWED_INVENTORIES = frozenset({"inventories/homelab.yml", "inventories/local.yml"})
ALLOWED_EXTRA_VARS = frozenset({"service", "backup_label"})
SAFE_SLUG = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$")
POSIX_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
HOSTNAME = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)
# Named so config.py's Settings validator (CR-085) can enforce a margin against it instead of
# repeating this number — the two only stayed in sync by convention before.
MAX_ACTION_TIMEOUT_SECONDS = 900


class ActionConfigurationError(ValueError):
    """Raised for any action that is not an explicit runner allow-list member."""


@dataclass(frozen=True)
class ResolvedAnsibleAction:
    playbook: str
    inventory: str
    limit: str
    extra_vars: dict[str, str]
    timeout_seconds: int
    user: str | None = None


@dataclass(frozen=True)
class ResolvedPortainerAction:
    operation: Literal["start", "stop", "restart", "logs"]
    target: Literal["selected_containers", "selected_services"] = "selected_containers"


@dataclass(frozen=True)
class ResolvedSshAction:
    command_id: str
    argv: tuple[str, ...]
    host: str
    port: int
    user: str
    timeout_seconds: int


ResolvedAction = ResolvedAnsibleAction | ResolvedPortainerAction | ResolvedSshAction


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActionConfigurationError(f"{field} must be an object")
    return value


def _safe_slug(value: object, field: str) -> str:
    if not isinstance(value, str) or not SAFE_SLUG.fullmatch(value):
        raise ActionConfigurationError(f"{field} contains unsupported characters")
    return value


def _safe_relative_path(value: object, allow_list: frozenset[str], field: str) -> str:
    if (
        not isinstance(value, str)
        or value not in allow_list
        or Path(value).is_absolute()
        or ".." in Path(value).parts
    ):
        raise ActionConfigurationError(f"{field} is not an allow-listed repository path")
    return value


def resolve_action(
    action_type: object,
    config: object,
    params: Mapping[str, Any] | None = None,
    connector_config: Mapping[str, Any] | None = None,
    ssh_commands: Mapping[str, SshCommand] | None = None,
) -> ResolvedAction:
    """Resolve only allow-listed action types and their explicitly supported shapes.

    ``params`` are the execution-time values supplied when the action was requested (persisted
    on the ``Execution`` row, re-read from PostgreSQL, never trusted from the queue payload).
    ``connector_config`` is the action's connector, also re-read from PostgreSQL: it supplies
    the target (Ansible inventory/user, SSH host/port/user), never the action itself.
    """
    if action_type not in ALLOWED_ACTION_TYPES:
        raise ActionConfigurationError("action_type is not supported by the runner")
    values = _mapping(config, "config")
    connector = _mapping(dict(connector_config or {}), "connector config")
    if action_type == "portainer":
        target = values.get("target")
        if set(values) != {"operation", "target"} or target not in ALLOWED_PORTAINER_TARGETS:
            raise ActionConfigurationError(
                "Portainer config must target selected_containers or selected_services"
            )
        operation = values.get("operation")
        if operation not in ALLOWED_PORTAINER_OPERATIONS:
            raise ActionConfigurationError("Portainer operation is not allow-listed")
        return ResolvedPortainerAction(operation=operation, target=target)
    if action_type == "ansible":
        return _resolve_ansible(values, params, connector)
    return _resolve_ssh(values, params, connector, ssh_commands)


def _resolve_ansible(
    values: dict[str, Any], params: Mapping[str, Any] | None, connector: dict[str, Any]
) -> ResolvedAnsibleAction:
    """``params`` may override ``extra_vars`` only for keys within ``ALLOWED_EXTRA_VARS`` —
    validated through the exact same allow-list/slug checks, never given a wider surface."""
    if not set(values).issubset({"playbook", "limit", "extra_vars", "timeout_seconds"}):
        raise ActionConfigurationError("Ansible config contains unsupported fields")
    playbook = _safe_relative_path(values.get("playbook"), ALLOWED_PLAYBOOKS, "playbook")
    inventory = _safe_relative_path(connector.get("inventory"), ALLOWED_INVENTORIES, "inventory")
    user = connector.get("user")
    if user is not None and (not isinstance(user, str) or not POSIX_USER.fullmatch(user)):
        raise ActionConfigurationError("Ansible connector user contains unsupported characters")
    limit = _safe_slug(values.get("limit"), "limit")
    raw_extra_vars = _mapping(values.get("extra_vars", {}), "extra_vars")
    if params:
        raw_extra_vars = {**raw_extra_vars, **_mapping(dict(params), "params")}
    if not set(raw_extra_vars).issubset(ALLOWED_EXTRA_VARS):
        raise ActionConfigurationError("Ansible extra_vars contains unsupported fields")
    extra_vars = {
        key: _safe_slug(item, f"extra_vars.{key}") for key, item in raw_extra_vars.items()
    }
    timeout = values.get("timeout_seconds", 300)
    if (
        not isinstance(timeout, int)
        or isinstance(timeout, bool)
        or not 1 <= timeout <= MAX_ACTION_TIMEOUT_SECONDS
    ):
        raise ActionConfigurationError(
            f"timeout_seconds must be an integer from 1 to {MAX_ACTION_TIMEOUT_SECONDS}"
        )
    return ResolvedAnsibleAction(playbook, inventory, limit, extra_vars, timeout, user)


def _resolve_ssh(
    values: dict[str, Any],
    params: Mapping[str, Any] | None,
    connector: dict[str, Any],
    commands: Mapping[str, SshCommand] | None,
) -> ResolvedSshAction:
    if commands is None:
        raise ActionConfigurationError("SSH command allow-list is not loaded")
    if not set(values).issubset({"command_id", "params"}):
        raise ActionConfigurationError("SSH config contains unsupported fields")
    command_id = values.get("command_id")
    command = commands.get(command_id) if isinstance(command_id, str) else None
    if command is None:
        raise ActionConfigurationError("SSH command_id is not allow-listed")
    supplied = {
        **_mapping(values.get("params", {}), "params"),
        **_mapping(dict(params or {}), "params"),
    }
    try:
        argv = command.render(supplied)
    except SshCommandsError as exc:
        raise ActionConfigurationError(str(exc)) from exc
    host = connector.get("host")
    if not isinstance(host, str) or not HOSTNAME.fullmatch(host):
        raise ActionConfigurationError("SSH connector host is not a valid hostname")
    port = connector.get("port", 22)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ActionConfigurationError("SSH connector port is invalid")
    user = connector.get("user")
    if not isinstance(user, str) or not POSIX_USER.fullmatch(user):
        raise ActionConfigurationError("SSH connector user contains unsupported characters")
    return ResolvedSshAction(command.command_id, argv, host, port, user, command.timeout_seconds)
