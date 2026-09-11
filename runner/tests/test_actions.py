from __future__ import annotations

import re
from typing import Any

import pytest

from capataz_runner.actions import (
    ActionConfigurationError,
    ResolvedAnsibleAction,
    ResolvedPortainerAction,
    ResolvedSshAction,
    resolve_action,
)
from capataz_runner.ssh_commands import SshCommand, SshParam

HOMELAB: dict[str, Any] = {
    "inventory": "inventories/homelab.yml",
    "private_key": "k",
    "known_hosts": "kh",
}
SSH_TARGET: dict[str, Any] = {
    "host": "mole.home.arpa",
    "port": 2222,
    "user": "capataz",
    "private_key": "k",
    "known_hosts": "kh",
}
COMMANDS = {
    "disk_usage": SshCommand(
        "disk_usage",
        ("df", "-h", "{path}"),
        {"path": SshParam(pattern=re.compile(r"^/[A-Za-z0-9_./-]{0,200}$"), default="/")},
        60,
    ),
    "unit_status": SshCommand(
        "unit_status", ("systemctl", "status", "{unit}"), {"unit": SshParam(enum=("nginx",))}, 30
    ),
}


def ansible(**config: Any) -> dict[str, Any]:
    return {"playbook": "playbooks/restart_service.yml", "limit": "node-ai-01", **config}


@pytest.mark.parametrize("operation", ["start", "stop", "restart", "logs"])
def test_resolve_allow_listed_portainer_action(operation: str) -> None:
    action = resolve_action("portainer", {"operation": operation, "target": "selected_containers"})
    assert isinstance(action, ResolvedPortainerAction)
    assert action.operation == operation


def test_ansible_inventory_and_user_come_from_the_connector() -> None:
    action = resolve_action(
        "ansible",
        ansible(limit="node-gpu-01", extra_vars={"service": "open-webui"}, timeout_seconds=60),
        connector_config={**HOMELAB, "user": "deploy"},
    )
    assert isinstance(action, ResolvedAnsibleAction)
    assert (action.inventory, action.user, action.limit) == (
        "inventories/homelab.yml",
        "deploy",
        "node-gpu-01",
    )


def test_ansible_rejects_an_inventory_in_the_action_or_outside_the_allow_list() -> None:
    with pytest.raises(ActionConfigurationError, match="unsupported fields"):
        resolve_action(
            "ansible", ansible(inventory="inventories/homelab.yml"), connector_config=HOMELAB
        )
    for inventory in ("/etc/ansible/hosts", "inventories/../../x.yml", "inventories/other.yml"):
        with pytest.raises(ActionConfigurationError, match="inventory"):
            resolve_action(
                "ansible", ansible(), connector_config={**HOMELAB, "inventory": inventory}
            )
    with pytest.raises(ActionConfigurationError, match="user"):
        resolve_action("ansible", ansible(), connector_config={**HOMELAB, "user": "root;id"})


@pytest.mark.parametrize(
    ("action_type", "config"),
    [
        ("ssh", {"command": "rm -rf /"}),
        ("ansible", ansible(playbook="/tmp/evil.yml")),
        ("ansible", ansible(limit="node-ai-01;whoami")),
        ("portainer", {"operation": "restart", "target": "client_supplied_container"}),
        ("portainer", {"operation": "exec", "target": "selected_containers"}),
        ("http", {"url": "https://example.com"}),
    ],
)
def test_rejects_any_non_allow_listed_action(action_type: str, config: object) -> None:
    connector = SSH_TARGET if action_type == "ssh" else HOMELAB
    with pytest.raises(ActionConfigurationError):
        resolve_action(action_type, config, connector_config=connector, ssh_commands=COMMANDS)


