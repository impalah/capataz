"""FastAPI dependencies shared by every router in this package."""

from collections.abc import AsyncIterator, Callable

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capataz_api.application.policies import require_role
from capataz_api.application.ports import ServiceRepository
from capataz_api.application.services import (
    ActionApplicationService,
    AuditService,
    CatalogContext,
    ConnectorApplicationService,
    ExecutionService,
    ResourceApplicationService,
    ServiceApplicationService,
)
from capataz_api.domain.entities import Principal
from capataz_api.infrastructure.database.repositories import SqlAlchemyRepository


async def repo_dependency(request: Request) -> AsyncIterator[ServiceRepository]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        try:
            yield SqlAlchemyRepository(session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def current_principal(request: Request) -> Principal:
    provider = request.app.state.identity_provider
    return await provider.authenticate(request.headers.get("authorization"), dict(request.headers))


def require(required: str) -> Callable[[Principal], Principal]:
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        require_role(principal, required)
        return principal

    return dependency


def service_application_service_dependency(
    request: Request, repo: ServiceRepository = Depends(repo_dependency)
) -> ServiceApplicationService:
    state = request.app.state
    return ServiceApplicationService(
        repo, state.status_service, state.resource_cipher, state.settings.health_suffixes
    )


def catalog_context_dependency(request: Request) -> CatalogContext:
    context: CatalogContext = request.app.state.catalog_context
    return context


def connector_application_service_dependency(
    request: Request, repo: ServiceRepository = Depends(repo_dependency)
) -> ConnectorApplicationService:
    return ConnectorApplicationService(repo, request.app.state.settings.health_suffixes)


def resource_application_service_dependency(
    request: Request, repo: ServiceRepository = Depends(repo_dependency)
) -> ResourceApplicationService:
    return ResourceApplicationService(repo, request.app.state.resource_cipher)


def action_application_service_dependency(
    repo: ServiceRepository = Depends(repo_dependency),
) -> ActionApplicationService:
    return ActionApplicationService(repo)


def execution_service_dependency(
    request: Request, repo: ServiceRepository = Depends(repo_dependency)
) -> ExecutionService:
    return ExecutionService(repo, request.app.state.queue)


def audit_service_dependency(repo: ServiceRepository = Depends(repo_dependency)) -> AuditService:
    return AuditService(repo)
