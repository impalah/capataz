"""Validation and resolution of declarative automation actions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ALLOWED_ACTION_TYPES = frozenset({"ansible", "portainer"})
ALLOWED_PORTAINER_OPERATIONS = frozenset({"start", "stop", "restart", "logs"})
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


@dataclass(frozen=True)
class ResolvedPortainerAction:
    operation: Literal["start", "stop", "restart", "logs"]


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
    action_type: object, config: object, params: Mapping[str, Any] | None = None
) -> ResolvedAnsibleAction | ResolvedPortainerAction:
    """Resolve only V1 action types and their explicitly supported configuration shapes.

    ``params`` are the execution-time values supplied when the action was requested (persisted
    on the ``Execution`` row, re-read from PostgreSQL, never trusted from the queue payload).
    They are only meaningful for Ansible actions, where they may override ``extra_vars`` for
    keys within ``ALLOWED_EXTRA_VARS`` — validated through the exact same allow-list/slug checks
    as the static catalog-defined ``extra_vars``, never given a wider surface.
    """
    if action_type not in ALLOWED_ACTION_TYPES:
        raise ActionConfigurationError("action_type is not supported by the V1 runner")
    values = _mapping(config, "config")
    if action_type == "portainer":
        if set(values) != {"operation", "target"} or values.get("target") != "selected_containers":
            raise ActionConfigurationError("Portainer config must target selected_containers only")
        operation = values.get("operation")
        if operation not in ALLOWED_PORTAINER_OPERATIONS:
            raise ActionConfigurationError("Portainer operation is not allow-listed")
        return ResolvedPortainerAction(operation=operation)

    allowed_keys = {"playbook", "inventory", "limit", "extra_vars", "timeout_seconds"}
    if not set(values).issubset(allowed_keys):
        raise ActionConfigurationError("Ansible config contains unsupported fields")
    playbook = _safe_relative_path(values.get("playbook"), ALLOWED_PLAYBOOKS, "playbook")
    inventory = _safe_relative_path(values.get("inventory"), ALLOWED_INVENTORIES, "inventory")
    limit = _safe_slug(values.get("limit"), "limit")
    raw_extra_vars = _mapping(values.get("extra_vars", {}), "extra_vars")
    if params:
        raw_extra_vars = {**raw_extra_vars, **_mapping(params, "params")}
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
    return ResolvedAnsibleAction(playbook, inventory, limit, extra_vars, timeout)
