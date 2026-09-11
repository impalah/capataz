"""Application-layer use cases for connector CRUD (docs/adr/008-connectors-and-resources)."""

from typing import Any

from pydantic import ValidationError as PydanticValidationError

from capataz_api.application.policies import (
    build_audit_event,
    connector_reference_errors,
    describe_error,
)
from capataz_api.application.ports import ServiceRepository
from capataz_api.domain.entities import Connector, Principal
from capataz_api.domain.exceptions import ConflictError, NotFoundError, ValidationError
from capataz_api.domain.specs import CONNECTOR_SPEC_ADAPTER, ConnectorSpec


class ConnectorApplicationService:
    def __init__(self, repo: ServiceRepository, allowed_suffixes: tuple[str, ...]) -> None:
        self._repo = repo
        self._allowed_suffixes = allowed_suffixes

    async def list_connectors(self) -> list[Connector]:
        return await self._repo.list_connectors()

    async def get_connector(self, connector_id: str) -> Connector:
        connector = await self._repo.get_connector(connector_id)
        if connector is None:
            raise NotFoundError("Connector not found")
        return connector

    async def create_connector(
        self, *, data: dict[str, Any], principal: Principal, request_id: str | None
    ) -> Connector:
        spec = self._parse(data)
        if await self._repo.get_connector(spec.id):
            raise ConflictError("Connector id already exists")
        await self._check_resources(spec)
        result = await self._repo.upsert_connector(Connector(spec=spec))
        await self._repo.append_audit(
            build_audit_event(principal, "connector.create", spec.id, request_id)
        )
        return result

    async def update_connector(
        self,
        connector_id: str,
        *,
        data: dict[str, Any],
        principal: Principal,
        request_id: str | None,
        expected_version: int | None = None,
    ) -> Connector:
        existing = await self.get_connector(connector_id)
        if data.get("id", connector_id) != connector_id:
            raise ConflictError("Connector id is immutable")
        spec = self._parse({**data, "id": connector_id})
        if spec.type != existing.spec.type:
            # Services and actions were validated against the old type's capabilities/config.
            raise ConflictError("Connector type is immutable; create a new connector instead")
        await self._check_resources(spec)
        version = expected_version if expected_version is not None else existing.version
        result = await self._repo.upsert_connector(
            Connector(spec=spec, version=version), enforce_version=expected_version is not None
        )
        await self._repo.append_audit(
            build_audit_event(principal, "connector.update", connector_id, request_id)
        )
        return result

    async def delete_connector(
        self, connector_id: str, *, principal: Principal, request_id: str | None
    ) -> None:
        await self.get_connector(connector_id)
        users = await self._usages(connector_id)
        if users:
            raise ConflictError(f"Connector {connector_id!r} is still used by: {', '.join(users)}")
        await self._repo.delete_connector(connector_id)
        await self._repo.append_audit(
            build_audit_event(principal, "connector.delete", connector_id, request_id)
        )

    async def _usages(self, connector_id: str) -> list[str]:
        services, _ = await self._repo.list_services(offset=0, limit=10000)
        users = [
            f"service {service.id} ({usage.path})"
            for service in services
            for usage in service.spec.connector_usages()
            if usage.connector_id == connector_id
        ]
        users += [
            f"action {action.service_id}/{action.key}"
            for action in await self._repo.list_actions_by_connector(connector_id)
        ]
        return users

    @staticmethod
    def _parse(data: dict[str, Any]) -> ConnectorSpec:
        try:
            return CONNECTOR_SPEC_ADAPTER.validate_python(data)
        except PydanticValidationError as exc:
            raise ValidationError(f"Invalid connector: {describe_error(exc)}") from None

    async def _check_resources(self, spec: ConnectorSpec) -> None:
        resource_types = {
            resource.id: resource.type for resource in await self._repo.list_resources()
        }
        errors = connector_reference_errors(spec, resource_types, self._allowed_suffixes)
        if errors:
            summary = "; ".join(f"{error.path}: {error.message}" for error in errors)
            raise ValidationError(f"Invalid connector: {summary}", tuple(errors))
