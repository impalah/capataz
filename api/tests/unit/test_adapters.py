import httpx
import pytest

from capataz_api.adapters.outbound.portainer import PortainerClient
from capataz_api.adapters.outbound.prometheus import PrometheusMetricsProvider
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


def _vector(*values: float) -> dict[str, object]:
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": {}, "value": [1700000000, str(v)]} for v in values],
        },
    }


@pytest.mark.asyncio
async def test_prometheus_query_passes_each_definitions_query_verbatim(monkeypatch) -> None:
    async def fake_request(self, method, url, **kwargs):
        query = kwargs["params"]["query"]
        value = 12.5 if query == "cpu_query" else 512.0
        return httpx.Response(200, json=_vector(value), request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    provider = PrometheusMetricsProvider("https://prometheus.test", None, 5)
    definitions = [
        {"label": "CPU", "type": "prometheus", "query": "cpu_query"},
        {"label": "Memoria", "type": "prometheus", "query": "mem_query"},
    ]

    result = await provider.query(definitions)

    assert result == [
        {"label": "CPU", "value": 12.5},
        {"label": "Memoria", "value": 512.0},
    ]


@pytest.mark.asyncio
async def test_prometheus_query_sums_multiple_series_when_not_fully_aggregated(monkeypatch) -> None:
    async def fake_request(self, method, url, **kwargs):
        return httpx.Response(200, json=_vector(1.0, 2.5), request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    provider = PrometheusMetricsProvider("https://prometheus.test", None, 5)

    result = await provider.query([{"label": "CPU", "type": "prometheus", "query": "q"}])

    assert result == [{"label": "CPU", "value": 3.5}]


@pytest.mark.asyncio
async def test_prometheus_query_returns_none_for_a_query_with_no_data(monkeypatch) -> None:
    async def fake_request(self, method, url, **kwargs):
        return httpx.Response(200, json=_vector(), request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    provider = PrometheusMetricsProvider("https://prometheus.test", None, 5)

    result = await provider.query([{"label": "CPU", "type": "prometheus", "query": "q"}])

    assert result == [{"label": "CPU", "value": None}]


@pytest.mark.asyncio
async def test_prometheus_query_returns_none_on_http_error(monkeypatch) -> None:
    async def fake_request(self, method, url, **kwargs):
        raise httpx.ConnectError("boom", request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    provider = PrometheusMetricsProvider("https://prometheus.test", None, 5)

    result = await provider.query([{"label": "CPU", "type": "prometheus", "query": "q"}])

    assert result == [{"label": "CPU", "value": None}]


@pytest.mark.asyncio
async def test_prometheus_query_returns_none_on_non_success_status(monkeypatch) -> None:
    async def fake_request(self, method, url, **kwargs):
        body = {"status": "error", "error": "bad query"}
        return httpx.Response(200, json=body, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    provider = PrometheusMetricsProvider("https://prometheus.test", None, 5)

    result = await provider.query([{"label": "CPU", "type": "prometheus", "query": "q"}])

    assert result == [{"label": "CPU", "value": None}]


@pytest.mark.asyncio
async def test_prometheus_query_returns_none_on_unexpected_response_shape(monkeypatch) -> None:
    async def fake_request(self, method, url, **kwargs):
        # "success" without the expected data.result structure.
        return httpx.Response(200, json={"status": "success"}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    provider = PrometheusMetricsProvider("https://prometheus.test", None, 5)

    result = await provider.query([{"label": "CPU", "type": "prometheus", "query": "q"}])

    assert result == [{"label": "CPU", "value": None}]


@pytest.mark.asyncio
async def test_prometheus_query_sends_bearer_token_only_when_configured(monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    async def fake_request(self, method, url, **kwargs):
        captured["authorization"] = self.headers.get("authorization")
        return httpx.Response(200, json=_vector(1.0), request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    provider = PrometheusMetricsProvider("https://prometheus.test", "secret-token", 5)

    await provider.query([{"label": "CPU", "type": "prometheus", "query": "q"}])

    assert captured["authorization"] == "Bearer secret-token"


@pytest.mark.asyncio
async def test_prometheus_query_with_no_definitions_returns_an_empty_list() -> None:
    provider = PrometheusMetricsProvider("https://prometheus.test", None, 5)
    assert await provider.query([]) == []
