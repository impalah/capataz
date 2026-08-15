"""Application-layer use cases for Action CRUD (excluding execution, see execution.py)."""

from typing import Any

from capataz_api.application.policies import build_audit_event, validate_action_config
from capataz_api.application.ports import ServiceRepository
from capataz_api.domain.entities import ActionDefinition, Principal, Service
from capataz_api.domain.exceptions import ConflictError, NotFoundError


class ActionApplicationService:
    def __init__(self, repo: ServiceRepository) -> None:
        self._repo = repo

    async def list_actions(self, service_id: str) -> list[ActionDefinition]:
        await self._require_service(service_id)
        return await self._repo.list_actions(service_id)

    async def create_action(
        self,
        service_id: str,
        *,
        data: dict[str, Any],
        principal: Principal,
        request_id: str | None,
    ) -> ActionDefinition:
        service = await self._require_service(service_id)
        action = ActionDefinition(service_id=service_id, **data)
        validate_action_config(service, action)
        action = await self._repo.upsert_action(action)
        await self._repo.append_audit(
            build_audit_event(principal, "action.create", f"{service_id}/{data['key']}", request_id)
        )
        return action

    async def patch_action(
        self,
        service_id: str,
        action_key: str,
        *,
        data: dict[str, Any],
        principal: Principal,
        request_id: str | None,
    ) -> ActionDefinition:
        if data["key"] != action_key:
            raise ConflictError("Action key is immutable")
        service = await self._require_service(service_id)
        existing = await self._repo.get_action(service_id, action_key)
        if existing is None:
            raise NotFoundError("Action not found")
        # Reuse the existing action's id: the real business key is (service_id, key), not id —
        # see CR-005 in docs/code-review-2026-08.md.
        action = ActionDefinition(service_id=service_id, id=existing.id, **data)
        validate_action_config(service, action)
        action = await self._repo.upsert_action(action)
        await self._repo.append_audit(
            build_audit_event(principal, "action.update", f"{service_id}/{action_key}", request_id)
        )
        return action

    async def delete_action(
        self,
        service_id: str,
        action_key: str,
        *,
        principal: Principal,
        request_id: str | None,
    ) -> None:
        if not await self._repo.delete_action(service_id, action_key):
            # False covers both "doesn't exist" and "has active executions" (CR-077) — same
            # honest-but-ambiguous wording ServiceApplicationService.delete_service already uses,
            # rather than a NotFoundError that would be actively wrong in the second case.
            raise ConflictError("Action does not exist or has active executions")
        # The original implementation omitted this audit record; CLAUDE.md's "every mutation
        # requires ... an audit record" rule applies here exactly as it does to create/update.
        await self._repo.append_audit(
            build_audit_event(principal, "action.delete", f"{service_id}/{action_key}", request_id)
        )

    async def _require_service(self, service_id: str) -> Service:
        service = await self._repo.get_service(service_id)
        if not service:
            raise NotFoundError("Service not found")
        return service
