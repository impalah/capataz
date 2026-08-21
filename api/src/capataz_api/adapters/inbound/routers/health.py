from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from sqlalchemy import text

router = APIRouter(tags=["Health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "live"}


@router.get(
    "/health/ready",
    responses={503: {"description": "One or more dependencies (database, cache) are not ready"}},
)
async def ready(request: Request) -> dict[str, str]:
    try:
        async with request.app.state.session_factory() as session:
            await session.execute(text("SELECT 1"))
        cache = request.app.state.status_cache
        if hasattr(cache, "client"):
            await cache.client.ping()
    except Exception as exc:
        # The 503 body is deliberately generic (no dependency internals leaked to a caller), so the
        # specific failure (which dependency, what error) must be logged here or it's lost entirely.
        logger.exception("Readiness check failed")
        raise HTTPException(status_code=503, detail="Dependencies are not ready") from exc
    return {"status": "ready"}
