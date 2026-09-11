"""Loader for runner/ssh_commands.yml, the SSH command allow-list versioned with the repo.

Parsed strictly: anything unexpected in the file itself (unknown keys, a placeholder with no
declared parameter, a default that doesn't satisfy its own pattern...) is an error, not ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

COMMAND_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
PARAM_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,31}$")
PLACEHOLDER = re.compile(r"^\{([a-z_][a-z0-9_]{0,31})\}$")
PROGRAM = re.compile(r"^[A-Za-z0-9_./-]+$")
DEFAULT_SSH_TIMEOUT_SECONDS = 60
MAX_SSH_TIMEOUT_SECONDS = 300


class SshCommandsError(ValueError):
    """The allow-list file is invalid, or an action's values don't satisfy it."""


@dataclass(frozen=True)
class SshParam:
    pattern: re.Pattern[str] | None = None
    enum: tuple[str, ...] | None = None
    default: str | None = None

    def check(self, name: str, value: object) -> str:
        if not isinstance(value, str):
            raise SshCommandsError(f"parameter {name} must be a string")
        if self.enum is not None and value not in self.enum:
            raise SshCommandsError(f"parameter {name} is not one of the allowed values")
        if self.pattern is not None and not self.pattern.fullmatch(value):
            raise SshCommandsError(f"parameter {name} contains unsupported characters")
        return value


@dataclass(frozen=True)
class SshCommand:
    command_id: str
    argv: tuple[str, ...]
    params: dict[str, SshParam] = field(default_factory=dict)
    timeout_seconds: int = DEFAULT_SSH_TIMEOUT_SECONDS

    def render(self, supplied: dict[str, Any]) -> tuple[str, ...]:
        unknown = set(supplied) - set(self.params)
        if unknown:
            raise SshCommandsError(f"unknown parameters for {self.command_id}: {sorted(unknown)}")
        values: dict[str, str] = {}
        for name, spec in self.params.items():
            value = supplied.get(name, spec.default)
            if value is None:
                raise SshCommandsError(f"parameter {name} is required")
            values[name] = spec.check(name, value)
        rendered: list[str] = []
        for element in self.argv:
            match = PLACEHOLDER.fullmatch(element)
            rendered.append(values[match.group(1)] if match else element)
        return tuple(rendered)


def _param(command_id: str, name: str, raw: object) -> SshParam:
    if not PARAM_NAME.fullmatch(name):
        raise SshCommandsError(f"{command_id}: invalid parameter name {name!r}")
    if not isinstance(raw, dict) or not set(raw) <= {"pattern", "enum", "default"}:
        raise SshCommandsError(f"{command_id}.{name}: expected pattern/enum/default keys")
    if ("pattern" in raw) == ("enum" in raw):
        raise SshCommandsError(f"{command_id}.{name}: exactly one of pattern or enum is required")
    try:
        pattern = re.compile(str(raw["pattern"])) if "pattern" in raw else None
    except re.error as exc:
        raise SshCommandsError(f"{command_id}.{name}: invalid pattern") from exc
    enum = raw.get("enum")
    if enum is not None and (
        not isinstance(enum, list) or not enum or not all(isinstance(v, str) for v in enum)
    ):
        raise SshCommandsError(f"{command_id}.{name}: enum must be a non-empty list of strings")
    spec = SshParam(pattern, tuple(enum) if enum is not None else None, raw.get("default"))
    if spec.default is not None:
        spec.check(name, spec.default)
    return spec


def _command(command_id: str, raw: object) -> SshCommand:
    if not COMMAND_ID.fullmatch(command_id):
        raise SshCommandsError(f"invalid command id {command_id!r}")
    if not isinstance(raw, dict) or not set(raw) <= {
        "description",
        "argv",
        "params",
        "timeout_seconds",
    }:
        raise SshCommandsError(f"{command_id}: unexpected keys")
    argv = raw.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise SshCommandsError(f"{command_id}: argv must be a non-empty list of strings")
    if not PROGRAM.fullmatch(argv[0]):
        raise SshCommandsError(f"{command_id}: the program must be a literal executable name")
    raw_params = raw.get("params") or {}
    if not isinstance(raw_params, dict):
        raise SshCommandsError(f"{command_id}: params must be a mapping")
    params = {str(name): _param(command_id, str(name), spec) for name, spec in raw_params.items()}
    placeholders = {m.group(1) for a in argv if (m := PLACEHOLDER.fullmatch(a))}
    if placeholders != set(params):
        raise SshCommandsError(f"{command_id}: argv placeholders and declared params differ")
    timeout = raw.get("timeout_seconds", DEFAULT_SSH_TIMEOUT_SECONDS)
    if (
        not isinstance(timeout, int)
        or isinstance(timeout, bool)
        or not 1 <= timeout <= MAX_SSH_TIMEOUT_SECONDS
    ):
        raise SshCommandsError(
            f"{command_id}: timeout_seconds must be an integer from 1 to {MAX_SSH_TIMEOUT_SECONDS}"
        )
    return SshCommand(command_id, tuple(argv), params, timeout)


def load_ssh_commands(path: Path) -> dict[str, SshCommand]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SshCommandsError(f"cannot read {path.name}") from exc
    except yaml.YAMLError as exc:
        raise SshCommandsError(f"{path.name} is not valid YAML") from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != {"commands"}
        or not isinstance(raw["commands"], dict)
    ):
        raise SshCommandsError(f"{path.name} must contain exactly a `commands` mapping")
    return {
        str(command_id): _command(str(command_id), spec)
        for command_id, spec in raw["commands"].items()
    }
