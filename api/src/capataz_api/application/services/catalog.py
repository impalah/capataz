from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from pydantic import ValidationError as PydanticValidationError

from capataz_api.application.dto.catalog import Catalog, ServiceCatalog
from capataz_api.application.ports import ServiceRepository
from capataz_api.domain.entities import ActionDefinition, Service
from capataz_api.domain.exceptions import FieldError
from capataz_api.domain.exceptions import ValidationError as DomainValidationError


@dataclass(frozen=True)
class CatalogImportOutcome:
    """Always-200 result of a catalog import/dry-run — see docs/05-yaml-catalog.en.md.

    Invalid input is expected, everyday operator feedback (a typo'd field, a missing key), not an
    HTTP-level failure: the caller inspects `valid`/`errors` rather than catching an exception.
    """

    dry_run: bool
    valid: bool
    created: int = 0
    updated: int = 0
    errors: tuple[FieldError, ...] = ()


def _line_for_loc(node: yaml.Node | None, loc: tuple[int | str, ...]) -> int | None:
    """Best-effort: walk a composed YAML node tree following a pydantic error `loc` path.

    Falls back to the deepest node still found along the path (e.g. the parent mapping) when the
    exact key is itself missing — the common case for "Field required" errors, where there is by
    definition no node for the missing field, but the enclosing service block is still useful.
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
            except TypeError, ValueError:
                break
            if index >= len(current.value):
                break
            current = current.value[index]
        else:
            break
    return current.start_mark.line + 1


def parse_catalog_yaml(raw: str) -> Catalog:
    """Parse and validate catalog YAML; raises DomainValidationError with field/line detail."""
    try:
        node = yaml.compose(raw)
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise DomainValidationError(
            "Catalog YAML is not valid YAML", (FieldError(path="$", message=str(exc)),)
        ) from exc
    try:
        return Catalog.model_validate(data)
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


def catalog_service_to_entity(item: ServiceCatalog) -> Service:
    portainer = item.portainer
    return Service(
        id=item.id,
        name=item.name,
        description=item.description,
        group_name=item.group_name,
        environment=item.environment,
        icon=item.icon,
        service_url=str(item.service_url) if item.service_url else None,
        documentation_url=str(item.documentation_url) if item.documentation_url else None,
        portainer_environment_id=str(portainer.environment_id) if portainer else None,
        portainer_stack_name=portainer.stack_name if portainer else None,
        container_selectors={
            "containers": [entry.model_dump() for entry in portainer.containers],
            "aggregation": portainer.aggregation,
        }
        if portainer
        else {},
        health_config=item.health.model_dump(mode="json") if item.health else {},
        grafana_config=item.grafana,
        loki_config=item.loki,
        metadata=item.metadata,
        maintenance=item.maintenance,
    )


async def upsert_catalog(
    repo: ServiceRepository, catalog: Catalog, dry_run: bool = False
) -> CatalogImportOutcome:
    created = 0
    updated = 0
    for item in catalog.services:
        service = catalog_service_to_entity(item)
        if await repo.get_service(item.id) is None:
            created += 1
        else:
            updated += 1
        if not dry_run:
            await repo.upsert_service(service)
            for action in item.actions:
                # Reuse the existing action's id (the real business key is (service_id, key), not
                # id) so re-importing the same catalog stays idempotent instead of generating a
                # fresh UUID per import and orphaning any Execution.action_definition_id FK.
                existing = await repo.get_action(item.id, action.key)
                fields = action.model_dump()
                if existing is not None:
                    fields["id"] = existing.id
                await repo.upsert_action(ActionDefinition(service_id=item.id, **fields))
    return CatalogImportOutcome(dry_run=dry_run, valid=True, created=created, updated=updated)


async def import_startup_catalog(repo: ServiceRepository, path: str | None) -> None:
    if path is None:
        return
    catalog_path = Path(path)
    if not catalog_path.exists():
        raise RuntimeError(f"Initial catalog file does not exist: {path}")
    await upsert_catalog(repo, parse_catalog_yaml(catalog_path.read_text(encoding="utf-8")))


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    return value.value if hasattr(value, "value") else value


def _action_to_catalog_dict(action: ActionDefinition) -> dict[str, Any]:
    # id/service_id are infrastructure-level identity, not part of the ActionCatalog schema
    # (extra="forbid") — omitting them is what makes a fresh export re-importable (round-trip).
    return {
        key: _json_safe(value)
        for key, value in asdict(action).items()
        if key not in {"id", "service_id"}
    }


def _service_to_catalog_dict(service: Service, actions: list[ActionDefinition]) -> dict[str, Any]:
    """Inverse of catalog_service_to_entity: a Service/its actions -> catalog YAML shape."""
    item = {key: _json_safe(value) for key, value in asdict(service).items()}
    item.pop("created_at", None)
    item.pop("updated_at", None)
    item.pop("version", None)
    item["portainer"] = (
        {
            "environment_id": item.pop("portainer_environment_id"),
            "stack_name": item.pop("portainer_stack_name"),
            **item.pop("container_selectors"),
        }
        if service.portainer_environment_id
        else None
    )
    item["health"] = item.pop("health_config") or None
    item["grafana"] = item.pop("grafana_config")
    item["loki"] = item.pop("loki_config")
    item["actions"] = [_action_to_catalog_dict(action) for action in actions]
    return {key: value for key, value in item.items() if value is not None}


async def export_catalog(repo: ServiceRepository) -> str:
    """Secrets-free, transient-data-free YAML dump of the persisted catalog (yaml-catalog.md)."""
    services, _ = await repo.list_services(offset=0, limit=10000)
    actions_by_service = await repo.list_actions_for_services([service.id for service in services])
    document: dict[str, Any] = {
        "version": 1,
        "services": [
            _service_to_catalog_dict(service, actions_by_service.get(service.id, []))
            for service in services
        ],
    }
    return yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
