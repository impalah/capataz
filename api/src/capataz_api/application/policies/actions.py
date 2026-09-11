from typing import Any

from capataz_api.application.policies.references import describe_error, portainer_target_error
from capataz_api.domain.entities import ActionDefinition, Connector, Service
from capataz_api.domain.exceptions import ValidationError
from capataz_api.domain.specs import connector_capabilities
from capataz_api.domain.specs import validate_action_config as validate_spec_action_config
from capataz_api.domain.value_objects import ConnectorCapability, ConnectorType

_FORBIDDEN_PARAM_KEYS = {"command", "container_id", "url", "playbook_path"}


def resolve_action(
    service: Service, action: ActionDefinition, params: dict[str, Any], connector: Connector
) -> dict[str, Any]:
    _validate_action_enabled(service, action)
    _validate_params(action, params)
    config = validate_action_config(service, action, connector)
    return {"config": config, "params": params}


def validate_action_config(
    service: Service, action: ActionDefinition, connector: Connector
) -> dict[str, Any]:
    """Reject a `config` whose shape doesn't match the action's connector; returns it normalized.

    Called at save time (ActionApplicationService, CR-088) and again right before enqueueing an
    execution. The runner still re-validates against its own allow-list (playbooks, extra_vars,
    SSH command ids): it stays the single source of truth for what is actually executable.
    """
    if connector.id != action.connector_id:
        raise ValidationError("Action connector does not match the action definition")
    if ConnectorCapability.ACTIONS not in connector_capabilities(connector.spec):
        raise ValidationError(f"Connector {connector.id!r} does not support actions")
    if action.action_type.value != connector.type.value:
        raise ValidationError("Action type does not match its connector type")
    try:
        config = validate_spec_action_config(connector.type, dict(action.config))
    except ValueError as exc:
        raise ValidationError(f"Invalid action config: {describe_error(exc)}") from None
    if connector.type is ConnectorType.PORTAINER:
        message = portainer_target_error(service.spec, connector.id, config)
        if message:
            raise ValidationError(message)
    return config


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
