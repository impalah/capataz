"""Stable automation executor port, shared by persistent and future ephemeral workers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class AutomationJob:
    execution_id: str
    service_id: str
    action_type: str
    action_config: dict[str, Any]
    service_container_selectors: dict[str, Any]
    portainer_environment_id: str | None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None


class AutomationExecutorPort(Protocol):
    """Boundary permitting replacement by an isolated Docker job executor in V2."""

    async def execute(self, job: AutomationJob) -> ExecutionResult:
        """Execute one already-persisted, declarative automation job."""
