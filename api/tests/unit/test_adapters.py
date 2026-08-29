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
    result = await client.container_states(
        "1", {"containers": [{"name": "selected", "required": True, "critical": True}]}
    )
    assert result == [
        {"name": "selected", "running": True, "healthy": True, "required": True, "critical": True}
    ]


@pytest.mark.asyncio
async def test_portainer_swarm_service_selection(monkeypatch) -> None:
    async def fake_request(self, *args, **kwargs):
        return httpx.Response(
            200,
            json=[
                {
                    "Spec": {"Name": "homelab-swarm_authentik-server"},
                    "ServiceStatus": {"RunningTasks": 1, "DesiredTasks": 1},
                },
                {
                    "Spec": {"Name": "homelab-swarm_other"},
                    "ServiceStatus": {"RunningTasks": 0, "DesiredTasks": 1},
                },
            ],
            request=httpx.Request("GET", "https://portainer.test"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = PortainerClient("https://portainer.test", "token")
    result = await client.container_states(
        "7",
        {
            "services": [{"name": "authentik-server", "required": True}],
            "stack_name": "homelab-swarm",
        },
    )
    assert result == [
        {
            "name": "homelab-swarm_authentik-server",
            "running": True,
            "healthy": True,
            "required": True,
            "critical": False,
        }
    ]


@pytest.mark.asyncio
async def test_find_link_target_resolves_a_container_id_by_name(monkeypatch) -> None:
    async def fake_request(self, *args, **kwargs):
        return httpx.Response(
            200,
            json=[
                {"Id": "aaa111", "Names": ["/selected"]},
                {"Id": "bbb222", "Names": ["/other"]},
            ],
            request=httpx.Request("GET", "https://portainer.test"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = PortainerClient("https://portainer.test", "token")
    target_id = await client.find_link_target("1", {"containers": [{"name": "selected"}]})
    assert target_id == "aaa111"


@pytest.mark.asyncio
async def test_find_link_target_resolves_a_swarm_service_id_by_stack_and_name(monkeypatch) -> None:
    async def fake_request(self, *args, **kwargs):
        return httpx.Response(
            200,
            json=[
                {"ID": "svc789", "Spec": {"Name": "authentik_authentik-server"}},
                {"ID": "svc000", "Spec": {"Name": "authentik_authentik-worker"}},
            ],
            request=httpx.Request("GET", "https://portainer.test"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = PortainerClient("https://portainer.test", "token")
    target_id = await client.find_link_target(
        "7", {"services": [{"name": "authentik-server"}], "stack_name": "authentik"}
    )
    assert target_id == "svc789"
