"""Resource endpoints. Content goes in (base64 JSON, max 64 KiB) but never comes back out."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from capataz_api.adapters.inbound.routers.deps import (
    require,
    resource_application_service_dependency,
)
from capataz_api.adapters.inbound.schemas import (
    ResourceContentUpdate,
    ResourceCreate,
    ResourceResponse,
)
from capataz_api.application.policies.rbac import ROLE_ADMIN
from capataz_api.application.services import ResourceApplicationService
from capataz_api.domain.entities import Principal

router = APIRouter(prefix="/api/v1", tags=["Resources"])

Service = Annotated[ResourceApplicationService, Depends(resource_application_service_dependency)]
Admin = Annotated[Principal, Depends(require(ROLE_ADMIN))]


@router.get("/resources")
async def list_resources(service: Service, principal: Admin) -> list[ResourceResponse]:
    return [ResourceResponse.from_entity(item) for item in await service.list_resources()]


@router.get("/resources/{resource_id}")
async def get_resource(resource_id: str, service: Service, principal: Admin) -> ResourceResponse:
    return ResourceResponse.from_entity(await service.get_resource(resource_id))


@router.post("/resources", status_code=201)
async def create_resource(
    payload: ResourceCreate, request: Request, service: Service, principal: Admin
) -> ResourceResponse:
    created = await service.create_resource(
        resource_id=payload.id,
        resource_type=payload.type.value,
        description=payload.description,
        content=payload.content(),
        principal=principal,
        request_id=request.state.request_id,
    )
    return ResourceResponse.from_entity(created)


@router.put("/resources/{resource_id}/content")
async def replace_resource_content(
    resource_id: str,
    payload: ResourceContentUpdate,
    request: Request,
    service: Service,
    principal: Admin,
) -> ResourceResponse:
    updated = await service.replace_resource(
        resource_id,
        content=payload.content(),
        description=payload.description,
        principal=principal,
        request_id=request.state.request_id,
    )
    return ResourceResponse.from_entity(updated)


@router.delete("/resources/{resource_id}", status_code=204, response_model=None)
async def delete_resource(
    resource_id: str, request: Request, service: Service, principal: Admin
) -> Response:
    await service.delete_resource(
        resource_id, principal=principal, request_id=request.state.request_id
    )
    return Response(status_code=204)
