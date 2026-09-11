"""FastAPI TestClient tests for routers/actions.py and routers/executions.py."""

from __future__ import annotations

from uuid import uuid4

from conftest import ADMIN, OPERATOR, VIEWER, InMemoryServiceRepository, client_for
from fakes import make_action, make_service, runtime, seed_connectors

from capataz_api.domain.entities import Execution
from capataz_api.domain.value_objects import ExecutionSource, RiskLevel

RESTART_PAYLOAD = {
    "key": "restart",
    "label": "Restart",
    "risk_level": "operate",
    "connector": "portainer_main",
    "config": {"operation": "restart", "target": "selected_containers"},
}


def seeded_repo(service_id: str = "one") -> InMemoryServiceRepository:
    repo = InMemoryServiceRepository()
    seed_connectors(repo)
    repo.services[service_id] = make_service(service_id, runtime=runtime(names=(service_id,)))
    return repo


# --- actions.py -----------------------------------------------------------------------------


def test_list_actions_requires_viewer_and_404s_for_missing_service() -> None:
    client = client_for(InMemoryServiceRepository())
    assert client.get("/api/v1/services/missing/actions", headers=VIEWER).status_code == 404


def test_create_action_requires_admin_and_reports_its_connector() -> None:
    client = client_for(seeded_repo())
    forbidden = client.post("/api/v1/services/one/actions", json=RESTART_PAYLOAD, headers=OPERATOR)
    assert forbidden.status_code == 403

    created = client.post("/api/v1/services/one/actions", json=RESTART_PAYLOAD, headers=ADMIN)
    assert created.status_code == 201
    body = created.json()
    assert (body["key"], body["connector"], body["action_type"]) == (
        "restart",
        "portainer_main",
        "portainer",
    )


def test_create_action_with_an_unknown_connector_is_a_422() -> None:
    client = client_for(seeded_repo())
    response = client.post(
        "/api/v1/services/one/actions",
        json={**RESTART_PAYLOAD, "connector": "ghost"},
        headers=ADMIN,
    )
    assert response.status_code == 422


def test_create_action_rejects_a_free_command_field() -> None:
    client = client_for(seeded_repo())
    response = client.post(
        "/api/v1/services/one/actions",
        json={**RESTART_PAYLOAD, "config": {"command": "rm -rf /"}},
        headers=ADMIN,
    )
    assert response.status_code == 422


def test_patch_and_delete_action_as_admin() -> None:
    repo = seeded_repo()
    repo.actions[("one", "restart")] = make_action("one")
    client = client_for(repo)
    patched = client.patch(
        "/api/v1/services/one/actions/restart",
        json={**RESTART_PAYLOAD, "label": "Restart (renamed)"},
        headers=ADMIN,
    )
    assert patched.status_code == 200
    assert patched.json()["label"] == "Restart (renamed)"

    assert client.delete("/api/v1/services/one/actions/restart", headers=ADMIN).status_code == 204
    # CR-077: "doesn't exist or has active executions" is a 409, not a 404.
    assert client.delete("/api/v1/services/one/actions/restart", headers=ADMIN).status_code == 409


def test_execute_operate_action_as_operator_returns_202() -> None:
    repo = seeded_repo()
    repo.actions[("one", "restart")] = make_action("one")
    response = client_for(repo).post(
        "/api/v1/services/one/actions/restart/execute",
        json={"params": {}, "confirmation": False},
        headers=OPERATOR,
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert repo.audit_events[-1]["action"] == "execution.request"


def test_execute_critical_action_without_confirmation_is_forbidden() -> None:
    repo = seeded_repo()
    repo.actions[("one", "critical-op")] = make_action(
        "one", key="critical-op", risk_level=RiskLevel.CRITICAL
    )
    response = client_for(repo).post(
        "/api/v1/services/one/actions/critical-op/execute",
        json={"params": {}, "confirmation": False},
        headers=ADMIN,
    )
    assert response.status_code == 403
    assert response.json()["title"] == "Authorization error"


def test_execute_critical_action_with_confirmation_and_reason_succeeds_for_admin() -> None:
    repo = seeded_repo()
    repo.actions[("one", "critical-op")] = make_action(
        "one", key="critical-op", risk_level=RiskLevel.CRITICAL
    )
    response = client_for(repo).post(
        "/api/v1/services/one/actions/critical-op/execute",
        json={"params": {}, "confirmation": True, "reason": "planned maintenance"},
        headers=ADMIN,
    )
    assert response.status_code == 202


def test_execute_action_as_viewer_is_forbidden() -> None:
    repo = seeded_repo()
    repo.actions[("one", "restart")] = make_action("one")
    response = client_for(repo).post(
        "/api/v1/services/one/actions/restart/execute", json={"params": {}}, headers=VIEWER
    )
    assert response.status_code == 403


# --- executions.py --------------------------------------------------------------------------


def make_execution(service_id: str = "one") -> Execution:
    return Execution(
        service_id=service_id,
        service_id_snapshot=service_id,
        action_definition_id=make_action(service_id).id,
        action_key="restart",
        requested_by_subject="tester",
        source=ExecutionSource.UI,
        correlation_id="r1",
    )


def test_list_executions_requires_viewer() -> None:
    assert client_for(InMemoryServiceRepository()).get("/api/v1/executions").status_code == 403


def test_list_executions_happy_path_returns_page_of_execution_response() -> None:
    repo = InMemoryServiceRepository()
    execution = make_execution()
    repo.executions[execution.id] = execution
    response = client_for(repo).get(
        "/api/v1/executions",
        params={"service_id": "one", "status": "queued", "actor": "tester", "source": "ui"},
        headers=VIEWER,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(execution.id)
    assert (body["offset"], body["limit"]) == (0, 20)


def test_get_execution_happy_path_and_404() -> None:
    repo = InMemoryServiceRepository()
    execution = make_execution()
    repo.executions[execution.id] = execution
    client = client_for(repo)
    ok = client.get(f"/api/v1/executions/{execution.id}", headers=VIEWER)
    assert ok.status_code == 200
    assert ok.json()["id"] == str(execution.id)
    assert client.get(f"/api/v1/executions/{uuid4()}", headers=VIEWER).status_code == 404


def test_execution_events_requires_existing_execution() -> None:
    repo = InMemoryServiceRepository()
    execution = make_execution()
    repo.executions[execution.id] = execution
    client = client_for(repo)
    response = client.get(f"/api/v1/executions/{execution.id}/events", headers=VIEWER)
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert client.get(f"/api/v1/executions/{uuid4()}/events", headers=VIEWER).status_code == 404


def test_cancel_execution_requires_operator_and_always_conflicts() -> None:
    repo = InMemoryServiceRepository()
    execution = make_execution()
    repo.executions[execution.id] = execution
    client = client_for(repo)
    assert (
        client.post(f"/api/v1/executions/{execution.id}/cancel", headers=VIEWER).status_code == 403
    )
    assert (
        client.post(f"/api/v1/executions/{execution.id}/cancel", headers=OPERATOR).status_code
        == 409
    )
