"""Builds the audit-event dict persisted via ServiceRepository.append_audit."""

from typing import Any

from capataz_api.domain.entities import Principal


def build_audit_event(
    principal: Principal,
    action: str,
    resource: str,
    request_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "actor": principal.subject,
        "actor_name": principal.name,
        "actor_email": principal.email,
        "action": action,
        "resource": resource,
        "request_id": request_id,
    }
    if metadata is not None:
        event["metadata"] = metadata
    return event
