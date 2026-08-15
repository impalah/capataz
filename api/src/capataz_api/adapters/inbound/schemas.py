from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from capataz_api.domain.value_objects import (
    ActionType,
    ExecutionSource,
    ExecutionStatus,
    RiskLevel,
)

# RFC 7231/7807 status-to-section mapping used to default ProblemDetail.type.
_STATUS_TO_SECTION: dict[int, str] = {
    400: "6.5.1",
    401: "https://datatracker.ietf.org/doc/html/rfc7235#section-3.1",
    403: "6.5.3",
    404: "6.5.4",
    405: "6.5.5",
    409: "6.5.8",
    422: "https://datatracker.ietf.org/doc/html/rfc4918#section-11.2",
    429: "https://datatracker.ietf.org/doc/html/rfc6585#section-4",
    500: "6.6.1",
    502: "6.6.3",
    503: "6.6.4",
}


def rfc_section_url(status: int) -> str:
    """Resolve the RFC section URL documenting a given HTTP status code."""
    base_url = "https://datatracker.ietf.org/doc/html/rfc7231#section-"
    section = _STATUS_TO_SECTION.get(status, "6.6.1")
    return section if section.startswith("https://") else f"{base_url}{section}"


class ServiceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    group_name: str
    environment: str
    description: str | None = None
    icon: str | None = None
    service_url: str | None = None
    documentation_url: str | None = None
    portainer_environment_id: str | None = None
    portainer_stack_name: str | None = None
    container_selectors: dict[str, Any] = Field(default_factory=dict)
    health_config: dict[str, Any] = Field(default_factory=dict)
    grafana_config: dict[str, Any] = Field(default_factory=dict)
    loki_config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    maintenance: bool = False


class ServicePatch(ServiceInput):
    id: str | None = None
    # Optional: when supplied, the update is rejected with 409 if the row has changed since the
    # client last read this version (see CR-034 in docs/code-review-2026-08.md). Omitting it keeps
    # the previous, more permissive last-write-wins behavior for callers that don't send it yet.
    expected_version: int | None = None


class ActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    label: str
    action_type: ActionType
    risk_level: RiskLevel
    description: str | None = None
    icon: str | None = None
    requires_confirmation: bool = False
    enabled: bool = True
    unattended: bool = False
    config: dict[str, Any]
    allowed_parameters_schema: dict[str, Any] = Field(default_factory=dict)


class ExecuteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    params: dict[str, Any] = Field(default_factory=dict)
    source: ExecutionSource = ExecutionSource.UI
    confirmation: bool = False
    reason: str | None = None


class CatalogImport(BaseModel):
    yaml: str
    dry_run: bool = False


class CatalogFieldErrorResponse(BaseModel):
    path: str
    message: str
    line: int | None = None


class CatalogImportResponse(BaseModel):
    dry_run: bool
    valid: bool
    created: int = 0
    updated: int = 0
    errors: list[CatalogFieldErrorResponse] = Field(default_factory=list)


class Page[T](BaseModel):
    items: list[T]
    total: int
    offset: int
    limit: int


class ServiceResponse(BaseModel):
    """Response DTO for Service; from_attributes lets it serialize the dataclass directly."""

    model_config = ConfigDict(from_attributes=True)
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
    container_selectors: dict[str, Any]
    health_config: dict[str, Any]
    grafana_config: dict[str, Any]
    loki_config: dict[str, Any]
    metadata: dict[str, Any]
    maintenance: bool
    version: int
    created_at: datetime
    updated_at: datetime


class ActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    service_id: str
    key: str
    label: str
    action_type: ActionType
    risk_level: RiskLevel
    description: str | None = None
    icon: str | None = None
    requires_confirmation: bool
    enabled: bool
    unattended: bool
    config: dict[str, Any]
    allowed_parameters_schema: dict[str, Any]


class ExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    # Nullable: SET NULL once the referenced service/action is deleted (CR-077) — clients must
    # use service_id_snapshot (never null) to display the execution's history, and treat a null
    # service_id/action_definition_id as "the underlying record no longer exists".
    service_id: str | None
    service_id_snapshot: str
    action_definition_id: UUID | None
    action_key: str
    requested_by_subject: str
    requested_by_email: str | None = None
    requested_by_name: str | None = None
    source: ExecutionSource
    params: dict[str, Any]
    status: ExecutionStatus
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    correlation_id: str
    worker_task_id: str | None = None
    result_summary: str | None = None
    error_code: str | None = None
    error_summary: str | None = None


class ExecutionEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    sequence: int
    timestamp: str
    level: str
    event_type: str
    message: str
    data: dict[str, Any]


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    timestamp: str
    actor: str
    actor_name: str | None = None
    actor_email: str | None = None
    action: str
    resource: str
    outcome: str
    request_id: str | None = None
    metadata: dict[str, Any]


class ValidationErrorDetail(BaseModel):
    """A single field-level validation failure, one per Pydantic/FastAPI error."""

    type: str = Field(description="Error type, e.g. 'value_error' or 'missing'")
    loc: tuple[str, ...] = Field(description="Error location in the request")
    msg: str = Field(description="Human-readable error message")
    input: Any = Field(default=None, description="The invalid input value")
    ctx: dict[str, str] | None = Field(default=None, description="Additional error context")
    url: str | None = Field(default=None, description="Pydantic error documentation URL")


class ProblemDetail(BaseModel):
    """RFC 7807 Problem Details response, returned by every error handler."""

    type: str | None = Field(
        default=None,
        description="URI reference identifying the problem type",
        json_schema_extra={
            "example": "https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.1"
        },
    )
    title: str = Field(description="Short, human-readable summary of the problem type")
    status: int = Field(description="HTTP status code", json_schema_extra={"example": 400})
    detail: str | None = Field(default=None, description="Explanation specific to this occurrence")
    instance: str | None = Field(
        default=None, description="Request path that produced this problem"
    )
    errors: list[ValidationErrorDetail] | None = Field(
        default=None, description="Field-level validation errors, present only for 422 responses"
    )
    correlation_id: str | None = Field(
        default=None, description="Correlation id for this request (also sent as X-Request-ID)"
    )

    @model_validator(mode="before")
    @classmethod
    def _default_type(cls, values: dict[str, Any]) -> dict[str, Any]:
        if not values.get("type"):
            values["type"] = rfc_section_url(values.get("status", 500))
        return values
