from __future__ import annotations

import pytest

from capataz_runner.actions import (
    ActionConfigurationError,
    ResolvedAnsibleAction,
    ResolvedPortainerAction,
    resolve_action,
)


@pytest.mark.parametrize("operation", ["start", "stop", "restart", "logs"])
def test_resolve_allow_listed_portainer_action(operation: str) -> None:
    action = resolve_action("portainer", {"operation": operation, "target": "selected_containers"})
    assert isinstance(action, ResolvedPortainerAction)
    assert action.operation == operation


def test_resolve_allow_listed_ansible_action() -> None:
    action = resolve_action(
        "ansible",
        {
            "playbook": "playbooks/restart_service.yml",
            "inventory": "inventories/homelab.yml",
            "limit": "node-gpu-01",
            "extra_vars": {"service": "open-webui"},
            "timeout_seconds": 60,
        },
    )
    assert isinstance(action, ResolvedAnsibleAction)
    assert action.limit == "node-gpu-01"


@pytest.mark.parametrize(
    ("action_type", "config"),
    [
        ("ssh", {"command": "rm -rf /"}),
        (
            "ansible",
            {
                "playbook": "/tmp/evil.yml",
                "inventory": "inventories/homelab.yml",
                "limit": "node-ai-01",
            },
        ),
        (
            "ansible",
            {
                "playbook": "playbooks/restart_service.yml",
                "inventory": "inventories/homelab.yml",
                "limit": "node-ai-01;whoami",
            },
        ),
        ("portainer", {"operation": "restart", "target": "client_supplied_container"}),
        ("portainer", {"operation": "exec", "target": "selected_containers"}),
    ],
)
def test_rejects_any_non_allow_listed_action(action_type: str, config: object) -> None:
    with pytest.raises(ActionConfigurationError):
        resolve_action(action_type, config)


def test_execution_time_params_are_merged_into_extra_vars() -> None:
    """CR-050: Execution.params overrides/extends extra_vars, still bound by ALLOWED_EXTRA_VARS."""
    action = resolve_action(
        "ansible",
        {
            "playbook": "playbooks/backup_service.yml",
            "inventory": "inventories/homelab.yml",
            "limit": "node-gpu-01",
            "extra_vars": {"service": "open-webui"},
        },
        params={"backup_label": "pre-upgrade"},
    )
    assert isinstance(action, ResolvedAnsibleAction)
    assert action.extra_vars == {"service": "open-webui", "backup_label": "pre-upgrade"}


def test_execution_time_params_override_static_extra_vars_for_the_same_key() -> None:
    action = resolve_action(
        "ansible",
        {
            "playbook": "playbooks/backup_service.yml",
            "inventory": "inventories/homelab.yml",
            "limit": "node-gpu-01",
            "extra_vars": {"service": "open-webui"},
        },
        params={"service": "overridden-at-execution-time"},
    )
    assert isinstance(action, ResolvedAnsibleAction)
    assert action.extra_vars == {"service": "overridden-at-execution-time"}


def test_execution_time_params_still_go_through_the_allow_list_and_safe_slug() -> None:
    with pytest.raises(ActionConfigurationError):
        resolve_action(
            "ansible",
            {
                "playbook": "playbooks/backup_service.yml",
                "inventory": "inventories/homelab.yml",
                "limit": "node-gpu-01",
            },
            params={"not_allow_listed": "x"},
        )
    with pytest.raises(ActionConfigurationError):
        resolve_action(
            "ansible",
            {
                "playbook": "playbooks/backup_service.yml",
                "inventory": "inventories/homelab.yml",
                "limit": "node-gpu-01",
            },
            params={"backup_label": "{{ 7*7 }}"},
        )


@pytest.mark.parametrize("dangerous", ["{{ 7*7 }}", "`whoami`", "$(whoami)", "a;b", "a b"])
def test_safe_slug_rejects_template_and_shell_injection_syntax(dangerous: str) -> None:
    """Fixes the invariant SAFE_SLUG relies on implicitly (see executor.py build_ansible_command):
    if this regex is ever relaxed, extra_vars/limit become a Jinja2/SSTI or shell-argument
    injection vector instead of an inert string."""
    with pytest.raises(ActionConfigurationError):
        resolve_action(
            "ansible",
            {
                "playbook": "playbooks/restart_service.yml",
                "inventory": "inventories/homelab.yml",
                "limit": dangerous,
            },
        )
