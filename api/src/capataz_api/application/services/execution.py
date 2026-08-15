"""Application-layer use case for requesting and (attempting to) cancel an Execution."""

from typing import Any, NoReturn
from uuid import UUID

from capataz_api.application.policies import authorize_action, build_audit_event, resolve_action
from capataz_api.application.ports import ExecutionQueue, ServiceRepository
from capataz_api.domain.entities import Execution, Principal, Service
from capataz_api.domain.exceptions import ConflictError, NotFoundError
from capataz_api.domain.value_objects import ExecutionSource


class ExecutionService:
    def __init__(self, repo: ServiceRepository, queue: ExecutionQueue) -> None:
        self._repo = repo
        self._queue = queue

    async def request_execution(
        self,
        *,
        service_id: str,
        action_key: str,
        principal: Principal,
        source: ExecutionSource,
        params: dict[str, Any],
        confirmation: bool,
        reason: str | None,
        request_id: str | None,
    ) -> tuple[Execution, str]:
        service = await self._get_checked_service(service_id)
        action = await self._repo.get_action(service_id, action_key)
        if action is None:
            raise NotFoundError("Action not found")
        authorize_action(principal, action.risk_level, confirmation, reason)
        resolve_action(service, action, params)
        execution = Execution(
            service_id=service_id,
            service_id_snapshot=service_id,
            action_definition_id=action.id,
            action_key=action.key,
            requested_by_subject=principal.subject,
            requested_by_email=principal.email,
            requested_by_name=principal.name,
            source=source,
            params=params,
            correlation_id=request_id or "",
        )
        execution = await self._repo.create_execution(execution)
        worker_task_id = await self._queue.enqueue(execution.id)
        execution.worker_task_id = worker_task_id
        await self._repo.append_audit(
            build_audit_event(
                principal,
                "execution.request",
                str(execution.id),
                request_id,
                metadata={"service_id": service_id, "action": action_key},
            )
        )
        return execution, worker_task_id

    async def cancel(self, execution_id: UUID) -> NoReturn:
        execution = await self._repo.get_execution(execution_id)
        if execution is None:
            raise NotFoundError("Execution not found")
        # The runner does not expose a safe revocation contract in V1 (see docs/12-roadmap.en.md);
        # no state mutation is attempted here (see CR-019 in docs/code-review-2026-08.md).
        raise ConflictError("Safe worker cancellation is not enabled in V1")

    async def list_executions(self, **filters: Any) -> tuple[list[Execution], int]:
        return await self._repo.list_executions(**filters)

    async def get_execution(self, execution_id: UUID) -> Execution:
        execution = await self._repo.get_execution(execution_id)
        if execution is None:
            raise NotFoundError("Execution not found")
        return execution

    async def get_events(self, execution_id: UUID) -> list[dict[str, Any]]:
        # CR-066: was previously a bare repo call from the router; routed through the same
        # existence check as get_execution so a 404 here can't silently diverge from that path.
        await self.get_execution(execution_id)
        return await self._repo.events(execution_id)

    async def _get_checked_service(self, service_id: str) -> Service:
        service = await self._repo.get_service(service_id)
        if service is None:
            raise NotFoundError("Service not found")
        return service
