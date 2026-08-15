from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from capataz_api.adapters.inbound.routers.deps import execution_service_dependency, require
from capataz_api.adapters.inbound.schemas import ExecutionEventResponse, ExecutionResponse, Page
from capataz_api.application.policies.rbac import ROLE_OPERATOR, ROLE_VIEWER
from capataz_api.application.services import ExecutionService
from capataz_api.domain.entities import Execution, Principal

router = APIRouter(prefix="/api/v1", tags=["Executions"])


@router.get("/executions")
async def list_executions(
    service: Annotated[ExecutionService, Depends(execution_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_VIEWER))],
    service_id: str | None = None,
    status: str | None = None,
    actor: str | None = None,
    source: str | None = None,
    offset: int = 0,
    limit: Annotated[int, Query(le=100)] = 20,
) -> Page[ExecutionResponse]:
    items, total = await service.list_executions(
        service_id=service_id, status=status, actor=actor, source=source, offset=offset, limit=limit
    )
    return Page(
        items=[ExecutionResponse.model_validate(item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/executions/{execution_id}", response_model=ExecutionResponse)
async def get_execution(
    execution_id: UUID,
    service: Annotated[ExecutionService, Depends(execution_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_VIEWER))],
) -> Execution:
    return await service.get_execution(execution_id)


@router.get("/executions/{execution_id}/events", response_model=list[ExecutionEventResponse])
async def events(
    execution_id: UUID,
    service: Annotated[ExecutionService, Depends(execution_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_VIEWER))],
) -> list[dict[str, Any]]:
    return await service.get_events(execution_id)


@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(
    execution_id: UUID,
    service: Annotated[ExecutionService, Depends(execution_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_OPERATOR))],
) -> None:
    await service.cancel(execution_id)
