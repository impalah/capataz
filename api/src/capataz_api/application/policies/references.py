"""Cross-object reference checks shared by catalog import and the CRUD use cases.

Everything here is pure: callers pass in the connectors/resources that exist (from the DB, the
catalog being imported, or both) and get back FieldErrors whose paths are relative to `prefix`,
so the catalog importer can map them onto YAML line numbers.
"""

from collections.abc import Mapping

from pydantic import ValidationError as PydanticValidationError

from capataz_api.application.policies.outbound_urls import (
    narrow_suffixes,
    suffix_within,
    validate_outbound_host,
    validate_outbound_url,
)
from capataz_api.domain.exceptions import FieldError, ValidationError
from capataz_api.domain.specs import (
    ActionSpec,
    ConnectorSpec,
    HttpConnector,
    ServiceSpec,
    SshConnector,
    connector_capabilities,
    connector_resource_refs,
    connector_type,
    validate_action_config,
)
from capataz_api.domain.value_objects import ConnectorCapability, ConnectorType, ResourceType


def describe_error(exc: ValueError) -> str:
    """A one-line message for a (possibly pydantic) validation error."""
    if isinstance(exc, PydanticValidationError):
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        return f"{location}: {first['msg']}" if location else str(first["msg"])
    return str(exc)


def portainer_target_error(
    service: ServiceSpec, connector_id: str, config: Mapping[str, object]
) -> str | None:
    runtime = service.runtime
    if runtime is None:
        return "Portainer actions require the service to declare a runtime"
    if runtime.connector != connector_id:
        return "Portainer actions must use the service's runtime connector"
    expected = "selected_services" if runtime.selector_kind == "services" else "selected_containers"
    if config.get("target") != expected:
        return "Portainer target must match the service's declared selector kind"
    return None


def service_reference_errors(
    spec: ServiceSpec,
    connectors: Mapping[str, ConnectorSpec],
    allowed_suffixes: tuple[str, ...],
    prefix: str = "",
) -> list[FieldError]:
    errors: list[FieldError] = []
    for usage in spec.connector_usages():
        connector = connectors.get(usage.connector_id)
        path = f"{prefix}{usage.path}"
        if connector is None:
            errors.append(FieldError(path, f"connector {usage.connector_id!r} does not exist"))
        elif usage.capability not in connector_capabilities(connector):
            errors.append(
                FieldError(
                    path,
                    f"connector {usage.connector_id!r} ({connector.type}) cannot be used for "
                    f"{usage.capability.value}",
                )
            )
    health = spec.observability.health
    if health is not None:
        connector = connectors.get(health.connector)
        if isinstance(connector, HttpConnector):
            suffixes = narrow_suffixes(
                tuple(connector.config.allowed_host_suffixes), allowed_suffixes
            )
            try:
                validate_outbound_url(str(health.url), suffixes)
            except ValidationError as exc:
                errors.append(FieldError(f"{prefix}observability.health.url", str(exc)))
    return errors


def connector_reference_errors(
    connector: ConnectorSpec,
    resource_types: Mapping[str, ResourceType],
    allowed_suffixes: tuple[str, ...],
    prefix: str = "",
) -> list[FieldError]:
    errors: list[FieldError] = []
    for field_name, (resource_id, expected) in connector_resource_refs(connector).items():
        actual = resource_types.get(resource_id)
        path = f"{prefix}config.{field_name}"
        if actual is None:
            errors.append(FieldError(path, f"resource {resource_id!r} does not exist"))
        elif actual != expected:
            errors.append(
                FieldError(
                    path,
                    f"resource {resource_id!r} is of type {actual.value}, "
                    f"expected {expected.value}",
                )
            )
    url = getattr(connector.config, "url", None)
    if url is not None:
        try:
            validate_outbound_url(str(url), allowed_suffixes, "Connector")
        except ValidationError as exc:
            errors.append(FieldError(f"{prefix}config.url", str(exc)))
    if isinstance(connector, HttpConnector):
        for index, suffix in enumerate(connector.config.allowed_host_suffixes):
            if not suffix_within(suffix, allowed_suffixes):
                errors.append(
                    FieldError(
                        f"{prefix}config.allowed_host_suffixes.{index}",
                        f"{suffix!r} is outside CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES",
                    )
                )
    if isinstance(connector, SshConnector):
        try:
            validate_outbound_host(connector.config.host, allowed_suffixes, "SSH")
        except ValidationError as exc:
            errors.append(FieldError(f"{prefix}config.host", str(exc)))
    return errors


def action_reference_errors(
    action: ActionSpec,
    service: ServiceSpec,
    connectors: Mapping[str, ConnectorSpec],
    prefix: str = "",
) -> list[FieldError]:
    connector = connectors.get(action.connector)
    if connector is None:
        return [FieldError(f"{prefix}connector", f"connector {action.connector!r} does not exist")]
    if ConnectorCapability.ACTIONS not in connector_capabilities(connector):
        return [
            FieldError(
                f"{prefix}connector",
                f"connector {action.connector!r} ({connector.type}) does not support actions",
            )
        ]
    try:
        config = validate_action_config(connector_type(connector), action.config)
    except ValueError as exc:
        return [FieldError(f"{prefix}config", describe_error(exc))]
    if connector_type(connector) is ConnectorType.PORTAINER:
        message = portainer_target_error(service, action.connector, config)
        if message:
            return [FieldError(f"{prefix}config.target", message)]
    return []
