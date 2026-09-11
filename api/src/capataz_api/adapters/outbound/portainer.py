from typing import Any

import httpx

from capataz_api.domain.exceptions import ExternalServiceError


class PortainerClient:
    def __init__(self, base_url: str, token: str, timeout: float = 5, verify: bool = True) -> None:
        self.base_url, self.token, self.timeout = base_url.rstrip("/"), token, timeout
        self.verify = verify

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify) as client:
                response = await client.request(
                    method, f"{self.base_url}{path}", headers={"X-API-Key": self.token}, **kwargs
                )
        except httpx.TimeoutException as exc:
            raise ExternalServiceError("Portainer request timed out") from exc
        except httpx.HTTPError as exc:
            raise ExternalServiceError("Portainer is unavailable") from exc
        if response.status_code in {401, 403}:
            raise ExternalServiceError("Portainer authentication was rejected")
        if response.status_code == 404:
            raise ExternalServiceError("Portainer resource was not found")
        if response.status_code >= 500:
            raise ExternalServiceError("Portainer reported an upstream error")
        if response.is_error:
            raise ExternalServiceError("Portainer request was rejected")
        return response.json()

    async def container_states(
        self, environment_id: str, selectors: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if "services" in selectors:
            return await self._service_states(environment_id, selectors)
        items = await self._request(
            "GET", f"/api/endpoints/{environment_id}/docker/containers/json", params={"all": "true"}
        )
        declared = {
            str(entry.get("name", "")).lstrip("/"): entry
            for entry in selectors.get("containers", [])
        }
        rows = []
        for row in items:
            name = str(row.get("Names", [""])[0]).lstrip("/")
            spec = declared.get(name)
            if spec is None:
                continue
            rows.append(
                {
                    "name": name,
                    "running": row.get("State") == "running",
                    "healthy": (row.get("Status", "").endswith("(healthy)"))
                    if "healthy" in row.get("Status", "")
                    else None,
                    "required": bool(spec.get("required", True)),
                    "critical": bool(spec.get("critical", False)),
                }
            )
        return rows

    async def find_link_target(self, environment_id: str, selectors: dict[str, Any]) -> str | None:
        """Resolve the opaque Portainer/Docker ID for a deep link (see policies/links.py).

        Docker's REST API only accepts this ID, never the human-readable name Capataz stores, so
        the link builder can't compute a deep link on its own — it has to ask Portainer.
        """
        if "services" in selectors:
            entries = selectors.get("services", [])
            if not entries:
                return None
            stack = selectors.get("stack_name")
            name = str(entries[0].get("name", ""))
            full_name = f"{stack}_{name}" if stack else name
            items = await self._request("GET", f"/api/endpoints/{environment_id}/docker/services")
            for item in items:
                if str(item.get("Spec", {}).get("Name", "")) == full_name:
                    return str(item.get("ID")) or None
            return None
        entries = selectors.get("containers", [])
        if not entries:
            return None
        name = str(entries[0].get("name", ""))
        items = await self._request(
            "GET", f"/api/endpoints/{environment_id}/docker/containers/json", params={"all": "true"}
        )
        for row in items:
            row_name = str(row.get("Names", [""])[0]).lstrip("/")
            if row_name == name:
                return str(row.get("Id")) or None
        return None

    async def _service_states(
        self, environment_id: str, selectors: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Docker Swarm services, matched by ``{stack_name}_{name}`` (see docs/05-yaml-catalog).

        Swarm mangles per-task container names, so the container-listing endpoint above can never
        match a declared name reliably; the Services API reports desired/running task counts
        directly instead, which is what makes a stable running/healthy read possible.
        """
        items = await self._request(
            "GET", f"/api/endpoints/{environment_id}/docker/services", params={"status": "true"}
        )
        stack = selectors.get("stack_name")
        declared = {
            f"{stack}_{entry.get('name', '')}" if stack else str(entry.get("name", "")): entry
            for entry in selectors.get("services", [])
        }
        rows = []
        for item in items:
            full_name = str(item.get("Spec", {}).get("Name", ""))
            spec = declared.get(full_name)
            if spec is None:
                continue
            status = item.get("ServiceStatus") or {}
            running = int(status.get("RunningTasks", 0))
            desired = int(status.get("DesiredTasks", 0))
            rows.append(
                {
                    "name": full_name,
                    "running": running > 0,
                    "healthy": running >= desired if desired else None,
                    "required": bool(spec.get("required", True)),
                    "critical": bool(spec.get("critical", False)),
                }
            )
        return rows
