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
from capataz_api.adapters.outbound.connector_factory import DefaultConnectorClientFactory
from capataz_api.application.services.catalog import CatalogContext, import_startup_catalog
from capataz_api.application.services.status import StatusService
from capataz_api.core.logging import configure_logging
from capataz_api.core.settings import Settings, get_settings
from capataz_api.infrastructure.celery import CeleryExecutionPublisher
from capataz_api.infrastructure.crypto import FernetResourceCipher
from capataz_api.infrastructure.database import build_engine, build_session_factory
from capataz_api.infrastructure.database.repositories import SqlAlchemyRepository
from capataz_api.infrastructure.resources import FileSystemResourceSourceLoader
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
    master_key = read_secret("resources_master_key")
    assert master_key is not None  # required=True (the default) never returns None
    cipher = FernetResourceCipher.from_secret(master_key)
    app.state.resource_cipher = cipher
    app.state.status_service = StatusService(
        DefaultConnectorClientFactory(settings.health_suffixes, settings.http_timeout_seconds)
    )
    app.state.catalog_context = CatalogContext(
        cipher=cipher,
        loader=FileSystemResourceSourceLoader(settings.resources_dir),
        inline_permitted=settings.inline_resources_permitted,
        allowed_suffixes=settings.health_suffixes,
    )
    if settings.initial_catalog_yaml_path:
        async with app.state.session_factory() as session:
            try:
                await import_startup_catalog(
                    SqlAlchemyRepository(session),
                    settings.initial_catalog_yaml_path,
                    app.state.catalog_context,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Initial catalog import failed")
                raise
    yield
    await redis_client.aclose()
    await app.state.engine.dispose()
