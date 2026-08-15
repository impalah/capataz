"""ASGI entry point.

Application wiring (lifespan, exception handlers, routing, the FastAPI
factory itself) lives in `capataz_api.bootstrap` — see that package for the
actual startup/shutdown, error-handling and routing logic.
"""

from capataz_api.bootstrap import create_app
from capataz_api.core.settings import get_settings

app = create_app()


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "capataz_api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.env == "development",
    )
