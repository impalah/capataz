"""FastAPI TestClient tests for adapters/inbound/routers/services.py.

Uses the in-memory repository double (via `client_for`) instead of a real database, so these stay
fast unit tests while exercising the real router, RBAC, and RFC 7807 error handling end to end.
"""

from __future__ import annotations

from conftest import ADMIN, NONE_ROLE, OPERATOR, VIEWER, InMemoryServiceRepository, client_for
from fakes import FakeConnectorFactory, FakeMetrics, runtime, seed_connectors


def make_service_payload(service_id: str = "open-webui") -> dict[str, object]:
    return {"id": service_id, "name": "Open WebUI", "group_name": "AI", "environment": "homelab"}


def seeded_repo() -> InMemoryServiceRepository:
    repo = InMemoryServiceRepository()
    seed_connectors(repo)
    return repo


def test_list_services_requires_viewer_role() -> None:
    client = client_for(InMemoryServiceRepository())
    response = client.get("/api/v1/services", headers=NONE_ROLE)
    assert response.status_code == 403
    body = response.json()
    assert body["title"] == "Authorization error"
    assert body["status"] == 403


def test_list_services_returns_flat_spec_fields_plus_identity() -> None:
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    assert (
        client.post("/api/v1/services", json=make_service_payload(), headers=ADMIN).status_code
        == 201
    )

    response = client.get("/api/v1/services", headers=VIEWER)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert (item["id"], item["name"], item["version"]) == ("open-webui", "Open WebUI", 1)
    assert item["runtime"] is None
    assert item["tags"] == []
    assert item["observability"]["metrics"] == []
    assert "created_at" in item


def test_create_service_requires_admin_role() -> None:
    client = client_for(InMemoryServiceRepository())
    response = client.post("/api/v1/services", json=make_service_payload(), headers=OPERATOR)
    assert response.status_code == 403


def test_create_service_rejects_duplicate_id_with_409() -> None:
    client = client_for(InMemoryServiceRepository())
    assert (
        client.post("/api/v1/services", json=make_service_payload(), headers=ADMIN).status_code
        == 201
    )
    second = client.post("/api/v1/services", json=make_service_payload(), headers=ADMIN)
    assert second.status_code == 409
    assert second.json()["title"] == "Conflict error"


def test_create_service_rejects_invalid_id_with_422_problem_detail() -> None:
    client = client_for(InMemoryServiceRepository())
    response = client.post(
        "/api/v1/services", json=make_service_payload("Not A Valid Id!"), headers=ADMIN
    )
    assert response.status_code == 422
    body = response.json()
    assert body["title"] == "Validation Error"
    assert body["errors"][0]["loc"][-1] == "id"


def test_create_service_rejects_unknown_connector_references_with_422() -> None:
    client = client_for(seeded_repo())
    payload = {**make_service_payload(), "runtime": runtime(connector="ghost")}
    response = client.post("/api/v1/services", json=payload, headers=ADMIN)
    assert response.status_code == 422
    assert "runtime.connector" in response.json()["detail"]


def test_get_service_not_found_returns_404() -> None:
    client = client_for(InMemoryServiceRepository())
    response = client.get("/api/v1/services/missing", headers=VIEWER)
    assert response.status_code == 404
    assert response.json()["title"] == "NotFound error"


def test_patch_service_accepts_a_partial_payload_as_admin() -> None:
    client = client_for(InMemoryServiceRepository())
    client.post("/api/v1/services", json=make_service_payload(), headers=ADMIN)
    response = client.patch(
        "/api/v1/services/open-webui", json={"name": "Patched Name"}, headers=ADMIN
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Patched Name"
    assert body["group_name"] == "AI"


def test_patch_service_requires_admin_role() -> None:
    client = client_for(InMemoryServiceRepository())
    response = client.patch("/api/v1/services/open-webui", json={"name": "x"}, headers=OPERATOR)
    assert response.status_code == 403


def test_delete_service_missing_returns_409_and_admin_delete_returns_204() -> None:
    client = client_for(InMemoryServiceRepository())
    assert client.delete("/api/v1/services/missing", headers=ADMIN).status_code == 409
    client.post("/api/v1/services", json=make_service_payload(), headers=ADMIN)
    ok = client.delete("/api/v1/services/open-webui", headers=ADMIN)
    assert ok.status_code == 204
    assert ok.content == b""


def test_refresh_status_requires_viewer_and_there_is_no_cached_status_endpoint() -> None:
    """refresh-status always runs the real checks, so it only needs viewer RBAC; the old cached
    GET /status is gone (2026-09-08)."""
    client = client_for(InMemoryServiceRepository())
    client.post("/api/v1/services", json=make_service_payload(), headers=ADMIN)

    forbidden = client.post("/api/v1/services/open-webui/refresh-status", headers=NONE_ROLE)
    assert forbidden.status_code == 403
    refreshed = client.post("/api/v1/services/open-webui/refresh-status", headers=VIEWER)
    assert refreshed.status_code == 200
    assert refreshed.json()["service_id"] == "open-webui"
    assert client.get("/api/v1/services/open-webui/status", headers=VIEWER).status_code == 404


def test_refresh_status_includes_metrics_when_the_service_declares_them() -> None:
    client = client_for(seeded_repo(), factory=FakeConnectorFactory(metrics=FakeMetrics(1.0)))
    payload = {
        **make_service_payload(),
        "observability": {"metrics": [{"label": "CPU", "connector": "prometheus", "query": "up"}]},
    }
    assert client.post("/api/v1/services", json=payload, headers=ADMIN).status_code == 201

    refreshed = client.post("/api/v1/services/open-webui/refresh-status", headers=VIEWER)

    assert refreshed.status_code == 200
    assert refreshed.json()["metrics"] == [{"label": "CPU", "value": 1.0}]


def test_links_endpoint_builds_dashboard_links_for_viewers() -> None:
    client = client_for(seeded_repo())
    payload = {
        **make_service_payload(),
        "observability": {"dashboards": [{"connector": "grafana", "uid": "abc123"}]},
    }
    client.post("/api/v1/services", json=payload, headers=ADMIN)
    response = client.get("/api/v1/services/open-webui/links", headers=VIEWER)
    assert response.status_code == 200
    assert response.json() == {"grafana": "https://grafana.home.arpa/d/abc123"}


def test_patch_service_with_minimal_payload_does_not_wipe_operational_fields() -> None:
    """CR-087: a PATCH carrying only the fields an edit form changed must never reset runtime/
    observability/metadata/maintenance — those fields simply weren't in the request."""
    client = client_for(seeded_repo())
    payload = {
        **make_service_payload(),
        "runtime": runtime(),
        "observability": {
            "health": {"connector": "http", "url": "https://open-webui.home.arpa/health"},
            "logs": {"connector": "loki", "query": '{compose_service="open-webui"}'},
        },
        "metadata": {"owner": "ana"},
        "maintenance": True,
    }
    created = client.post("/api/v1/services", json=payload, headers=ADMIN)
    assert created.status_code == 201

    response = client.patch(
        "/api/v1/services/open-webui",
        json={"name": "Open WebUI", "description": "Actualizado desde el Catálogo"},
        headers=ADMIN,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Actualizado desde el Catálogo"
    assert body["runtime"] == created.json()["runtime"]
    assert body["observability"] == created.json()["observability"]
    assert body["metadata"] == {"owner": "ana"}
    assert body["maintenance"] is True
