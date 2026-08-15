"""Application startup/shutdown: builds every resource held in `app.state`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger
from redis.asyncio import Redis

from capataz_api.adapters.inbound.auth import (
    CognitoIdentityProvider,
    DevMockIdentityProvider,
    OidcIdentityProvider,
)
from capataz_api.adapters.outbound.health import HttpHealthProber
from capataz_api.adapters.outbound.portainer import PortainerClient
from capataz_api.application.services.catalog import import_startup_catalog
from capataz_api.application.services.status import StatusService
from capataz_api.core.logging import configure_logging
from capataz_api.core.settings import Settings, get_settings
from capataz_api.infrastructure.celery import CeleryExecutionPublisher
from capataz_api.infrastructure.database import build_engine, build_session_factory
from capataz_api.infrastructure.database.repositories import SqlAlchemyRepository
from capataz_api.infrastructure.health import RedisStatusCache
from capataz_api.infrastructure.secrets import read_secret


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = getattr(app.state, "configured_settings", get_settings())
    configure_logging(settings.log_level, settings.log_json)
    app.state.settings = settings
    app.state.engine = build_engine(settings)
    app.state.session_factory = build_session_factory(app.state.engine)
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.redis = redis_client
    app.state.status_cache = RedisStatusCache(redis_client)
    app.state.queue = CeleryExecutionPublisher(settings.redis_url, settings.celery_queue)
    if settings.auth_mode == "dev_mock":
        app.state.identity_provider = DevMockIdentityProvider()
    elif settings.auth_mode == "oidc":
        app.state.identity_provider = OidcIdentityProvider(
            settings.oidc_issuer,
            settings.oidc_audience,
            settings.oidc_jwks_uri or None,
            settings.oidc_groups_claim,
        )
    else:
        app.state.identity_provider = CognitoIdentityProvider(
            settings.cognito_region, settings.cognito_user_pool_id, settings.cognito_app_client_id
        )
    platform = None
    if settings.portainer_url:
        token = read_secret("portainer_token", required=False)
        if token:
            platform = PortainerClient(
                str(settings.portainer_url), token, settings.http_timeout_seconds
            )
    app.state.status_service = StatusService(
        app.state.status_cache,
        platform,
        HttpHealthProber(settings.health_suffixes, settings.http_timeout_seconds),
        settings.status_cache_ttl_seconds,
    )
    if settings.initial_catalog_yaml_path:
        async with app.state.session_factory() as session:
            try:
                await import_startup_catalog(
                    SqlAlchemyRepository(session), settings.initial_catalog_yaml_path
                )
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Initial catalog import failed")
                raise
    yield
    await redis_client.aclose()
    await app.state.engine.dispose()
