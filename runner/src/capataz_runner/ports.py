"""Stable automation executor port, shared by persistent and future ephemeral workers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class AutomationJob:
    execution_id: str
    service_id: str
    # Always equal to the type of the action's connector (checked when the job is loaded).
    action_type: str
    action_config: dict[str, Any]
    connector_config: dict[str, Any] = field(default_factory=dict)
    # The service spec's `runtime` block: environment_id, stack_name and its containers/services
    # selectors. Only Portainer actions use it.
    runtime: dict[str, Any] | None = None
    # Connector config field -> decrypted resource content. Kept out of repr so a logged job can
    # never print it.
    secrets: dict[str, bytes] = field(default_factory=dict, repr=False)
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
