from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from capataz_api.domain.exceptions import ConflictError
from capataz_api.domain.value_objects import ActionType, ExecutionSource, ExecutionStatus, RiskLevel


def utcnow() -> datetime:
    return datetime.now(UTC)


TERMINAL_EXECUTION_STATUSES = frozenset(
    {
        ExecutionStatus.SUCCEEDED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
        ExecutionStatus.REJECTED,
    }
)


@dataclass(slots=True)
class Service:
    id: str
    name: str
    group_name: str
    environment: str
    description: str | None = None
    icon: str | None = None
    service_url: str | None = None
    documentation_url: str | None = None
    portainer_environment_id: str | None = None
    portainer_stack_name: str | None = None
    container_selectors: dict[str, Any] = field(default_factory=dict)
    health_config: dict[str, Any] = field(default_factory=dict)
    grafana_config: dict[str, Any] = field(default_factory=dict)
    loki_config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    maintenance: bool = False
    version: int = 1
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class ActionDefinition:
    service_id: str
    key: str
    label: str
    action_type: ActionType
    risk_level: RiskLevel
    id: UUID = field(default_factory=uuid4)
    description: str | None = None
    icon: str | None = None
    requires_confirmation: bool = False
    enabled: bool = True
    unattended: bool = False
    config: dict[str, Any] = field(default_factory=dict)
    allowed_parameters_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Execution:
    # Nullable: ON DELETE SET NULL lets execution history survive its service/action being
    # deleted. service_id_snapshot is the non-null, immutable display label captured at
    # creation time — service_id (the FK, also the human-readable slug) is the only field
    # that goes blank once the service is gone.
    service_id: str | None
    service_id_snapshot: str
    action_definition_id: UUID | None
    action_key: str
    requested_by_subject: str
    source: ExecutionSource
    correlation_id: str
    id: UUID = field(default_factory=uuid4)
    requested_by_email: str | None = None
    requested_by_name: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    status: ExecutionStatus = ExecutionStatus.QUEUED
    requested_at: datetime = field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    worker_task_id: str | None = None
    result_summary: str | None = None
    error_code: str | None = None
    error_summary: str | None = None

    def transition_to(self, target: ExecutionStatus) -> None:
        transitions = {
            ExecutionStatus.QUEUED: {
                ExecutionStatus.RUNNING,
                ExecutionStatus.CANCELLED,
                ExecutionStatus.REJECTED,
            },
            ExecutionStatus.RUNNING: {
                ExecutionStatus.SUCCEEDED,
                ExecutionStatus.FAILED,
                ExecutionStatus.CANCELLED,
                ExecutionStatus.TIMED_OUT,
            },
        }
        if target not in transitions.get(self.status, set()):
            raise ConflictError(f"Invalid execution transition: {self.status} -> {target}")
        self.status = target
        now = utcnow()
        if target == ExecutionStatus.RUNNING:
            self.started_at = now
        if target in TERMINAL_EXECUTION_STATUSES:
            self.finished_at = now

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_EXECUTION_STATUSES


@dataclass(slots=True)
class Principal:
    subject: str
    groups: set[str]
    email: str | None = None
    name: str | None = None
