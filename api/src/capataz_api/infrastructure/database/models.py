from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

JSONType = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class ServiceModel(Base):
    __tablename__ = "services"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    group_name: Mapped[str] = mapped_column(String(128))
    icon: Mapped[str | None] = mapped_column(String(128))
    environment: Mapped[str] = mapped_column(String(128))
    service_url: Mapped[str | None] = mapped_column(Text)
    documentation_url: Mapped[str | None] = mapped_column(Text)
    portainer_environment_id: Mapped[str | None] = mapped_column(String(128))
    portainer_stack_name: Mapped[str | None] = mapped_column(String(255))
    container_selectors: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    health_config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    grafana_config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    loki_config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict)
    maintenance: Mapped[bool] = mapped_column(Boolean, default=False)
    # Queryable mirror of the last computed ServiceStatus, written by
    # ServiceApplicationService.refresh_status after StatusService.refresh() — the
    # authoritative status still lives in the Redis StatusCache; this column exists solely
    # so list_services can filter by `status` in SQL instead of scanning every service
    # through the cache in application code.
    status_cache: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status_cache_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Optimistic concurrency is enforced explicitly in SqlAlchemyRepository.upsert_service (compares
    # the caller-supplied `version` against the current row) rather than via SQLAlchemy's built-in
    # `version_id_col`, which only protects a single session's own load-then-flush window and would
    # not catch the cross-request "two PATCH requests read, then both write" race this needs to
    # guard against (see CR-034 in docs/code-review-2026-08.md).


class ActionDefinitionModel(Base):
    __tablename__ = "action_definitions"
    __table_args__ = (UniqueConstraint("service_id", "key", name="uq_action_service_key"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_id: Mapped[str] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(128))
    label: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(String(128))
    action_type: Mapped[str] = mapped_column(String(32))
    risk_level: Mapped[str] = mapped_column(String(32))
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    unattended: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    allowed_parameters_schema: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class ExecutionModel(Base):
    __tablename__ = "executions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # ondelete="SET NULL": execution history survives its service/action being deleted (CR-077).
    # service_id_snapshot (below) is the non-null label that keeps history legible once service_id
    # goes NULL — Service.id is a human-readable slug, not a surrogate key, so unlike action_key
    # (already denormalized for the same reason) there was no display fallback without it.
    service_id: Mapped[str | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), index=True
    )
    service_id_snapshot: Mapped[str] = mapped_column(String(128))
    action_definition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("action_definitions.id", ondelete="SET NULL"), index=True
    )
    action_key: Mapped[str] = mapped_column(String(128))
    requested_by_subject: Mapped[str] = mapped_column(String(255), index=True)
    requested_by_email: Mapped[str | None] = mapped_column(String(255))
    requested_by_name: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(32), index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(32), index=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    worker_task_id: Mapped[str | None] = mapped_column(String(255))
    result_summary: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_summary: Mapped[str | None] = mapped_column(Text)


class ExecutionEventModel(Base):
    __tablename__ = "execution_events"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence", name="uq_execution_event_sequence"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("executions.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    level: Mapped[str] = mapped_column(String(32))
    event_type: Mapped[str] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class AuditEventModel(Base):
    __tablename__ = "audit_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(String(255), index=True)
    actor_name: Mapped[str | None] = mapped_column(String(255))
    actor_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(128))
    resource: Mapped[str] = mapped_column(String(255))
    outcome: Mapped[str] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(128), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict)
