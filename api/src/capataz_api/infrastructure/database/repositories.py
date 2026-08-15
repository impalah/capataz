from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from capataz_api.application.policies import sanitize
from capataz_api.domain.entities import ActionDefinition, Execution, Service
from capataz_api.domain.exceptions import ConflictError
from capataz_api.domain.value_objects import ActionType, ExecutionSource, ExecutionStatus, RiskLevel
from capataz_api.infrastructure.database.models import (
    ActionDefinitionModel,
    AuditEventModel,
    ExecutionEventModel,
    ExecutionModel,
    ServiceModel,
)


def service_from(model: ServiceModel) -> Service:
    return Service(
        id=model.id,
        name=model.name,
        description=model.description,
        group_name=model.group_name,
        icon=model.icon,
        environment=model.environment,
        service_url=model.service_url,
        documentation_url=model.documentation_url,
        portainer_environment_id=model.portainer_environment_id,
        portainer_stack_name=model.portainer_stack_name,
        container_selectors=model.container_selectors,
        health_config=model.health_config,
        grafana_config=model.grafana_config,
        loki_config=model.loki_config,
        metadata=model.metadata_json,
        maintenance=model.maintenance,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def action_from(model: ActionDefinitionModel) -> ActionDefinition:
    return ActionDefinition(
        id=model.id,
        service_id=model.service_id,
        key=model.key,
        label=model.label,
        description=model.description,
        icon=model.icon,
        action_type=ActionType(model.action_type),
        risk_level=RiskLevel(model.risk_level),
        requires_confirmation=model.requires_confirmation,
        enabled=model.enabled,
        unattended=model.unattended,
        config=model.config,
        allowed_parameters_schema=model.allowed_parameters_schema,
    )


def execution_from(model: ExecutionModel) -> Execution:
    return Execution(
        id=model.id,
        service_id=model.service_id,
        service_id_snapshot=model.service_id_snapshot,
        action_definition_id=model.action_definition_id,
        action_key=model.action_key,
        requested_by_subject=model.requested_by_subject,
        requested_by_email=model.requested_by_email,
        requested_by_name=model.requested_by_name,
        source=ExecutionSource(model.source),
        params=model.params,
        status=ExecutionStatus(model.status),
        requested_at=model.requested_at,
        started_at=model.started_at,
        finished_at=model.finished_at,
        correlation_id=model.correlation_id,
        worker_task_id=model.worker_task_id,
        result_summary=model.result_summary,
        error_code=model.error_code,
        error_summary=model.error_summary,
    )


class SqlAlchemyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _flush_translating_conflicts(self) -> None:
        """A raw IntegrityError is an expected, user-facing conflict (409), never a 500."""
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise ConflictError("A record with the same identifier already exists") from exc

    async def get_service(self, service_id: str) -> Service | None:
        model = await self.session.get(ServiceModel, service_id)
        return service_from(model) if model else None

    async def list_services(self, **filters: object) -> tuple[list[Service], int]:
        query = select(ServiceModel)
        if group := filters.get("group_name"):
            query = query.where(ServiceModel.group_name == group)
        if environment := filters.get("environment"):
            query = query.where(ServiceModel.environment == environment)
        if status := filters.get("status"):
            # CR-063: status_cache is a persisted mirror of the last computed ServiceStatus
            # (written by update_status_cache below), so this filters in SQL like every other
            # field here — no more fetching a page then discarding rows in application code.
            query = query.where(ServiceModel.status_cache == status)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        offset, limit = int(str(filters.get("offset", 0))), int(str(filters.get("limit", 50)))
        rows = list(
            (
                await self.session.scalars(
                    query.order_by(ServiceModel.name).offset(offset).limit(limit)
                )
            ).all()
        )
        return [service_from(row) for row in rows], total

    async def upsert_service(self, service: Service, *, enforce_version: bool = False) -> Service:
        """`enforce_version` performs an explicit compare-and-swap against `service.version`.

        Off by default (plain upsert, used by service creation and idempotent catalog import,
        neither of which have a meaningful "expected version" to compare against). Callers that
        already loaded the row earlier in the same request — i.e. an application-layer patch
        flow — should pass `enforce_version=True` so two concurrent PATCH requests reading the
        same row can't silently overwrite one another (CR-034 in docs/code-review-2026-08.md).
        """
        model = await self.session.get(ServiceModel, service.id)
        fields = {
            "name": service.name,
            "description": service.description,
            "group_name": service.group_name,
            "icon": service.icon,
            "environment": service.environment,
            "service_url": service.service_url,
            "documentation_url": service.documentation_url,
            "portainer_environment_id": service.portainer_environment_id,
            "portainer_stack_name": service.portainer_stack_name,
            "container_selectors": service.container_selectors,
            "health_config": service.health_config,
            "grafana_config": service.grafana_config,
            "loki_config": service.loki_config,
            "metadata_json": sanitize(service.metadata),
            "maintenance": service.maintenance,
        }
        if model is None:
            model = ServiceModel(id=service.id, **fields)
            self.session.add(model)
        else:
            if enforce_version and model.version != service.version:
                raise ConflictError("The record was modified by another request; reload and retry")
            for key, value in fields.items():
                setattr(model, key, value)
            model.version += 1
        await self._flush_translating_conflicts()
        await self.session.refresh(model)
        return service_from(model)

    async def delete_service(self, service_id: str) -> bool:
        model = await self.session.get(ServiceModel, service_id)
        if not model:
            return False
        active = await self.session.scalar(
            select(ExecutionModel.id)
            .where(
                ExecutionModel.service_id == service_id,
                ExecutionModel.status.in_(["queued", "running"]),
            )
            .limit(1)
        )
        if active:
            return False
        await self.session.delete(model)
        await self._flush_translating_conflicts()
        return True

    async def update_status_cache(self, service_id: str, status: str) -> None:
        """Mirror a freshly computed status onto the row so list_services can filter on it.

        A plain UPDATE, not upsert_service: this is a system-derived cache value, not a
        user-visible edit, so it deliberately doesn't touch `version`/`updated_at` or go through
        optimistic-concurrency checks.
        """
        await self.session.execute(
            update(ServiceModel)
            .where(ServiceModel.id == service_id)
            .values(status_cache=status, status_cache_updated_at=datetime.now(UTC))
        )
        await self._flush_translating_conflicts()

    async def list_actions(self, service_id: str) -> list[ActionDefinition]:
        rows = list(
            (
                await self.session.scalars(
                    select(ActionDefinitionModel)
                    .where(ActionDefinitionModel.service_id == service_id)
                    .order_by(ActionDefinitionModel.key)
                )
            ).all()
        )
        return [action_from(row) for row in rows]

    async def list_actions_for_services(
        self, service_ids: list[str]
    ) -> dict[str, list[ActionDefinition]]:
        """Batched form of list_actions — one query for N services (CR-080), not N queries."""
        if not service_ids:
            return {}
        rows = list(
            (
                await self.session.scalars(
                    select(ActionDefinitionModel)
                    .where(ActionDefinitionModel.service_id.in_(service_ids))
                    .order_by(ActionDefinitionModel.service_id, ActionDefinitionModel.key)
                )
            ).all()
        )
        by_service: dict[str, list[ActionDefinition]] = {
            service_id: [] for service_id in service_ids
        }
        for row in rows:
            by_service[row.service_id].append(action_from(row))
        return by_service

    async def get_action(self, service_id: str, key: str) -> ActionDefinition | None:
        model = await self.session.scalar(
            select(ActionDefinitionModel).where(
                ActionDefinitionModel.service_id == service_id, ActionDefinitionModel.key == key
            )
        )
        return action_from(model) if model else None

    async def upsert_action(self, action: ActionDefinition) -> ActionDefinition:
        model = await self.session.scalar(
            select(ActionDefinitionModel).where(
                ActionDefinitionModel.service_id == action.service_id,
                ActionDefinitionModel.key == action.key,
            )
        )
        fields = {
            "label": action.label,
            "description": action.description,
            "icon": action.icon,
            "action_type": action.action_type.value,
            "risk_level": action.risk_level.value,
            "requires_confirmation": action.requires_confirmation,
            "enabled": action.enabled,
            "unattended": action.unattended,
            "config": sanitize(action.config),
            "allowed_parameters_schema": action.allowed_parameters_schema,
        }
        if model is None:
            model = ActionDefinitionModel(
                id=action.id, service_id=action.service_id, key=action.key, **fields
            )
            self.session.add(model)
        else:
            for key, value in fields.items():
                setattr(model, key, value)
        await self._flush_translating_conflicts()
        return action_from(model)

    async def delete_action(self, service_id: str, key: str) -> bool:
        model = await self.session.scalar(
            select(ActionDefinitionModel).where(
                ActionDefinitionModel.service_id == service_id, ActionDefinitionModel.key == key
            )
        )
        if not model:
            return False
        # Same precheck delete_service already has, extended here to match (CR-077): a queued/
        # running execution must not be orphaned mid-flight by deleting the action it's running.
        # Historical (terminal) executions no longer block deletion — action_definition_id is
        # ON DELETE SET NULL, and action_key already preserves the display label.
        active = await self.session.scalar(
            select(ExecutionModel.id)
            .where(
                ExecutionModel.action_definition_id == model.id,
                ExecutionModel.status.in_(["queued", "running"]),
            )
            .limit(1)
        )
        if active:
            return False
        await self.session.delete(model)
        await self._flush_translating_conflicts()
        return True

    async def create_execution(self, execution: Execution) -> Execution:
        model = ExecutionModel(
            id=execution.id,
            service_id=execution.service_id,
            service_id_snapshot=execution.service_id_snapshot,
            action_definition_id=execution.action_definition_id,
            action_key=execution.action_key,
            requested_by_subject=execution.requested_by_subject,
            requested_by_email=execution.requested_by_email,
            requested_by_name=execution.requested_by_name,
            source=execution.source.value,
            params=sanitize(execution.params),
            status=execution.status.value,
            requested_at=execution.requested_at,
            started_at=execution.started_at,
            finished_at=execution.finished_at,
            correlation_id=execution.correlation_id,
            worker_task_id=execution.worker_task_id,
            result_summary=execution.result_summary,
            error_code=execution.error_code,
            error_summary=execution.error_summary,
        )
        self.session.add(model)
        await self._flush_translating_conflicts()
        return execution_from(model)

    async def get_execution(self, execution_id: UUID) -> Execution | None:
        model = await self.session.get(ExecutionModel, execution_id)
        return execution_from(model) if model else None

    async def list_executions(self, **filters: object) -> tuple[list[Execution], int]:
        query = select(ExecutionModel)
        for field, column in [
            ("service_id", ExecutionModel.service_id),
            ("status", ExecutionModel.status),
            ("actor", ExecutionModel.requested_by_subject),
            ("source", ExecutionModel.source),
        ]:
            if value := filters.get(field):
                query = query.where(column == (value.value if hasattr(value, "value") else value))
        total = await self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        offset, limit = int(str(filters.get("offset", 0))), int(str(filters.get("limit", 50)))
        rows = list(
            (
                await self.session.scalars(
                    query.order_by(ExecutionModel.requested_at.desc()).offset(offset).limit(limit)
                )
            ).all()
        )
        return [execution_from(row) for row in rows], total

    async def events(self, execution_id: UUID) -> list[dict[str, Any]]:
        rows = list(
            (
                await self.session.scalars(
                    select(ExecutionEventModel)
                    .where(ExecutionEventModel.execution_id == execution_id)
                    .order_by(ExecutionEventModel.sequence)
                )
            ).all()
        )
        return [
            {
                "id": str(row.id),
                "sequence": row.sequence,
                "timestamp": row.timestamp.isoformat(),
                "level": row.level,
                "event_type": row.event_type,
                "message": row.message,
                "data": row.data,
            }
            for row in rows
        ]

    async def append_audit(self, event: dict[str, Any]) -> None:
        self.session.add(
            AuditEventModel(
                actor=str(event["actor"]),
                actor_name=event.get("actor_name"),
                actor_email=event.get("actor_email"),
                action=str(event["action"]),
                resource=str(event["resource"]),
                outcome=str(event.get("outcome", "success")),
                ip_address=event.get("ip_address"),
                request_id=event.get("request_id"),
                metadata_json=sanitize(event.get("metadata", {})),
            )
        )
        await self._flush_translating_conflicts()

    async def list_audit(self, **filters: object) -> tuple[list[dict[str, Any]], int]:
        total = await self.session.scalar(select(func.count()).select_from(AuditEventModel)) or 0
        offset, limit = int(str(filters.get("offset", 0))), int(str(filters.get("limit", 50)))
        rows = list(
            (
                await self.session.scalars(
                    select(AuditEventModel)
                    .order_by(AuditEventModel.timestamp.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        return [
            {
                "id": str(row.id),
                "timestamp": row.timestamp.isoformat(),
                "actor": row.actor,
                "actor_name": row.actor_name,
                "actor_email": row.actor_email,
                "action": row.action,
                "resource": row.resource,
                "outcome": row.outcome,
                "request_id": row.request_id,
                "metadata": row.metadata_json,
            }
            for row in rows
        ], total
