"""Router registration: aggregates every per-domain router onto the app."""

from fastapi import FastAPI

from capataz_api.adapters.inbound.routers.actions import router as actions_router
from capataz_api.adapters.inbound.routers.audit import router as audit_router
from capataz_api.adapters.inbound.routers.auth import router as auth_router
from capataz_api.adapters.inbound.routers.catalog import router as catalog_router
from capataz_api.adapters.inbound.routers.executions import router as executions_router
from capataz_api.adapters.inbound.routers.health import router as health_router
from capataz_api.adapters.inbound.routers.services import router as services_router


def register_routes(app: FastAPI) -> None:
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(services_router)
    app.include_router(actions_router)
    app.include_router(executions_router)
    app.include_router(catalog_router)
    app.include_router(audit_router)
