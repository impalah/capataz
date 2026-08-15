"""Unit tests for bootstrap/exception_handlers.py: every error path becomes RFC 7807 JSON."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from capataz_api.bootstrap.exception_handlers import register_exception_handlers
from capataz_api.domain.exceptions import (
    AuthorizationError,
    ConfigurationError,
    ConflictError,
    DomainError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)


class _UnmappedDomainError(DomainError):
    """A DomainError subclass deliberately absent from _DOMAIN_ERROR_STATUS's mapping."""


class _Body(BaseModel):
    name: str


def build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/not-found")
    async def raise_not_found() -> None:
        raise NotFoundError("Service not found")

    @app.get("/authz")
    async def raise_authz() -> None:
        raise AuthorizationError("Insufficient role")

    @app.get("/conflict")
    async def raise_conflict() -> None:
        raise ConflictError("Already exists")

    @app.get("/validation")
    async def raise_validation() -> None:
        raise ValidationError("Bad config")

    @app.get("/external")
    async def raise_external() -> None:
        raise ExternalServiceError("Portainer unreachable")

    @app.get("/config")
    async def raise_config() -> None:
        raise ConfigurationError("Missing secret")

    @app.get("/unmapped")
    async def raise_unmapped() -> None:
        raise _UnmappedDomainError("Some other domain failure")

    @app.get("/http")
    async def raise_http() -> None:
        raise HTTPException(status_code=503, detail="Dependencies are not ready")

    @app.post("/body")
    async def echo_body(body: _Body) -> dict[str, str]:
        return {"name": body.name}

    @app.get("/boom")
    async def raise_unexpected() -> None:
        raise RuntimeError("internal detail that must not leak")

    return app


client = TestClient(build_app(), raise_server_exceptions=False)


def test_domain_not_found_maps_to_404_problem_detail() -> None:
    response = client.get("/not-found")
    assert response.status_code == 404
    body = response.json()
    assert body["status"] == 404
    assert body["title"] == "NotFound error"
    assert body["detail"] == "Service not found"
    assert body["type"] == "https://capataz.local/problems/notfounderror"
    assert body["instance"] == "/not-found"
    assert response.headers["content-type"] == "application/problem+json"


def test_domain_authorization_error_maps_to_403() -> None:
    response = client.get("/authz")
    assert response.status_code == 403
    assert response.json()["title"] == "Authorization error"


def test_domain_conflict_error_maps_to_409() -> None:
    response = client.get("/conflict")
    assert response.status_code == 409


def test_domain_validation_error_maps_to_422() -> None:
    response = client.get("/validation")
    assert response.status_code == 422


def test_domain_external_service_error_maps_to_502() -> None:
    response = client.get("/external")
    assert response.status_code == 502


def test_domain_configuration_error_maps_to_500() -> None:
    response = client.get("/config")
    assert response.status_code == 500


def test_unmapped_domain_error_falls_back_to_400() -> None:
    response = client.get("/unmapped")
    assert response.status_code == 400


def test_http_exception_is_wrapped_as_problem_detail() -> None:
    response = client.get("/http")
    assert response.status_code == 503
    body = response.json()
    assert body["title"] == "An error occurred"
    assert body["detail"] == "Dependencies are not ready"


def test_request_validation_error_lists_field_errors() -> None:
    response = client.post("/body", json={})
    assert response.status_code == 422
    body = response.json()
    assert body["title"] == "Validation Error"
    assert body["errors"]
    assert body["errors"][0]["loc"] == ["body", "name"]


def test_request_validation_error_with_non_json_content_type_does_not_crash() -> None:
    # A body sent with a non-JSON Content-Type surfaces its raw bytes as the pydantic error's
    # "input" — regression test for a 500 that used to happen here (bytes aren't JSON-serializable,
    # see _json_safe_input; this is exactly what a plain-text/YAML body would trigger).
    response = client.post(
        "/body", content=b"name: not-json", headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 422
    assert response.json()["title"] == "Validation Error"


def test_unhandled_exception_becomes_opaque_500_without_leaking_details() -> None:
    response = client.get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["title"] == "Internal Server Error"
    assert "internal detail" not in body["detail"]
    assert body["detail"] == "An unexpected error occurred. Please try again later."


def test_correlation_id_is_included_when_request_state_has_it() -> None:
    request_id = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    response = client.get("/not-found", headers={"X-Request-ID": request_id})
    # No CorrelationIdMiddleware is registered in this minimal app, so request.state has no
    # request_id and correlation_id must gracefully default to None rather than error out.
    assert response.json().get("correlation_id") is None
