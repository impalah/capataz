"""FastAPI application factory: assembles middleware, routes and error handling."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from capataz_api.bootstrap.exception_handlers import (
    UnhandledExceptionMiddleware,
    register_exception_handlers,
)
from capataz_api.bootstrap.lifespan import lifespan
from capataz_api.bootstrap.routing import register_routes
from capataz_api.core.settings import Settings, get_settings
from capataz_api.infrastructure.observability import CorrelationIdMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="Capataz API", version="0.1.1", openapi_url="/api/v1/openapi.json", lifespan=lifespan
    )
    app.add_middleware(CorrelationIdMiddleware)
    # Must be added before CORSMiddleware below: add_middleware wraps in reverse order, so the
    # later CORSMiddleware ends up outermost and still gets a chance to add CORS headers to
    # whatever response this middleware returns for an otherwise-unhandled exception (see its
    # docstring — Starlette's own ServerErrorMiddleware sits outside all of this and can't).
    app.add_middleware(UnhandledExceptionMiddleware)

    configured = settings or get_settings()
    app.state.configured_settings = configured
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[item.strip() for item in configured.cors_origins.split(",")],
        allow_credentials=True,
        # Kept in sync with the verbs/headers actually issued by frontend/src/api/client.ts —
        # credentials are allowed, so wildcards here would be broader than necessary.
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "X-Dev-User",
            "X-Dev-Groups",
        ],
        expose_headers=["X-Request-ID"],
    )

    register_routes(app)
    register_exception_handlers(app)

    return app
