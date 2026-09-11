"""FastAPI TestClient tests for routers/connectors.py and routers/resources.py."""

from __future__ import annotations

import base64

from conftest import ADMIN, OPERATOR, VIEWER, InMemoryServiceRepository, client_for
from fakes import make_service, portainer_connector, runtime

SECRET = b"portainer-api-token"
RESOURCE = {
    "id": "portainer_token",
    "type": "secret",
    "content_base64": base64.b64encode(SECRET).decode(),
}
PORTAINER = {
    "id": "portainer_main",
    "type": "portainer",
    "config": {"url": "https://portainer.home.arpa", "token": "portainer_token"},
}


def test_connector_and_resource_endpoints_are_admin_only() -> None:
    client = client_for(InMemoryServiceRepository())
    for path in ("/api/v1/connectors", "/api/v1/resources"):
        assert client.get(path, headers=VIEWER).status_code == 403
        assert client.get(path, headers=OPERATOR).status_code == 403
        assert client.get(path, headers=ADMIN).status_code == 200


def test_upload_a_resource_then_create_a_connector_that_uses_it() -> None:
    repo = InMemoryServiceRepository()
    client = client_for(repo)

    uploaded = client.post("/api/v1/resources", json=RESOURCE, headers=ADMIN)
    assert uploaded.status_code == 201
    body = uploaded.json()
    assert (body["id"], body["type"], body["size"]) == ("portainer_token", "secret", len(SECRET))
    assert len(body["fingerprint"]) == 12
    assert "content" not in str(body).replace("content_base64", "")  # metadata only

    created = client.post("/api/v1/connectors", json=PORTAINER, headers=ADMIN)
    assert created.status_code == 201
    connector = created.json()
    assert connector["capabilities"] == ["actions", "status"]
    assert connector["config"]["token"] == "portainer_token"

    listed = client.get("/api/v1/resources", headers=ADMIN).text
    assert SECRET.decode() not in listed
    assert RESOURCE["content_base64"] not in listed


def test_invalid_payloads_are_422s() -> None:
    client = client_for(InMemoryServiceRepository())
    bad_base64 = {**RESOURCE, "content_base64": "***"}
    assert client.post("/api/v1/resources", json=bad_base64, headers=ADMIN).status_code == 422
    unknown_type = {"id": "x", "type": "kubernetes", "config": {}}
    assert client.post("/api/v1/connectors", json=unknown_type, headers=ADMIN).status_code == 422
    # References a resource that doesn't exist.
    assert client.post("/api/v1/connectors", json=PORTAINER, headers=ADMIN).status_code == 422


def test_update_connector_and_replace_resource_content() -> None:
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    client.post("/api/v1/resources", json=RESOURCE, headers=ADMIN)
    client.post("/api/v1/connectors", json=PORTAINER, headers=ADMIN)

    updated = client.put(
        "/api/v1/connectors/portainer_main?expected_version=1",
        json={**PORTAINER, "description": "Main"},
        headers=ADMIN,
    )
    assert updated.status_code == 200
    assert (updated.json()["description"], updated.json()["version"]) == ("Main", 2)
    changed_type = {
        "id": "portainer_main",
        "type": "grafana",
        "config": {"url": "https://g.home.arpa"},
    }
    assert (
        client.put(
            "/api/v1/connectors/portainer_main", json=changed_type, headers=ADMIN
        ).status_code
        == 409
    )

    replaced = client.put(
        "/api/v1/resources/portainer_token/content",
        json={"content_base64": base64.b64encode(b"rotated").decode()},
        headers=ADMIN,
    )
    assert replaced.status_code == 200
    assert replaced.json()["version"] == 2


def test_deleting_something_still_in_use_is_a_409() -> None:
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    client.post("/api/v1/resources", json=RESOURCE, headers=ADMIN)
    repo.connectors["portainer_main"] = portainer_connector()
    repo.services["one"] = make_service("one", runtime=runtime(names=("one",)))

    assert client.delete("/api/v1/resources/portainer_token", headers=ADMIN).status_code == 409
    assert client.delete("/api/v1/connectors/portainer_main", headers=ADMIN).status_code == 409

    del repo.services["one"]
    assert client.delete("/api/v1/connectors/portainer_main", headers=ADMIN).status_code == 204
    assert client.delete("/api/v1/resources/portainer_token", headers=ADMIN).status_code == 204
    assert client.get("/api/v1/resources/portainer_token", headers=ADMIN).status_code == 404
