"""FastAPI TestClient tests for routers/catalog.py, routers/audit.py and routers/auth.py."""

from __future__ import annotations

import base64

from conftest import ADMIN, OPERATOR, VIEWER, InMemoryServiceRepository, client_for

INLINE_SECRET = b"pt-inline-secret-value"
CATALOG_YAML = f"""version: 2
resources:
  - id: portainer_token
    type: secret
    source: {{base64: {base64.b64encode(INLINE_SECRET).decode()}}}
connectors:
  - id: portainer_main
    type: portainer
    config: {{url: "https://portainer.home.arpa", token: portainer_token}}
services:
  - id: one
    name: One
    group_name: G
    environment: dev
    runtime: {{connector: portainer_main, environment_id: 7, containers: [{{name: one}}]}}
    actions:
      - key: restart
        label: Restart
        risk_level: operate
        connector: portainer_main
        config: {{operation: restart, target: selected_containers}}
"""


def test_catalog_import_requires_admin_role() -> None:
    client = client_for(InMemoryServiceRepository())
    response = client.post("/api/v1/catalog/import", json={"yaml": CATALOG_YAML}, headers=OPERATOR)
    assert response.status_code == 403


def test_catalog_import_happy_path_upserts_everything_warns_about_inline_and_audits() -> None:
    repo = InMemoryServiceRepository()
    response = client_for(repo).post(
        "/api/v1/catalog/import", json={"yaml": CATALOG_YAML}, headers=ADMIN
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert (body["created"], body["updated"]) == (1, 0)
    assert body["counts"]["connectors"]["created"] == 1
    assert body["counts"]["resources"]["created"] == 1
    assert body["warnings"][0]["path"] == "resources.0.source"
    assert "one" in repo.services and "portainer_main" in repo.connectors
    assert INLINE_SECRET not in repo.resources["portainer_token"].ciphertext
    assert repo.audit_events[-1]["action"] == "catalog.import"


def test_catalog_import_dry_run_does_not_persist() -> None:
    repo = InMemoryServiceRepository()
    response = client_for(repo).post(
        "/api/v1/catalog/import", json={"yaml": CATALOG_YAML, "dry_run": True}, headers=ADMIN
    )
    assert response.status_code == 200
    assert response.json()["dry_run"] is True
    assert (repo.services, repo.connectors, repo.resources) == ({}, {}, {})


def test_catalog_import_invalid_yaml_returns_200_with_field_errors_not_a_500() -> None:
    """Invalid input is expected, everyday operator feedback, not an HTTP-level failure."""
    repo = InMemoryServiceRepository()
    invalid = CATALOG_YAML.replace("    group_name: G\n", "")
    response = client_for(repo).post(
        "/api/v1/catalog/import", json={"yaml": invalid}, headers=ADMIN
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert (body["created"], body["updated"]) == (0, 0)
    assert body["errors"][0]["path"] == "services.0.group_name"
    assert "one" not in repo.services


def test_catalog_import_with_a_broken_reference_persists_nothing() -> None:
    repo = InMemoryServiceRepository()
    invalid = CATALOG_YAML.replace(
        "connector: portainer_main, environment_id", "connector: ghost, environment_id"
    )
    body = (
        client_for(repo)
        .post("/api/v1/catalog/import", json={"yaml": invalid}, headers=ADMIN)
        .json()
    )
    assert body["valid"] is False
    assert body["errors"][0]["path"] == "services.0.runtime.connector"
    assert (repo.services, repo.connectors, repo.resources) == ({}, {}, {})


def test_catalog_export_requires_admin_and_never_contains_resource_content() -> None:
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    client.post("/api/v1/catalog/import", json={"yaml": CATALOG_YAML}, headers=ADMIN)

    assert client.get("/api/v1/catalog/export", headers=VIEWER).status_code == 403
    response = client.get("/api/v1/catalog/export", headers=ADMIN)
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "id: one" in response.text
    assert "version: 2" in response.text
    assert INLINE_SECRET.decode() not in response.text
    assert base64.b64encode(INLINE_SECRET).decode() not in response.text


def test_audit_events_requires_admin_role() -> None:
    client = client_for(InMemoryServiceRepository())
    assert client.get("/api/v1/audit-events", headers=OPERATOR).status_code == 403


def test_audit_events_happy_path() -> None:
    client = client_for(InMemoryServiceRepository())
    client.post("/api/v1/catalog/import", json={"yaml": CATALOG_YAML}, headers=ADMIN)
    response = client.get("/api/v1/audit-events", headers=ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["action"] == "catalog.import"


def test_auth_me_requires_dev_user_header() -> None:
    client = client_for(InMemoryServiceRepository())
    assert client.get("/api/v1/auth/me", headers={}).status_code == 403


def test_auth_me_returns_principal_shape() -> None:
    response = client_for(InMemoryServiceRepository()).get("/api/v1/auth/me", headers=ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "tester"
    assert body["groups"] == ["capataz-admin"]
