"""Application-layer use cases for Service CRUD, status and links."""

from typing import Any

from pydantic import ValidationError as PydanticValidationError

from capataz_api.application.policies import (
    build_audit_event,
    describe_error,
    resolve_links,
    service_reference_errors,
)
from capataz_api.application.ports import ResourceCipher, ServiceRepository
from capataz_api.application.services.connector_resolver import ConnectorResolver
from capataz_api.application.services.status import StatusService
from capataz_api.domain.entities import Principal, Service
from capataz_api.domain.exceptions import (
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationError,
)
from capataz_api.domain.specs import ServiceSpec


class ServiceApplicationService:
    def __init__(
        self,
        repo: ServiceRepository,
        status_service: StatusService,
        cipher: ResourceCipher,
        allowed_suffixes: tuple[str, ...],
    ) -> None:
        self._repo = repo
        self._status_service = status_service
        self._cipher = cipher
        self._allowed_suffixes = allowed_suffixes

    async def list_services(
        self,
        *,
        group_name: str | None,
        environment: str | None,
        status: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Service], int]:
        # CR-063: status is filtered in SQL against the persisted status_cache column (kept in
        # sync by refresh_status below), so this is a plain pass-through like every other filter.
        return await self._repo.list_services(
            group_name=group_name,
            environment=environment,
            status=status,
            offset=offset,
            limit=limit,
        )

    async def get_service(self, service_id: str) -> Service:
        service = await self._repo.get_service(service_id)
        if service is None:
            raise NotFoundError("Service not found")
        return service

    async def create_service(
        self, *, data: dict[str, Any], principal: Principal, request_id: str | None
    ) -> Service:
        fields = dict(data)
        service = Service(id=str(fields.pop("id")), spec=self._parse_spec(fields))
        if await self._repo.get_service(service.id):
            raise ConflictError("Service id already exists")
        await self._check_references(service.spec)
        # The pre-check above covers the deterministic case (id already exists); a genuine
        # concurrent race past this point still lands on ConflictError via the repository
        # translating the real unique-constraint IntegrityError (CR-033), not a raw 500.
        result = await self._repo.upsert_service(service)
        await self._repo.append_audit(
            build_audit_event(principal, "service.create", service.id, request_id)
        )
        return result

    async def patch_service(
        self,
        service_id: str,
        *,
        data: dict[str, Any],
        principal: Principal,
        request_id: str | None,
        expected_version: int | None = None,
    ) -> Service:
        """Each supplied top-level spec field replaces that whole field (e.g. `observability`)."""
        existing = await self.get_service(service_id)
        merged = existing.spec.model_dump(mode="json")
        merged.update(data)
        existing.spec = self._parse_spec(merged)
        await self._check_references(existing.spec)
        if expected_version is not None:
            existing.version = expected_version
        result = await self._repo.upsert_service(
            existing, enforce_version=expected_version is not None
        )
        await self._repo.append_audit(
            build_audit_event(principal, "service.update", service_id, request_id)
        )
        return result

    async def delete_service(
        self, service_id: str, *, principal: Principal, request_id: str | None
    ) -> None:
        if not await self._repo.delete_service(service_id):
            raise ConflictError("Service does not exist or has active executions")
        await self._repo.append_audit(
            build_audit_event(principal, "service.delete", service_id, request_id)
        )

    async def refresh_status(self, service_id: str) -> dict[str, Any]:
        service = await self.get_service(service_id)
        result = await self._status_service.refresh(service, self._resolver())
        # CR-063: mirror the freshly computed status onto the queryable column. This is the only
        # place a service's status is ever computed server-side (see StatusService.refresh), so
        # it's also the only place status_cache needs writing.
        await self._repo.update_status_cache(service_id, str(result["status"]))
        return result

    async def get_links(self, service_id: str) -> dict[str, str]:
        service = await self.get_service(service_id)
        connectors = {connector.id: connector for connector in await self._repo.list_connectors()}
        links = resolve_links(service, connectors)
        runtime = service.spec.runtime
        if runtime is None or "portainer" not in links:
            return links
        resolver = self._resolver()
        try:
            connector = await resolver.get(runtime.connector)
            platform = self._status_service.factory.platform(
                connector, await resolver.secrets_for(connector)
            )
            target_id = await platform.find_link_target(
                runtime.environment_id, runtime.platform_selectors()
            )
        except DomainError:
            # The deep link is a convenience; fall back to the list-page link already in
            # `links` rather than failing the whole request when Portainer is unreachable.
            target_id = None
        if target_id:
            base = links["portainer"].split("/#!/", 1)[0]
            links["portainer"] = (
                f"{base}/#!/{runtime.environment_id}/docker/{runtime.selector_kind}/{target_id}"
            )
        return links

    def _resolver(self) -> ConnectorResolver:
        return ConnectorResolver(self._repo, self._cipher)

    @staticmethod
    def _parse_spec(fields: dict[str, Any]) -> ServiceSpec:
        try:
            return ServiceSpec.model_validate(fields)
        except PydanticValidationError as exc:
            raise ValidationError(f"Invalid service: {describe_error(exc)}") from None

    async def _check_references(self, spec: ServiceSpec) -> None:
        connectors = {
            connector.id: connector.spec for connector in await self._repo.list_connectors()
        }
        errors = service_reference_errors(spec, connectors, self._allowed_suffixes)
        if errors:
            summary = "; ".join(f"{error.path}: {error.message}" for error in errors)
            raise ValidationError(f"Invalid references: {summary}", tuple(errors))
