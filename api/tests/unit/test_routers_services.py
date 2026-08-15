"""FastAPI TestClient tests for adapters/inbound/routers/services.py.

Uses the InMemoryServiceRepository double from conftest.py (via `client_for`)
instead of a real database, so these stay fast unit tests while exercising the
real router, RBAC, and RFC 7807 error handling end to end.
"""

from __future__ import annotations

from conftest import ADMIN, NONE_ROLE, OPERATOR, VIEWER, InMemoryServiceRepository, client_for


def make_service_payload(service_id: str = "open-webui") -> dict[str, object]:
    return {
        "id": service_id,
        "name": "Open WebUI",
        "group_name": "AI",
        "environment": "homelab",
    }


def test_list_services_requires_viewer_role() -> None:
    client = client_for(InMemoryServiceRepository())
    response = client.get("/api/v1/services", headers=NONE_ROLE)
    assert response.status_code == 403
    body = response.json()
    assert body["title"] == "Authorization error"
    assert body["status"] == 403


def test_list_services_happy_path_returns_page_of_service_response() -> None:
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    create = client.post("/api/v1/services", json=make_service_payload(), headers=ADMIN)
    assert create.status_code == 201

    response = client.get("/api/v1/services", headers=VIEWER)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "open-webui"
    assert body["items"][0]["version"] == 1
    assert "created_at" in body["items"][0]


def test_create_service_requires_admin_role() -> None:
    client = client_for(InMemoryServiceRepository())
    response = client.post("/api/v1/services", json=make_service_payload(), headers=OPERATOR)
    assert response.status_code == 403


def test_create_service_rejects_duplicate_id_with_409() -> None:
    client = client_for(InMemoryServiceRepository())
    first = client.post("/api/v1/services", json=make_service_payload(), headers=ADMIN)
    assert first.status_code == 201
    second = client.post("/api/v1/services", json=make_service_payload(), headers=ADMIN)
    assert second.status_code == 409
    assert second.json()["title"] == "Conflict error"


def test_create_service_rejects_invalid_id_with_422_problem_detail() -> None:
    client = client_for(InMemoryServiceRepository())
    payload = make_service_payload("Not A Valid Id!")
    response = client.post("/api/v1/services", json=payload, headers=ADMIN)
    assert response.status_code == 422
    body = response.json()
    assert body["title"] == "Validation Error"
    assert body["errors"]
    assert body["errors"][0]["loc"][-1] == "id"


def test_get_service_not_found_returns_404() -> None:
    client = client_for(InMemoryServiceRepository())
    response = client.get("/api/v1/services/missing", headers=VIEWER)
    assert response.status_code == 404
    assert response.json()["title"] == "NotFound error"


def test_patch_service_merges_fields_as_admin() -> None:
    # ServicePatch inherits every ServiceInput field as still-required (only `id` and
    # `expected_version` are optional), so a PATCH payload must carry the full representation —
    # there is no partial-field shorthand at the schema level.
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    client.post("/api/v1/services", json=make_service_payload(), headers=ADMIN)
    payload = make_service_payload()
    payload["name"] = "Patched Name"
    response = client.patch("/api/v1/services/open-webui", json=payload, headers=ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Patched Name"
    assert body["group_name"] == "AI"


def test_patch_service_requires_admin_role() -> None:
    client = client_for(InMemoryServiceRepository())
    response = client.patch(
        "/api/v1/services/open-webui", json=make_service_payload(), headers=OPERATOR
    )
    assert response.status_code == 403


def test_delete_service_missing_returns_409_and_admin_delete_returns_204() -> None:
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    missing = client.delete("/api/v1/services/missing", headers=ADMIN)
    assert missing.status_code == 409

    client.post("/api/v1/services", json=make_service_payload(), headers=ADMIN)
    ok = client.delete("/api/v1/services/open-webui", headers=ADMIN)
    assert ok.status_code == 204
    assert ok.content == b""


def test_refresh_status_requires_operator_and_get_status_requires_viewer() -> None:
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    client.post("/api/v1/services", json=make_service_payload(), headers=ADMIN)

    forbidden = client.post("/api/v1/services/open-webui/refresh-status", headers=VIEWER)
    assert forbidden.status_code == 403

    refreshed = client.post("/api/v1/services/open-webui/refresh-status", headers=OPERATOR)
    assert refreshed.status_code == 200
    assert refreshed.json()["service_id"] == "open-webui"

    status = client.get("/api/v1/services/open-webui/status", headers=VIEWER)
    assert status.status_code == 200


def test_links_endpoint_returns_dict_for_viewer() -> None:
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    client.post("/api/v1/services", json=make_service_payload(), headers=ADMIN)
    response = client.get("/api/v1/services/open-webui/links", headers=VIEWER)
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_patch_service_with_minimal_payload_does_not_wipe_operational_fields() -> None:
    """CR-087: a PATCH that only carries the fields CatalogPage.vue's edit form actually sends

    (name/group_name/environment/description) must never reset container_selectors/health_config/
    grafana_config/loki_config/metadata/maintenance to their empty defaults — those fields simply
    weren't in the request. Regression test for the exclude_unset fix in
    adapters/inbound/routers/services.py::patch_service.
    """
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    payload = make_service_payload()
    payload["container_selectors"] = {"containers": [{"name": "open-webui", "required": True}]}
    payload["health_config"] = {"type": "http", "url": "https://open-webui.home.arpa/health"}
    payload["grafana_config"] = {"dashboard_uid": "abc123"}
    payload["loki_config"] = {"query": '{compose_service="open-webui"}'}
    payload["metadata"] = {"owner": "ana"}
    payload["maintenance"] = True
    created = client.post("/api/v1/services", json=payload, headers=ADMIN)
    assert created.status_code == 201

    minimal_edit = {
        "name": "Open WebUI",
        "group_name": "AI",
        "environment": "homelab",
        "description": "Actualizado desde el Catálogo",
    }
    response = client.patch("/api/v1/services/open-webui", json=minimal_edit, headers=ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Actualizado desde el Catálogo"
    assert body["container_selectors"] == payload["container_selectors"]
    assert body["health_config"] == payload["health_config"]
    assert body["grafana_config"] == payload["grafana_config"]
    assert body["loki_config"] == payload["loki_config"]
    assert body["metadata"] == payload["metadata"]
    assert body["maintenance"] is True
