from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response

from capataz_api.adapters.inbound.routers.deps import (
    require,
    service_application_service_dependency,
)
from capataz_api.adapters.inbound.schemas import (
    Page,
    ServiceInput,
    ServicePatch,
    ServiceResponse,
)
from capataz_api.application.policies.rbac import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER
from capataz_api.application.services import ServiceApplicationService
from capataz_api.domain.entities import Principal, Service

router = APIRouter(prefix="/api/v1", tags=["Services"])


@router.get("/services")
async def list_services(
    service: Annotated[ServiceApplicationService, Depends(service_application_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_VIEWER))],
    group_name: str | None = None,
    environment: str | None = None,
    status: str | None = None,
    offset: int = 0,
    limit: Annotated[int, Query(le=100)] = 20,
) -> Page[ServiceResponse]:
    items, total = await service.list_services(
        group_name=group_name,
        environment=environment,
        status=status,
        offset=offset,
        limit=limit,
    )
    return Page(
        items=[ServiceResponse.model_validate(item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/services", status_code=201, response_model=ServiceResponse)
async def create_service(
    payload: ServiceInput,
    request: Request,
    service: Annotated[ServiceApplicationService, Depends(service_application_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_ADMIN))],
) -> Service:
    return await service.create_service(
        data=payload.model_dump(), principal=principal, request_id=request.state.request_id
    )


@router.get("/services/{service_id}", response_model=ServiceResponse)
async def get_service(
    service_id: str,
    service: Annotated[ServiceApplicationService, Depends(service_application_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_VIEWER))],
) -> Service:
    return await service.get_service(service_id)


@router.patch("/services/{service_id}", response_model=ServiceResponse)
async def patch_service(
    service_id: str,
    payload: ServicePatch,
    request: Request,
    service: Annotated[ServiceApplicationService, Depends(service_application_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_ADMIN))],
) -> Service:
    # exclude_unset (not exclude_none): distinguishes "the client didn't send this field" from
    # "the client explicitly sent it as empty/false".
    # A client that PATCHes only {name} must never wipe container_selectors/maintenance/etc, which
    # default to {}/False rather than None and so survived exclude_none unchanged.
    values = payload.model_dump(exclude_unset=True)
    values.pop("id", None)
    expected_version = values.pop("expected_version", None)
    return await service.patch_service(
        service_id,
        data=values,
        expected_version=expected_version,
        principal=principal,
        request_id=request.state.request_id,
    )


@router.delete("/services/{service_id}", status_code=204, response_model=None)
async def delete_service(
    service_id: str,
    request: Request,
    service: Annotated[ServiceApplicationService, Depends(service_application_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_ADMIN))],
) -> Response:
    await service.delete_service(
        service_id, principal=principal, request_id=request.state.request_id
    )
    return Response(status_code=204)


@router.post("/services/{service_id}/refresh-status")
async def refresh_status(
    service_id: str,
    service: Annotated[ServiceApplicationService, Depends(service_application_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_OPERATOR))],
) -> dict[str, Any]:
    return await service.refresh_status(service_id)


@router.get("/services/{service_id}/status")
async def get_status(
    service_id: str,
    service: Annotated[ServiceApplicationService, Depends(service_application_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_VIEWER))],
) -> dict[str, Any]:
    return await service.get_status(service_id)


@router.get("/services/{service_id}/links")
async def links(
    service_id: str,
    request: Request,
    service: Annotated[ServiceApplicationService, Depends(service_application_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_VIEWER))],
) -> dict[str, str]:
    settings = request.app.state.settings
    return await service.get_links(
        service_id,
        portainer_url=str(settings.portainer_url) if settings.portainer_url else None,
        grafana_url=str(settings.grafana_url) if settings.grafana_url else None,
        loki_url=str(settings.loki_url) if settings.loki_url else None,
    )
