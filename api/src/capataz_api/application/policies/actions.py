from typing import Any

from capataz_api.domain.entities import ActionDefinition, Service
from capataz_api.domain.exceptions import ValidationError
from capataz_api.domain.value_objects import ActionType

_FORBIDDEN_PARAM_KEYS = {"command", "container_id", "url", "playbook_path"}
_ALLOWED_PORTAINER_OPERATIONS = {"start", "stop", "restart", "logs"}


def resolve_action(
    service: Service, action: ActionDefinition, params: dict[str, Any]
) -> dict[str, Any]:
    _validate_action_enabled(service, action)
    _validate_params(action, params)
    config = dict(action.config)
    _validate_config_for_action_type(service, action, config)
    return {"config": config, "params": params}


def validate_action_config(service: Service, action: ActionDefinition) -> None:
    """Reject a `config` whose shape doesn't match the declared `action_type`.

    Called from ActionApplicationService.create_action/patch_action so a broken config is a 422
    at save time (CR-088), instead of the pre-existing behaviour of persisting it successfully and
    only failing the first time someone tries to execute it, via the same check `resolve_action`
    runs. Deliberately skips `_validate_action_enabled`/`_validate_params`: those two are about a
    specific execution attempt, not about whether the definition itself is well-formed.
    """
    _validate_config_for_action_type(service, action, dict(action.config))


def _validate_action_enabled(service: Service, action: ActionDefinition) -> None:
    if action.service_id != service.id:
        raise ValidationError("Action does not belong to this service")
    if not action.enabled:
        raise ValidationError("Action is not enabled for this service")


def _validate_params(action: ActionDefinition, params: dict[str, Any]) -> None:
    if _FORBIDDEN_PARAM_KEYS & params.keys():
        raise ValidationError("Unallowlisted execution parameters")
    schema = action.allowed_parameters_schema
    properties = schema.get("properties", {})
    if any(key not in properties for key in params):
        raise ValidationError("Parameter is not allow-listed")
    for key, definition in properties.items():
        if key in params and "enum" in definition and params[key] not in definition["enum"]:
            raise ValidationError(f"Invalid value for parameter {key}")


def _validate_config_for_action_type(
    service: Service, action: ActionDefinition, config: dict[str, Any]
) -> None:
    if action.action_type == ActionType.PORTAINER:
        _validate_portainer_config(service, config)
    if action.action_type == ActionType.ANSIBLE:
        _validate_ansible_config(config)
    if action.action_type in {ActionType.HTTP, ActionType.SSH, ActionType.RSYNC}:
        raise ValidationError("Action type is modelled but not executable in V1")


def _validate_portainer_config(service: Service, config: dict[str, Any]) -> None:
    if set(config) != {"operation", "target"}:
        raise ValidationError("Portainer config must contain only operation and target")
    if config.get("operation") not in _ALLOWED_PORTAINER_OPERATIONS:
        raise ValidationError("Unsupported Portainer operation")
    if config.get("target") != "selected_containers" or not service.container_selectors:
        raise ValidationError("Portainer target must be service-declared containers")


def _validate_ansible_config(config: dict[str, Any]) -> None:
    playbook = str(config.get("playbook", ""))
    inventory = str(config.get("inventory", ""))
    if (
        not (playbook.startswith("playbooks/") and inventory.startswith("inventories/"))
        or ".." in playbook + inventory
    ):
        raise ValidationError("Ansible paths must be allow-listed relative paths")
    # Deliberately not re-validating the runner's closed ALLOWED_PLAYBOOKS/ALLOWED_INVENTORIES/
    # ALLOWED_EXTRA_VARS/timeout_seconds range here (see docs/05-yaml-catalog.en.md and CR-010 in
    # docs/code-review-2026-08.md): the runner stays the single source of truth for that
    # allow-list, so a definition passing this prefix-only check can still be rejected by the
    # runner at execution time, surfacing as a `failed` Execution rather than an early 422.
