from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from capataz_api.adapters.inbound.routers.deps import (
    action_application_service_dependency,
    current_principal,
    execution_service_dependency,
    require,
)
from capataz_api.adapters.inbound.schemas import (
    ActionInput,
    ActionResponse,
    ExecuteInput,
    ExecutionResponse,
)
from capataz_api.application.policies.rbac import ROLE_ADMIN, ROLE_VIEWER
from capataz_api.application.services import ActionApplicationService, ExecutionService
from capataz_api.domain.entities import ActionDefinition, Execution, Principal

router = APIRouter(prefix="/api/v1", tags=["Actions"])


@router.get("/services/{service_id}/actions", response_model=list[ActionResponse])
async def list_actions(
    service_id: str,
    service: Annotated[ActionApplicationService, Depends(action_application_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_VIEWER))],
) -> list[ActionDefinition]:
    return await service.list_actions(service_id)


@router.post("/services/{service_id}/actions", status_code=201, response_model=ActionResponse)
async def create_action(
    service_id: str,
    payload: ActionInput,
    request: Request,
    service: Annotated[ActionApplicationService, Depends(action_application_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_ADMIN))],
) -> ActionDefinition:
    return await service.create_action(
        service_id,
        data=payload.model_dump(),
        principal=principal,
        request_id=request.state.request_id,
    )


@router.patch("/services/{service_id}/actions/{action_key}", response_model=ActionResponse)
async def patch_action(
    service_id: str,
    action_key: str,
    payload: ActionInput,
    request: Request,
    service: Annotated[ActionApplicationService, Depends(action_application_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_ADMIN))],
) -> ActionDefinition:
    return await service.patch_action(
        service_id,
        action_key,
        data=payload.model_dump(),
        principal=principal,
        request_id=request.state.request_id,
    )


@router.delete("/services/{service_id}/actions/{action_key}", status_code=204, response_model=None)
async def delete_action(
    service_id: str,
    action_key: str,
    request: Request,
    service: Annotated[ActionApplicationService, Depends(action_application_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_ADMIN))],
) -> Response:
    await service.delete_action(
        service_id, action_key, principal=principal, request_id=request.state.request_id
    )
    return Response(status_code=204)


@router.post(
    "/services/{service_id}/actions/{action_key}/execute",
    status_code=202,
    response_model=ExecutionResponse,
)
async def execute(
    service_id: str,
    action_key: str,
    payload: ExecuteInput,
    request: Request,
    service: Annotated[ExecutionService, Depends(execution_service_dependency)],
    principal: Annotated[Principal, Depends(current_principal)],
) -> Execution:
    execution, _worker_task_id = await service.request_execution(
        service_id=service_id,
        action_key=action_key,
        principal=principal,
        source=payload.source,
        params=payload.params,
        confirmation=payload.confirmation,
        reason=payload.reason,
        request_id=request.state.request_id,
    )
    return execution
