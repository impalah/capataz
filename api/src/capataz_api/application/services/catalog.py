"""Catalog v2 import/export (docs/05-yaml-catalog.en.md).

Import is all-or-nothing: the whole document — structure, references to connectors/resources
(in the document or already in the database) and every resource source — is validated before
the first write, so an invalid catalog never leaves a half-applied state behind.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import ValidationError as PydanticValidationError

from capataz_api.application.dto.catalog import Catalog, ServiceDefinition
from capataz_api.application.policies import (
    action_reference_errors,
    connector_reference_errors,
    service_reference_errors,
)
from capataz_api.application.ports import ResourceCipher, ResourceSourceLoader, ServiceRepository
from capataz_api.domain.entities import ActionDefinition, Connector, Resource, Service
from capataz_api.domain.exceptions import FieldError
from capataz_api.domain.exceptions import ValidationError as DomainValidationError
from capataz_api.domain.specs import (
    ActionSpec,
    ConnectorSpec,
    EnvSource,
    FileSource,
    InlineSource,
    ResourceSource,
    ResourceSpec,
    connector_type,
    validate_action_config,
)
from capataz_api.domain.value_objects import ActionType, ResourceType

CONVERTER_HINT = "convert it with scripts/convert_catalog_v1_to_v2.py"


@dataclass(frozen=True)
class CatalogContext:
    cipher: ResourceCipher
    loader: ResourceSourceLoader
    inline_permitted: bool
    allowed_suffixes: tuple[str, ...]


@dataclass(frozen=True)
class CatalogImportOutcome:
    """Always-200 result of a catalog import/dry-run — see docs/05-yaml-catalog.en.md.

    Invalid input is expected, everyday operator feedback (a typo'd field, a missing key), not an
    HTTP-level failure: the caller inspects `valid`/`errors` rather than catching an exception.
    `created`/`updated` count services; `counts` breaks every kind down.
    """

    dry_run: bool
    valid: bool
    created: int = 0
    updated: int = 0
    errors: tuple[FieldError, ...] = ()
    warnings: tuple[FieldError, ...] = ()
    counts: dict[str, dict[str, int]] = field(default_factory=dict)


def _line_for_loc(node: yaml.Node | None, loc: tuple[int | str, ...]) -> int | None:
    """Best-effort: walk a composed YAML node tree following an error `loc` path.

    Falls back to the deepest node still found along the path (e.g. the parent mapping) when the
    exact key is itself missing — the common case for "Field required" errors, where there is by
    definition no node for the missing field, but the enclosing block is still useful.
    """
    if node is None:
        return None
    current = node
    for key in loc:
        if isinstance(current, yaml.MappingNode):
            match = next((v for k, v in current.value if str(k.value) == str(key)), None)
            if match is None:
                break
            current = match
        elif isinstance(current, yaml.SequenceNode):
            try:
                index = int(key)
            except ValueError:
                break
            if index >= len(current.value):
                break
            current = current.value[index]
        else:
            break
    return current.start_mark.line + 1


def _with_lines(node: yaml.Node | None, errors: list[FieldError]) -> tuple[FieldError, ...]:
    return tuple(
        FieldError(
            error.path,
            error.message,
            error.line or _line_for_loc(node, tuple(error.path.split("."))),
        )
        for error in errors
    )


def _parse(raw: str) -> tuple[Catalog, yaml.Node | None]:
    try:
        node = yaml.compose(raw)
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise DomainValidationError(
            "Catalog YAML is not valid YAML", (FieldError(path="$", message=str(exc)),)
        ) from exc
    if isinstance(data, dict) and data.get("version") == 1:
        message = f"catalog version 1 is no longer supported; {CONVERTER_HINT}"
        raise DomainValidationError(
            message, (FieldError("version", message, _line_for_loc(node, ("version",))),)
        )
    try:
        return Catalog.model_validate(data), node
    except PydanticValidationError as exc:
        errors = tuple(
            FieldError(
                path=".".join(str(part) for part in error["loc"]) or "$",
                message=error["msg"],
                line=_line_for_loc(node, error["loc"]),
            )
            for error in exc.errors()
        )
        raise DomainValidationError(f"{len(errors)} validation error(s)", errors) from exc


def parse_catalog_yaml(raw: str) -> Catalog:
    """Parse and structurally validate catalog YAML; raises DomainValidationError."""
    return _parse(raw)[0]


def _provenance(source: ResourceSource) -> dict[str, Any]:
    """Non-secret record of where a resource came from; never the content itself."""
    if isinstance(source, FileSource):
        return {"file": source.file}
    if isinstance(source, EnvSource):
        return {"env": source.env, "encoding": source.encoding}
    return {"inline": True}


@dataclass
class _Prepared:
    errors: list[FieldError]
    warnings: list[FieldError]
    contents: dict[str, bytes]
    db_resources: dict[str, Resource]
    db_connectors: dict[str, Connector]
    connector_specs: dict[str, ConnectorSpec]


def _missing_resource_errors(
    resource: ResourceSpec, existing: Resource | None, path: str
) -> list[FieldError]:
    """A resource declared with no `source` must already exist in the database, same type."""
    if existing is None:
        return [
            FieldError(
                path, f"resource {resource.id!r} has no source and has not been uploaded yet"
            )
        ]
    if existing.type != resource.type:
        return [
            FieldError(
                f"{path}.type", f"resource {resource.id!r} already exists as {existing.type.value}"
            )
        ]
    return []


def _load_resource_content(
    resource: ResourceSpec, context: CatalogContext, path: str
) -> tuple[bytes | None, list[FieldError], list[FieldError]]:
    """Load one resource's declared `source`; returns (content, errors, warnings).

    A permitted inline source is warned about up front, regardless of whether the load that
    follows succeeds — the warning describes the *source*, not the outcome of loading it.
    """
    warnings: list[FieldError] = []
    if isinstance(resource.source, InlineSource):
        if not context.inline_permitted:
            error = FieldError(
                f"{path}.source",
                "inline resource content is refused in production; set "
                "CAPATAZ_ALLOW_INLINE_RESOURCES=true to allow it",
            )
            return None, [error], []
        warnings.append(
            FieldError(
                f"{path}.source",
                "inline resource content is meant for development/testing only: it is stored "
                "encrypted, but it also sits in clear text in this YAML",
            )
        )
    try:
        content = context.loader.load(resource.source)
    except DomainValidationError as exc:
        return None, [FieldError(f"{path}.source", str(exc))], warnings
    return content, [], warnings


def _prepare_resource(
    resource: ResourceSpec, existing: Resource | None, context: CatalogContext, index: int
) -> tuple[bytes | None, list[FieldError], list[FieldError]]:
    """One catalog resource's (content, errors, warnings); content is None if nothing to store."""
    path = f"resources.{index}"
    if resource.source is None:
        return None, _missing_resource_errors(resource, existing, path), []
    return _load_resource_content(resource, context, path)


def _resource_types(
    db_resources: Mapping[str, Resource], resources: list[ResourceSpec]
) -> dict[str, ResourceType]:
    types = {rid: resource.type for rid, resource in db_resources.items()}
    types |= {resource.id: resource.type for resource in resources}
    return types


def _connector_specs(
    db_connectors: Mapping[str, Connector], connectors: list[ConnectorSpec]
) -> dict[str, ConnectorSpec]:
    specs: dict[str, ConnectorSpec] = {
        cid: connector.spec for cid, connector in db_connectors.items()
    }
    specs |= {connector.id: connector for connector in connectors}
    return specs


def _all_connector_errors(
    connectors: list[ConnectorSpec],
    resource_types: Mapping[str, ResourceType],
    context: CatalogContext,
) -> list[FieldError]:
    errors: list[FieldError] = []
    for index, connector in enumerate(connectors):
        errors += connector_reference_errors(
            connector, resource_types, context.allowed_suffixes, f"connectors.{index}."
        )
    return errors


def _all_service_and_action_errors(
    services: list[ServiceDefinition],
    connector_specs: Mapping[str, ConnectorSpec],
    context: CatalogContext,
) -> list[FieldError]:
    errors: list[FieldError] = []
    for index, service in enumerate(services):
        prefix = f"services.{index}."
        errors += service_reference_errors(
            service, connector_specs, context.allowed_suffixes, prefix
        )
        for action_index, action in enumerate(service.actions):
            errors += action_reference_errors(
                action, service, connector_specs, f"{prefix}actions.{action_index}."
            )
    return errors


async def _prepare(repo: ServiceRepository, catalog: Catalog, context: CatalogContext) -> _Prepared:
    db_resources = {resource.id: resource for resource in await repo.list_resources()}
    db_connectors = {connector.id: connector for connector in await repo.list_connectors()}

    errors: list[FieldError] = []
    warnings: list[FieldError] = []
    contents: dict[str, bytes] = {}
    for index, resource in enumerate(catalog.resources):
        content, resource_errors, resource_warnings = _prepare_resource(
            resource, db_resources.get(resource.id), context, index
        )
        errors += resource_errors
        warnings += resource_warnings
        if content is not None:
            contents[resource.id] = content

    resource_types = _resource_types(db_resources, catalog.resources)
    connector_specs = _connector_specs(db_connectors, catalog.connectors)
    errors += _all_connector_errors(catalog.connectors, resource_types, context)
    errors += _all_service_and_action_errors(catalog.services, connector_specs, context)
    return _Prepared(errors, warnings, contents, db_resources, db_connectors, connector_specs)


def _resource_record(
    resource: ResourceSpec,
    existing: Resource | None,
    content: bytes | None,
    context: CatalogContext,
) -> Resource | None:
    """The `Resource` row to upsert for one catalog resource, or None if nothing changed."""
    if content is None:
        # No source (already uploaded): only its description can change from the catalog.
        assert existing is not None
        if existing.description == resource.description:
            return None
        existing.description = resource.description
        return existing
    assert resource.source is not None
    fingerprint = context.cipher.fingerprint(content)
    provenance = _provenance(resource.source)
    if existing is not None and (
        existing.fingerprint,
        existing.type,
        existing.description,
        existing.source,
    ) == (fingerprint, resource.type, resource.description, provenance):
        return None
    return Resource(
        id=resource.id,
        type=resource.type,
        ciphertext=context.cipher.encrypt(content),
        fingerprint=fingerprint,
        size=len(content),
        description=resource.description,
        source=provenance,
    )


async def _write_resources(
    repo: ServiceRepository,
    resources: list[ResourceSpec],
    prepared: _Prepared,
    context: CatalogContext,
    dry_run: bool,
    counts: dict[str, int],
) -> None:
    for resource in resources:
        existing = prepared.db_resources.get(resource.id)
        record = _resource_record(resource, existing, prepared.contents.get(resource.id), context)
        if record is None:
            counts["unchanged"] += 1
            continue
        counts["updated" if existing else "created"] += 1
        if not dry_run:
            await repo.upsert_resource(record)


async def _write_connectors(
    repo: ServiceRepository,
    connectors: list[ConnectorSpec],
    db_connectors: Mapping[str, Connector],
    dry_run: bool,
    counts: dict[str, int],
) -> None:
    for connector in connectors:
        counts["updated" if connector.id in db_connectors else "created"] += 1
        if not dry_run:
            await repo.upsert_connector(Connector(spec=connector))


async def _upsert_action(
    repo: ServiceRepository,
    service_id: str,
    action: ActionSpec,
    connector_specs: Mapping[str, ConnectorSpec],
) -> None:
    kind = connector_type(connector_specs[action.connector])
    # Reuse the existing action's id (the real business key is (service_id, key), not id) so
    # re-importing the same catalog stays idempotent instead of generating a fresh UUID per
    # import and orphaning any Execution.action_definition_id FK.
    existing_action = await repo.get_action(service_id, action.key)
    fields = action.model_dump(exclude={"connector"})
    fields["config"] = validate_action_config(kind, action.config)
    if existing_action is not None:
        fields["id"] = existing_action.id
    await repo.upsert_action(
        ActionDefinition(
            service_id=service_id,
            connector_id=action.connector,
            action_type=ActionType(kind.value),
            **fields,
        )
    )


async def _write_service(
    repo: ServiceRepository,
    item: ServiceDefinition,
    connector_specs: Mapping[str, ConnectorSpec],
    dry_run: bool,
) -> bool:
    """Upsert one service and its actions; returns whether the service already existed."""
    exists = await repo.get_service(item.id) is not None
    if not dry_run:
        await repo.upsert_service(Service(id=item.id, spec=item.to_spec()))
        for action in item.actions:
            await _upsert_action(repo, item.id, action, connector_specs)
    return exists


async def _write_services(
    repo: ServiceRepository,
    services: list[ServiceDefinition],
    connector_specs: Mapping[str, ConnectorSpec],
    dry_run: bool,
    counts: dict[str, int],
) -> None:
    for item in services:
        exists = await _write_service(repo, item, connector_specs, dry_run)
        counts["updated" if exists else "created"] += 1


async def _write(
    repo: ServiceRepository,
    catalog: Catalog,
    prepared: _Prepared,
    context: CatalogContext,
    dry_run: bool,
) -> dict[str, dict[str, int]]:
    counts = {
        kind: {"created": 0, "updated": 0, "unchanged": 0}
        for kind in ("resources", "connectors", "services")
    }
    await _write_resources(repo, catalog.resources, prepared, context, dry_run, counts["resources"])
    await _write_connectors(
        repo, catalog.connectors, prepared.db_connectors, dry_run, counts["connectors"]
    )
    await _write_services(
        repo, catalog.services, prepared.connector_specs, dry_run, counts["services"]
    )
    return counts


async def import_catalog_yaml(
    repo: ServiceRepository, raw: str, *, dry_run: bool, context: CatalogContext
) -> CatalogImportOutcome:
    try:
        catalog, node = _parse(raw)
    except DomainValidationError as exc:
        return CatalogImportOutcome(dry_run=dry_run, valid=False, errors=exc.field_errors)
    prepared = await _prepare(repo, catalog, context)
    warnings = _with_lines(node, prepared.warnings)
    if prepared.errors:
        return CatalogImportOutcome(
            dry_run=dry_run,
            valid=False,
            errors=_with_lines(node, prepared.errors),
            warnings=warnings,
        )
    counts = await _write(repo, catalog, prepared, context, dry_run)
    return CatalogImportOutcome(
        dry_run=dry_run,
        valid=True,
        created=counts["services"]["created"],
        updated=counts["services"]["updated"],
        warnings=warnings,
        counts=counts,
    )


async def import_startup_catalog(
    repo: ServiceRepository, path: str | None, context: CatalogContext
) -> None:
    if path is None:
        return
    catalog_path = Path(path)
    if not catalog_path.exists():
        raise RuntimeError(f"Initial catalog file does not exist: {path}")
    outcome = await import_catalog_yaml(
        repo, catalog_path.read_text(encoding="utf-8"), dry_run=False, context=context
    )
    for warning in outcome.warnings:
        logger.warning(f"Initial catalog: {warning.path}: {warning.message}")
    if not outcome.valid:
        details = "; ".join(f"{error.path}: {error.message}" for error in outcome.errors)
        raise DomainValidationError(f"Initial catalog is invalid: {details}", outcome.errors)


def _action_to_catalog_dict(action: ActionDefinition) -> dict[str, Any]:
    item: dict[str, Any] = {
        "key": action.key,
        "label": action.label,
        "description": action.description,
        "icon": action.icon,
        "risk_level": action.risk_level.value,
        "requires_confirmation": action.requires_confirmation,
        "enabled": action.enabled,
        "unattended": action.unattended,
        "connector": action.connector_id,
        "config": action.config,
        "allowed_parameters_schema": action.allowed_parameters_schema,
    }
    return {key: value for key, value in item.items() if value is not None}


async def export_catalog(repo: ServiceRepository) -> str:
    """Secrets-free YAML dump of the persisted catalog: resources appear as metadata plus their
    file/env source only — never content, and never an inline literal."""
    resources: list[dict[str, Any]] = []
    for resource in await repo.list_resources():
        item: dict[str, Any] = {"id": resource.id, "type": resource.type.value}
        if resource.description:
            item["description"] = resource.description
        if "file" in resource.source or "env" in resource.source:
            item["source"] = dict(resource.source)
        resources.append(item)
    connectors = [
        connector.spec.model_dump(mode="json", exclude_none=True)
        for connector in await repo.list_connectors()
    ]
    services, _ = await repo.list_services(offset=0, limit=10000)
    actions_by_service = await repo.list_actions_for_services([service.id for service in services])
    document: dict[str, Any] = {
        "version": 2,
        "resources": resources,
        "connectors": connectors,
        "services": [
            {
                "id": service.id,
                **service.spec.model_dump(mode="json", exclude_none=True),
                "actions": [
                    _action_to_catalog_dict(action)
                    for action in actions_by_service.get(service.id, [])
                ],
            }
            for service in services
        ],
    }
    return yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
