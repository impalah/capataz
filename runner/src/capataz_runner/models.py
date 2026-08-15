"""Lightweight SQLAlchemy mappings for the tables owned and migrated by api/."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Runner-local declarative base; it does not create or migrate API tables."""


class ServiceRecord(Base):
    __tablename__ = "services"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    portainer_environment_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    container_selectors: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ActionDefinitionRecord(Base):
    __tablename__ = "action_definitions"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), index=True)
    key: Mapped[str] = mapped_column(String(128))
    action_type: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ExecutionRecord(Base):
    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), index=True)
    action_definition_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("action_definitions.id"), index=True
    )
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExecutionEventRecord(Base):
    __tablename__ = "execution_events"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("executions.id"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    level: Mapped[str] = mapped_column(String(20))
    event_type: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
