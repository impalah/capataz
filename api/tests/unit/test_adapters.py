import httpx
import pytest

from capataz_api.adapters.outbound.portainer import PortainerClient
from capataz_api.domain.exceptions import ExternalServiceError


@pytest.mark.asyncio
async def test_portainer_error_mapping(monkeypatch) -> None:
    async def fake_request(self, *args, **kwargs):
        return httpx.Response(401, request=httpx.Request("GET", "https://portainer.test"))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = PortainerClient("https://portainer.test", "token")
    with pytest.raises(ExternalServiceError, match="authentication"):
        await client._request("GET", "/api/test")


@pytest.mark.asyncio
async def test_portainer_container_selection(monkeypatch) -> None:
    async def fake_request(self, *args, **kwargs):
        return httpx.Response(
            200,
            json=[
                {"Names": ["/selected"], "State": "running", "Status": "Up 2 seconds (healthy)"},
                {"Names": ["/other"], "State": "exited", "Status": "Exited"},
            ],
            request=httpx.Request("GET", "https://portainer.test"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = PortainerClient("https://portainer.test", "token")
    result = await client.container_states("1", {"containers": [{"name": "selected"}]})
    assert result == [{"name": "selected", "running": True, "healthy": True}]
