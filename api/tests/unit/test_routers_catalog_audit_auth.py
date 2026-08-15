"""FastAPI TestClient tests for routers/catalog.py, routers/audit.py and routers/auth.py."""

from __future__ import annotations

from conftest import ADMIN, OPERATOR, VIEWER, InMemoryServiceRepository, client_for

CATALOG_YAML = """version: 1
services:
  - id: one
    name: One
    group_name: G
    environment: dev
    actions:
      - key: restart
        label: Restart
        action_type: portainer
        risk_level: operate
        config: {operation: restart, target: selected_containers}
"""


def test_catalog_import_requires_admin_role() -> None:
    client = client_for(InMemoryServiceRepository())
    response = client.post("/api/v1/catalog/import", json={"yaml": CATALOG_YAML}, headers=OPERATOR)
    assert response.status_code == 403


def test_catalog_import_happy_path_upserts_and_audits() -> None:
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    response = client.post("/api/v1/catalog/import", json={"yaml": CATALOG_YAML}, headers=ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert (body["created"], body["updated"]) == (1, 0)
    assert "one" in repo.services
    assert repo.audit_events[-1]["action"] == "catalog.import"


def test_catalog_import_dry_run_does_not_persist() -> None:
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    response = client.post(
        "/api/v1/catalog/import",
        json={"yaml": CATALOG_YAML, "dry_run": True},
        headers=ADMIN,
    )
    assert response.status_code == 200
    assert response.json()["dry_run"] is True
    assert "one" not in repo.services


def test_catalog_import_invalid_yaml_returns_200_with_field_errors_not_a_500() -> None:
    """Invalid input is expected, everyday operator feedback, not an HTTP-level failure."""
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    invalid = CATALOG_YAML.replace("    group_name: G\n", "")  # drop a required field's whole line
    response = client.post("/api/v1/catalog/import", json={"yaml": invalid}, headers=ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert (body["created"], body["updated"]) == (0, 0)
    assert body["errors"][0]["path"] == "services.0.group_name"
    assert "one" not in repo.services


def test_catalog_export_requires_admin_and_returns_yaml_text() -> None:
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    client.post("/api/v1/catalog/import", json={"yaml": CATALOG_YAML}, headers=ADMIN)

    forbidden = client.get("/api/v1/catalog/export", headers=VIEWER)
    assert forbidden.status_code == 403

    response = client.get("/api/v1/catalog/export", headers=ADMIN)
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "id: one" in response.text


def test_audit_events_requires_admin_role() -> None:
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    forbidden = client.get("/api/v1/audit-events", headers=OPERATOR)
    assert forbidden.status_code == 403


def test_audit_events_happy_path() -> None:
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    client.post("/api/v1/catalog/import", json={"yaml": CATALOG_YAML}, headers=ADMIN)

    response = client.get("/api/v1/audit-events", headers=ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["action"] == "catalog.import"


def test_auth_me_requires_dev_user_header() -> None:
    client = client_for(InMemoryServiceRepository())
    response = client.get("/api/v1/auth/me", headers={})
    assert response.status_code == 403


def test_auth_me_returns_principal_shape() -> None:
    client = client_for(InMemoryServiceRepository())
    response = client.get("/api/v1/auth/me", headers=ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "tester"
    assert body["groups"] == ["capataz-admin"]
