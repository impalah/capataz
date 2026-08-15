"""Application-layer use cases for Service CRUD, status and links."""

from typing import Any

from capataz_api.application.policies import build_audit_event, resolve_links
from capataz_api.application.ports import ServiceRepository
from capataz_api.application.services.status import StatusService
from capataz_api.domain.entities import Principal, Service
from capataz_api.domain.exceptions import ConflictError, NotFoundError


class ServiceApplicationService:
    def __init__(self, repo: ServiceRepository, status_service: StatusService) -> None:
        self._repo = repo
        self._status_service = status_service

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
        # sync by refresh_status below), so this is a plain pass-through like every other filter
        # — no more re-filtering/re-counting a page already truncated by offset/limit.
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
        service = Service(**data)
        if await self._repo.get_service(service.id):
            raise ConflictError("Service id already exists")
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
        existing = await self.get_service(service_id)
        for key, value in data.items():
            setattr(existing, key, value)
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
        result = await self._status_service.refresh(service)
        # CR-063: mirror the freshly computed status onto the queryable column. This is the only
        # place a service's status is ever computed server-side (see StatusService.refresh), so
        # it's also the only place status_cache needs writing.
        await self._repo.update_status_cache(service_id, str(result["status"]))
        return result

    async def get_status(self, service_id: str) -> dict[str, Any]:
        service = await self.get_service(service_id)
        result = await self._status_service.get(service)
        return result or {"service_id": service_id, "status": "unknown"}

    async def get_links(
        self,
        service_id: str,
        *,
        portainer_url: str | None,
        grafana_url: str | None,
        loki_url: str | None,
    ) -> dict[str, str]:
        service = await self.get_service(service_id)
        return resolve_links(service, portainer_url, grafana_url, loki_url)
