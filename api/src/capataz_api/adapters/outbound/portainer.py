from typing import Any

import httpx

from capataz_api.domain.exceptions import ExternalServiceError


class PortainerClient:
    def __init__(self, base_url: str, token: str, timeout: float = 5) -> None:
        self.base_url, self.token, self.timeout = base_url.rstrip("/"), token, timeout

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
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
        items = await self._request(
            "GET", f"/api/endpoints/{environment_id}/docker/containers/json", params={"all": "true"}
        )
        names = {str(item.get("name", "")).lstrip("/") for item in selectors.get("containers", [])}
        return [
            {
                "name": str(row.get("Names", [""])[0]).lstrip("/"),
                "running": row.get("State") == "running",
                "healthy": (row.get("Status", "").endswith("(healthy)"))
                if "healthy" in row.get("Status", "")
                else None,
            }
            for row in items
            if str(row.get("Names", [""])[0]).lstrip("/") in names
        ]
