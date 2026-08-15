from enum import StrEnum


class ServiceStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    MAINTENANCE = "maintenance"
    UNKNOWN = "unknown"


class ActionType(StrEnum):
    PORTAINER = "portainer"
    ANSIBLE = "ansible"
    HTTP = "http"
    SSH = "ssh"
    RSYNC = "rsync"


class RiskLevel(StrEnum):
    READ = "read"
    OPERATE = "operate"
    CRITICAL = "critical"


class ExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"


class ExecutionSource(StrEnum):
    UI = "ui"
    API = "api"
    YAML = "yaml"
    N8N = "n8n"
    MCP = "mcp"
    CRON = "cron"
    ALERT = "alert"
    SYSTEM = "system"


class AggregationMode(StrEnum):
    ALL_REQUIRED = "all_required"
    ANY_HEALTHY = "any_healthy"
