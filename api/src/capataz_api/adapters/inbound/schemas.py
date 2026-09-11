import base64
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    field_validator,
    model_validator,
)

from capataz_api.domain.entities import Connector, Resource, Service
from capataz_api.domain.specs import (
    MAX_RESOURCE_BYTES,
    SERVICE_ID_PATTERN,
    ActionSpec,
    ConnectorSpec,
    ObservabilitySpec,
    RuntimeSpec,
    ServiceSpec,
    connector_capabilities,
)
from capataz_api.domain.value_objects import (
    ActionType,
    ConnectorCapability,
    ConnectorType,
    ExecutionSource,
    ExecutionStatus,
    ResourceType,
    RiskLevel,
)

# base64 of MAX_RESOURCE_BYTES, rounded up to a whole 4-char group.
_MAX_RESOURCE_BASE64 = 4 * ((MAX_RESOURCE_BYTES + 2) // 3)

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


class ServiceInput(ServiceSpec):
    """A new service: its immutable slug id plus the full domain.specs.ServiceSpec."""

    id: str = Field(pattern=SERVICE_ID_PATTERN, max_length=128)


class ServicePatch(BaseModel):
    """Top-level partial update: each supplied field replaces that whole spec field."""

    model_config = ConfigDict(extra="forbid")
    id: str | None = None
    name: str | None = None
    description: str | None = None
    group_name: str | None = None
    environment: str | None = None
    icon: str | None = None
    tags: list[str] | None = None
    service_url: str | None = None
    documentation_url: str | None = None
    runtime: RuntimeSpec | None = None
    observability: ObservabilitySpec | None = None
    metadata: dict[str, Any] | None = None
    maintenance: bool | None = None
    # Optional: when supplied, the update is rejected with 409 if the row has changed since the
    # client last read this version (see CR-034 in docs/code-review-2026-08.md). Omitting it keeps
    # the previous, more permissive last-write-wins behavior for callers that don't send it yet.
    expected_version: int | None = None


class ActionInput(ActionSpec):
    """An action definition; its type is always the type of the connector it references."""


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
    # Services only; `counts` breaks resources/connectors/services down individually.
    created: int = 0
    updated: int = 0
    errors: list[CatalogFieldErrorResponse] = Field(default_factory=list)
    warnings: list[CatalogFieldErrorResponse] = Field(default_factory=list)
    counts: dict[str, dict[str, int]] = Field(default_factory=dict)


class Page[T](BaseModel):
    items: list[T]
    total: int
    offset: int
    limit: int


class ServiceResponse(ServiceSpec):
    """A service as the flat spec fields plus its identity/versioning metadata."""

    id: str
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, service: Service) -> ServiceResponse:
        return cls(
            id=service.id,
            version=service.version,
            created_at=service.created_at,
            updated_at=service.updated_at,
            **service.spec.model_dump(),
        )


class ActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    service_id: str
    key: str
    label: str
    action_type: ActionType
    risk_level: RiskLevel
    connector: str = Field(validation_alias=AliasChoices("connector", "connector_id"))
    description: str | None = None
    icon: str | None = None
    requires_confirmation: bool
    enabled: bool
    unattended: bool
    config: dict[str, Any]
    allowed_parameters_schema: dict[str, Any]


class ConnectorInput(RootModel[ConnectorSpec]):
    """Any connector type; the `type` field selects which config shape is expected."""


class ConnectorResponse(BaseModel):
    id: str
    type: ConnectorType
    description: str | None = None
    config: dict[str, Any]
    capabilities: list[ConnectorCapability]
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, connector: Connector) -> ConnectorResponse:
        return cls(
            id=connector.id,
            type=connector.type,
            description=connector.spec.description,
            config=connector.spec.config.model_dump(mode="json"),
            capabilities=sorted(connector_capabilities(connector.spec)),
            version=connector.version,
            created_at=connector.created_at,
            updated_at=connector.updated_at,
        )


class _ResourceContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_base64: str = Field(min_length=1, max_length=_MAX_RESOURCE_BASE64)

    @field_validator("content_base64")
    @classmethod
    def must_be_base64(cls, value: str) -> str:
        compact = "".join(value.split())
        try:
            base64.b64decode(compact, validate=True)
        except ValueError:
            raise ValueError("content_base64 is not valid base64") from None
        return compact

    def content(self) -> bytes:
        return base64.b64decode(self.content_base64)


class ResourceCreate(_ResourceContent):
    id: str
    type: ResourceType
    description: str | None = None


class ResourceContentUpdate(_ResourceContent):
    description: str | None = None


class ResourceResponse(BaseModel):
    """Metadata only: a resource's content is never returned by any endpoint."""

    id: str
    type: ResourceType
    description: str | None = None
    fingerprint: str = Field(description="Short keyed fingerprint, to tell versions apart")
    size: int
    source: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, resource: Resource) -> ResourceResponse:
        return cls(
            id=resource.id,
            type=resource.type,
            description=resource.description,
            fingerprint=resource.fingerprint[:12],
            size=resource.size,
            source=resource.source,
            version=resource.version,
            created_at=resource.created_at,
            updated_at=resource.updated_at,
        )


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
