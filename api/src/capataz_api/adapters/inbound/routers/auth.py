from typing import Annotated, Any

from fastapi import APIRouter, Depends

from capataz_api.adapters.inbound.routers.deps import require
from capataz_api.application.policies.rbac import ROLE_VIEWER
from capataz_api.domain.entities import Principal

router = APIRouter(prefix="/api/v1", tags=["Auth"])


@router.get("/auth/me")
async def me(principal: Annotated[Principal, Depends(require(ROLE_VIEWER))]) -> dict[str, Any]:
    return {
        "subject": principal.subject,
        "email": principal.email,
        "name": principal.name,
        "groups": sorted(principal.groups),
    }