def test_execution_time_params_are_merged_into_extra_vars() -> None:
    """CR-050: Execution.params overrides/extends extra_vars, still bound by ALLOWED_EXTRA_VARS."""
    action = resolve_action(
        "ansible",
        ansible(playbook="playbooks/backup_service.yml", extra_vars={"service": "open-webui"}),
        params={"backup_label": "pre-upgrade", "service": "overridden"},
        connector_config=HOMELAB,
    )
    assert isinstance(action, ResolvedAnsibleAction)
    assert action.extra_vars == {"service": "overridden", "backup_label": "pre-upgrade"}


def test_execution_time_params_still_go_through_the_allow_list_and_safe_slug() -> None:
    for params in ({"not_allow_listed": "x"}, {"backup_label": "{{ 7*7 }}"}):
        with pytest.raises(ActionConfigurationError):
            resolve_action("ansible", ansible(), params=params, connector_config=HOMELAB)


@pytest.mark.parametrize("dangerous", ["{{ 7*7 }}", "`whoami`", "$(whoami)", "a;b", "a b"])
def test_safe_slug_rejects_template_and_shell_injection_syntax(dangerous: str) -> None:
    """If this regex is ever relaxed, extra_vars/limit become a Jinja2/SSTI or shell-argument
    injection vector instead of an inert string."""
    with pytest.raises(ActionConfigurationError):
        resolve_action("ansible", ansible(limit=dangerous), connector_config=HOMELAB)


# --- ssh ------------------------------------------------------------------------------------


def test_ssh_resolves_an_allow_listed_command_with_defaults_and_the_connector_target() -> None:
    action = resolve_action(
        "ssh", {"command_id": "disk_usage"}, connector_config=SSH_TARGET, ssh_commands=COMMANDS
    )
    assert action == ResolvedSshAction(
        "disk_usage", ("df", "-h", "/"), "mole.home.arpa", 2222, "capataz", 60
    )


def test_ssh_params_come_from_the_action_and_execution_time_overrides() -> None:
    action = resolve_action(
        "ssh",
        {"command_id": "disk_usage", "params": {"path": "/srv"}},
        params={"path": "/var/lib/docker"},
        connector_config=SSH_TARGET,
        ssh_commands=COMMANDS,
    )
    assert isinstance(action, ResolvedSshAction)
    assert action.argv == ("df", "-h", "/var/lib/docker")


@pytest.mark.parametrize(
    ("config", "match"),
    [
        ({"command_id": "rm"}, "not allow-listed"),
        ({"command_id": "disk_usage", "params": {"other": "x"}}, "unknown parameters"),
        ({"command_id": "disk_usage", "params": {"path": "/srv; rm -rf /"}}, "unsupported"),
        ({"command_id": "disk_usage", "params": {"path": "$(id)"}}, "unsupported"),
        ({"command_id": "unit_status", "params": {"unit": "sshd"}}, "allowed values"),
        ({"command_id": "unit_status"}, "required"),
        ({"command_id": "disk_usage", "timeout": 5}, "unsupported fields"),
    ],
)
def test_ssh_rejects_anything_outside_the_allow_list(config: dict[str, Any], match: str) -> None:
    with pytest.raises(ActionConfigurationError, match=match):
        resolve_action("ssh", config, connector_config=SSH_TARGET, ssh_commands=COMMANDS)


def test_ssh_requires_the_allow_list_to_be_loaded() -> None:
    with pytest.raises(ActionConfigurationError, match="not loaded"):
        resolve_action("ssh", {"command_id": "disk_usage"}, connector_config=SSH_TARGET)


@pytest.mark.parametrize(
    "target",
    [
        {"host": "-oProxyCommand=touch /tmp/x"},
        {"host": "mole.home.arpa extra"},
        {"user": "root;id"},
        {"port": 0},
        {"port": True},
    ],
)
def test_ssh_rejects_injection_shaped_targets(target: dict[str, Any]) -> None:
    with pytest.raises(ActionConfigurationError):
        resolve_action(
            "ssh",
            {"command_id": "disk_usage"},
            connector_config={**SSH_TARGET, **target},
            ssh_commands=COMMANDS,
        )
