from typing import Annotated

from fastapi import APIRouter, Depends, Query

from capataz_api.adapters.inbound.routers.deps import audit_service_dependency, require
from capataz_api.adapters.inbound.schemas import AuditEventResponse, Page
from capataz_api.application.policies.rbac import ROLE_ADMIN
from capataz_api.application.services import AuditService
from capataz_api.domain.entities import Principal

router = APIRouter(prefix="/api/v1", tags=["Audit"])


@router.get("/audit-events")
async def audit_events(
    service: Annotated[AuditService, Depends(audit_service_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_ADMIN))],
    offset: int = 0,
    limit: Annotated[int, Query(le=100)] = 20,
) -> Page[AuditEventResponse]:
    items, total = await service.list_audit(offset=offset, limit=limit)
    return Page(
        items=[AuditEventResponse.model_validate(item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
    )
