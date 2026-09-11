from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from capataz_api.adapters.inbound.routers.deps import (
    connector_application_service_dependency,
    require,
)
from capataz_api.adapters.inbound.schemas import ConnectorInput, ConnectorResponse
from capataz_api.application.policies.rbac import ROLE_ADMIN
from capataz_api.application.services import ConnectorApplicationService
from capataz_api.domain.entities import Principal

router = APIRouter(prefix="/api/v1", tags=["Connectors"])

Service = Annotated[ConnectorApplicationService, Depends(connector_application_service_dependency)]
Admin = Annotated[Principal, Depends(require(ROLE_ADMIN))]


@router.get("/connectors")
async def list_connectors(service: Service, principal: Admin) -> list[ConnectorResponse]:
    return [ConnectorResponse.from_entity(item) for item in await service.list_connectors()]


@router.get("/connectors/{connector_id}")
async def get_connector(connector_id: str, service: Service, principal: Admin) -> ConnectorResponse:
    return ConnectorResponse.from_entity(await service.get_connector(connector_id))


@router.post("/connectors", status_code=201)
async def create_connector(
    payload: ConnectorInput, request: Request, service: Service, principal: Admin
) -> ConnectorResponse:
    created = await service.create_connector(
        data=payload.root.model_dump(mode="json"),
        principal=principal,
        request_id=request.state.request_id,
    )
    return ConnectorResponse.from_entity(created)


@router.put("/connectors/{connector_id}")
async def update_connector(
    connector_id: str,
    payload: ConnectorInput,
    request: Request,
    service: Service,
    principal: Admin,
    # Optional compare-and-swap, same semantics as a service PATCH's expected_version (CR-034).
    expected_version: int | None = None,
) -> ConnectorResponse:
    updated = await service.update_connector(
        connector_id,
        data=payload.root.model_dump(mode="json"),
        expected_version=expected_version,
        principal=principal,
        request_id=request.state.request_id,
    )
    return ConnectorResponse.from_entity(updated)


@router.delete("/connectors/{connector_id}", status_code=204, response_model=None)
async def delete_connector(
    connector_id: str, request: Request, service: Service, principal: Admin
) -> Response:
    await service.delete_connector(
        connector_id, principal=principal, request_id=request.state.request_id
    )
    return Response(status_code=204)
