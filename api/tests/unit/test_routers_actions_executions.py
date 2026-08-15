"""FastAPI TestClient tests for routers/actions.py and routers/executions.py."""

from __future__ import annotations

from conftest import ADMIN, OPERATOR, VIEWER, InMemoryServiceRepository, client_for

from capataz_api.domain.entities import ActionDefinition, Execution
from capataz_api.domain.value_objects import ActionType, ExecutionSource, RiskLevel


def seed_service(repo: InMemoryServiceRepository, service_id: str = "one") -> None:
    from capataz_api.domain.entities import Service

    repo.services[service_id] = Service(
        id=service_id,
        name="One",
        group_name="G",
        environment="dev",
        container_selectors={"containers": [{"name": service_id}]},
    )


def make_action(
    service_id: str = "one", key: str = "restart", risk: RiskLevel = RiskLevel.OPERATE
) -> ActionDefinition:
    return ActionDefinition(
        service_id=service_id,
        key=key,
        label="Restart",
        action_type=ActionType.PORTAINER,
        risk_level=risk,
        config={"operation": "restart", "target": "selected_containers"},
    )


# --- actions.py -----------------------------------------------------------------


def test_list_actions_requires_viewer_and_404s_for_missing_service() -> None:
    repo = InMemoryServiceRepository()
    client = client_for(repo)
    response = client.get("/api/v1/services/missing/actions", headers=VIEWER)
    assert response.status_code == 404


def test_create_action_requires_admin_role() -> None:
    repo = InMemoryServiceRepository()
    seed_service(repo)
    client = client_for(repo)
    payload = {
        "key": "restart",
        "label": "Restart",
        "action_type": "portainer",
        "risk_level": "operate",
        "config": {"operation": "restart", "target": "selected_containers"},
    }
    forbidden = client.post("/api/v1/services/one/actions", json=payload, headers=OPERATOR)
    assert forbidden.status_code == 403

    created = client.post("/api/v1/services/one/actions", json=payload, headers=ADMIN)
    assert created.status_code == 201
    assert created.json()["key"] == "restart"


def test_patch_and_delete_action_as_admin() -> None:
    repo = InMemoryServiceRepository()
    seed_service(repo)
    repo.actions[("one", "restart")] = make_action()
    client = client_for(repo)
    payload = {
        "key": "restart",
        "label": "Restart (renamed)",
        "action_type": "portainer",
        "risk_level": "operate",
        "config": {"operation": "restart", "target": "selected_containers"},
    }
    patched = client.patch("/api/v1/services/one/actions/restart", json=payload, headers=ADMIN)
    assert patched.status_code == 200
    assert patched.json()["label"] == "Restart (renamed)"

    deleted = client.delete("/api/v1/services/one/actions/restart", headers=ADMIN)
    assert deleted.status_code == 204
    # CR-077: matches delete_service's wording — "doesn't exist or has active executions" is a
    # 409, not a 404, since the same bool covers both causes.
    missing = client.delete("/api/v1/services/one/actions/restart", headers=ADMIN)
    assert missing.status_code == 409


def test_execute_operate_action_as_operator_returns_202() -> None:
    repo = InMemoryServiceRepository()
    seed_service(repo)
    repo.actions[("one", "restart")] = make_action()
    client = client_for(repo)
    response = client.post(
        "/api/v1/services/one/actions/restart/execute",
        json={"params": {}, "confirmation": False},
        headers=OPERATOR,
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert repo.audit_events[-1]["action"] == "execution.request"


def test_execute_critical_action_without_confirmation_is_forbidden() -> None:
    repo = InMemoryServiceRepository()
    seed_service(repo)
    repo.actions[("one", "critical-op")] = make_action(key="critical-op", risk=RiskLevel.CRITICAL)
    client = client_for(repo)
    response = client.post(
        "/api/v1/services/one/actions/critical-op/execute",
        json={"params": {}, "confirmation": False},
        headers=ADMIN,
    )
    assert response.status_code == 403
    assert response.json()["title"] == "Authorization error"


def test_execute_critical_action_with_confirmation_and_reason_succeeds_for_admin() -> None:
    repo = InMemoryServiceRepository()
    seed_service(repo)
    repo.actions[("one", "critical-op")] = make_action(key="critical-op", risk=RiskLevel.CRITICAL)
    client = client_for(repo)
    response = client.post(
        "/api/v1/services/one/actions/critical-op/execute",
        json={"params": {}, "confirmation": True, "reason": "planned maintenance"},
        headers=ADMIN,
    )
    assert response.status_code == 202


def test_execute_action_as_viewer_is_forbidden() -> None:
    repo = InMemoryServiceRepository()
    seed_service(repo)
    repo.actions[("one", "restart")] = make_action()
    client = client_for(repo)
    response = client.post(
        "/api/v1/services/one/actions/restart/execute",
        json={"params": {}},
        headers=VIEWER,
    )
    assert response.status_code == 403


# --- executions.py ----------------------------------------------------------------


def make_execution(service_id: str = "one") -> Execution:
    return Execution(
        service_id=service_id,
        service_id_snapshot=service_id,
        action_definition_id=make_action().id,
        action_key="restart",
        requested_by_subject="tester",
        source=ExecutionSource.UI,
        correlation_id="r1",
    )


def test_list_executions_requires_viewer() -> None:
    client = client_for(InMemoryServiceRepository())
    response = client.get("/api/v1/executions", headers={})
    assert response.status_code == 403


def test_list_executions_happy_path_returns_page_of_execution_response() -> None:
    repo = InMemoryServiceRepository()
    execution = make_execution()
    repo.executions[execution.id] = execution
    client = client_for(repo)

    response = client.get(
        "/api/v1/executions",
        params={"service_id": "one", "status": "queued", "actor": "tester", "source": "ui"},
        headers=VIEWER,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(execution.id)
    assert body["offset"] == 0
    assert body["limit"] == 20


def test_get_execution_happy_path_and_404() -> None:
    repo = InMemoryServiceRepository()
    execution = make_execution()
    repo.executions[execution.id] = execution
    client = client_for(repo)

    ok = client.get(f"/api/v1/executions/{execution.id}", headers=VIEWER)
    assert ok.status_code == 200
    assert ok.json()["id"] == str(execution.id)

    from uuid import uuid4

    missing = client.get(f"/api/v1/executions/{uuid4()}", headers=VIEWER)
    assert missing.status_code == 404


def test_execution_events_requires_existing_execution() -> None:
    repo = InMemoryServiceRepository()
    execution = make_execution()
    repo.executions[execution.id] = execution
    client = client_for(repo)

    response = client.get(f"/api/v1/executions/{execution.id}/events", headers=VIEWER)
    assert response.status_code == 200
    assert isinstance(response.json(), list)

    from uuid import uuid4

    missing = client.get(f"/api/v1/executions/{uuid4()}/events", headers=VIEWER)
    assert missing.status_code == 404


def test_cancel_execution_requires_operator_and_always_conflicts() -> None:
    repo = InMemoryServiceRepository()
    execution = make_execution()
    repo.executions[execution.id] = execution
    client = client_for(repo)

    forbidden = client.post(f"/api/v1/executions/{execution.id}/cancel", headers=VIEWER)
    assert forbidden.status_code == 403

    response = client.post(f"/api/v1/executions/{execution.id}/cancel", headers=OPERATOR)
    assert response.status_code == 409
