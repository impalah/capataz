"""Application-layer use case for listing audit events (CR-066).

Not `application/policies/audit.py::build_audit_event` — that's the policy that shapes an audit
record at write time; this is the read-side use case, previously called directly from the router.
"""

from typing import Any

from capataz_api.application.ports import ServiceRepository


class AuditService:
    def __init__(self, repo: ServiceRepository) -> None:
        self._repo = repo

    async def list_audit(self, **filters: Any) -> tuple[list[dict[str, Any]], int]:
        return await self._repo.list_audit(**filters)
