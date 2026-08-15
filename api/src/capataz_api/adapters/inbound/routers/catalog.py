from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

from capataz_api.adapters.inbound.routers.deps import repo_dependency, require
from capataz_api.adapters.inbound.schemas import (
    CatalogFieldErrorResponse,
    CatalogImport,
    CatalogImportResponse,
)
from capataz_api.application.policies import build_audit_event
from capataz_api.application.policies.rbac import ROLE_ADMIN
from capataz_api.application.ports import ServiceRepository
from capataz_api.application.services import (
    CatalogImportOutcome,
    export_catalog,
    parse_catalog_yaml,
    upsert_catalog,
)
from capataz_api.domain.entities import Principal
from capataz_api.domain.exceptions import ValidationError

router = APIRouter(prefix="/api/v1", tags=["Catalog"])


@router.post("/catalog/import")
async def catalog_import(
    payload: CatalogImport,
    request: Request,
    repo: Annotated[ServiceRepository, Depends(repo_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_ADMIN))],
) -> CatalogImportResponse:
    # Invalid input is expected, everyday operator feedback here, not an HTTP-level failure — the
    # response is always 200; the client checks `valid`/`errors` (see CatalogImportOutcome).
    try:
        catalog = parse_catalog_yaml(payload.yaml)
    except ValidationError as exc:
        outcome = CatalogImportOutcome(
            dry_run=payload.dry_run, valid=False, errors=exc.field_errors
        )
    else:
        outcome = await upsert_catalog(repo, catalog, payload.dry_run)
    await repo.append_audit(
        build_audit_event(
            principal,
            "catalog.import",
            "catalog",
            request.state.request_id,
            metadata={"dry_run": payload.dry_run, "valid": outcome.valid},
        )
    )
    return CatalogImportResponse(
        dry_run=outcome.dry_run,
        valid=outcome.valid,
        created=outcome.created,
        updated=outcome.updated,
        errors=[
            CatalogFieldErrorResponse(path=error.path, message=error.message, line=error.line)
            for error in outcome.errors
        ],
    )


@router.get("/catalog/export", response_class=PlainTextResponse)
async def catalog_export(
    repo: Annotated[ServiceRepository, Depends(repo_dependency)],
    principal: Annotated[Principal, Depends(require(ROLE_ADMIN))],
) -> str:
    return await export_catalog(repo)
