"""Application-layer tests for connector and resource CRUD (connector.py, resource.py)."""

from __future__ import annotations

from typing import Any

import pytest
from fakes import (
    TEST_SUFFIXES,
    InMemoryServiceRepository,
    make_action,
    make_cipher,
    make_resource,
    make_service,
    portainer_connector,
    runtime,
)

from capataz_api.application.services import (
    ConnectorApplicationService,
    ResourceApplicationService,
)
from capataz_api.domain.entities import Principal
from capataz_api.domain.exceptions import ConflictError, NotFoundError, ValidationError
from capataz_api.domain.specs import MAX_RESOURCE_BYTES, PortainerConnector
from capataz_api.domain.value_objects import ResourceType

ADMIN = Principal("admin", {"capataz-admin"})
PORTAINER: dict[str, Any] = {
    "id": "portainer_main",
    "type": "portainer",
    "config": {"url": "https://portainer.home.arpa", "token": "portainer_token"},
}


def repo_with_token() -> InMemoryServiceRepository:
    repo = InMemoryServiceRepository()
    repo.resources["portainer_token"] = make_resource("portainer_token")
    return repo


def connectors(repo: InMemoryServiceRepository) -> ConnectorApplicationService:
    return ConnectorApplicationService(repo, TEST_SUFFIXES)


def resources(repo: InMemoryServiceRepository) -> ResourceApplicationService:
    return ResourceApplicationService(repo, make_cipher())


# --- connectors -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_connector_validates_resources_and_audits() -> None:
    repo = repo_with_token()
    created = await connectors(repo).create_connector(
        data=PORTAINER, principal=ADMIN, request_id="r"
    )
    assert isinstance(created.spec, PortainerConnector)
    assert repo.audit_events[-1]["action"] == "connector.create"
    with pytest.raises(ConflictError):
        await connectors(repo).create_connector(data=PORTAINER, principal=ADMIN, request_id="r")


@pytest.mark.asyncio
async def test_create_connector_rejects_bad_references_urls_and_shapes() -> None:
    service = connectors(InMemoryServiceRepository())
    with pytest.raises(ValidationError) as missing:
        await service.create_connector(data=PORTAINER, principal=ADMIN, request_id="r")
    assert missing.value.field_errors[0].path == "config.token"

    repo = repo_with_token()
    evil = {**PORTAINER, "config": {**PORTAINER["config"], "url": "https://portainer.evil.example"}}
    with pytest.raises(ValidationError, match="config.url"):
        await connectors(repo).create_connector(data=evil, principal=ADMIN, request_id="r")

    with pytest.raises(ValidationError, match="Invalid connector"):
        await connectors(repo).create_connector(
            data={"id": "x", "type": "kubernetes", "config": {}}, principal=ADMIN, request_id="r"
        )


@pytest.mark.asyncio
async def test_update_connector_keeps_id_and_type_immutable_and_supports_cas() -> None:
    repo = repo_with_token()
    service = connectors(repo)
    await service.create_connector(data=PORTAINER, principal=ADMIN, request_id="r")

    renamed = {**PORTAINER, "description": "Main Portainer"}
    updated = await service.update_connector(
        "portainer_main", data=renamed, principal=ADMIN, request_id="r", expected_version=1
    )
    assert (updated.spec.description, updated.version) == ("Main Portainer", 2)

    with pytest.raises(ConflictError, match="version|modified"):
        await service.update_connector(
            "portainer_main", data=renamed, principal=ADMIN, request_id="r", expected_version=1
        )
    with pytest.raises(ConflictError, match="type is immutable"):
        await service.update_connector(
            "portainer_main",
            data={"type": "grafana", "config": {"url": "https://grafana.home.arpa"}},
            principal=ADMIN,
            request_id="r",
        )
    with pytest.raises(ConflictError, match="id is immutable"):
        await service.update_connector(
            "portainer_main", data={**PORTAINER, "id": "other"}, principal=ADMIN, request_id="r"
        )
    with pytest.raises(NotFoundError):
        await service.update_connector("ghost", data=PORTAINER, principal=ADMIN, request_id="r")


@pytest.mark.asyncio
async def test_a_connector_in_use_cannot_be_deleted() -> None:
    repo = repo_with_token()
    repo.connectors["portainer_main"] = portainer_connector()
    repo.services["one"] = make_service("one", runtime=runtime(names=("one",)))
    with pytest.raises(ConflictError, match="service one \\(runtime.connector\\)"):
        await connectors(repo).delete_connector("portainer_main", principal=ADMIN, request_id="r")

    del repo.services["one"]
    repo.actions[("two", "restart")] = make_action("two")
    with pytest.raises(ConflictError, match="action two/restart"):
        await connectors(repo).delete_connector("portainer_main", principal=ADMIN, request_id="r")

    repo.actions.clear()
    await connectors(repo).delete_connector("portainer_main", principal=ADMIN, request_id="r")
    assert repo.connectors == {}
    assert repo.audit_events[-1]["action"] == "connector.delete"


# --- resources ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_resource_encrypts_and_never_audits_the_content() -> None:
    repo = InMemoryServiceRepository()
    created = await resources(repo).create_resource(
        resource_id="ssh_mole_key",
        resource_type="ssh_private_key",
        description="Deploy key",
        content=b"-----BEGIN KEY-----\nsecret\n",
        principal=ADMIN,
        request_id="r",
    )
    stored = repo.resources["ssh_mole_key"]
    assert created.type is ResourceType.SSH_PRIVATE_KEY
    assert b"secret" not in stored.ciphertext
    assert make_cipher().decrypt(stored.ciphertext) == b"-----BEGIN KEY-----\nsecret\n"
    assert (stored.size, stored.source) == (27, {"upload": True})
    audit = repo.audit_events[-1]
    assert audit["action"] == "resource.create"
    assert "secret" not in str(audit)


@pytest.mark.asyncio
async def test_create_resource_rejects_duplicates_bad_ids_and_bad_content() -> None:
    repo = InMemoryServiceRepository()
    service = resources(repo)

    async def create(resource_id: str = "k", content: bytes = b"x", **kw: Any) -> None:
        await service.create_resource(
            resource_id=resource_id,
            resource_type=kw.get("resource_type", "secret"),
            description=None,
            content=content,
            principal=ADMIN,
            request_id="r",
        )

    await create()
    with pytest.raises(ConflictError):
        await create()
    with pytest.raises(ValidationError, match="Invalid resource"):
        await create("Not A Slug")
    with pytest.raises(ValidationError, match="Invalid resource"):
        await create("k2", resource_type="password_manager")
    with pytest.raises(ValidationError, match="empty"):
        await create("k3", b"")
    with pytest.raises(ValidationError, match="exceeds"):
        await create("k4", b"x" * (MAX_RESOURCE_BYTES + 1))


@pytest.mark.asyncio
async def test_replace_resource_reencrypts_and_bumps_the_version() -> None:
    repo = InMemoryServiceRepository()
    repo.resources["k"] = make_resource("k", description="old")
    replaced = await resources(repo).replace_resource(
        "k", content=b"rotated", description=None, principal=ADMIN, request_id="r"
    )
    assert replaced.version == 2
    assert replaced.description == "old"  # kept when not supplied
    assert make_cipher().decrypt(repo.resources["k"].ciphertext) == b"rotated"
    assert repo.audit_events[-1]["action"] == "resource.update"


@pytest.mark.asyncio
async def test_a_resource_used_by_a_connector_cannot_be_deleted() -> None:
    repo = repo_with_token()
    repo.connectors["portainer_main"] = portainer_connector()
    with pytest.raises(ConflictError, match="connector portainer_main \\(token\\)"):
        await resources(repo).delete_resource("portainer_token", principal=ADMIN, request_id="r")

    repo.connectors.clear()
    await resources(repo).delete_resource("portainer_token", principal=ADMIN, request_id="r")
    assert repo.resources == {}
    with pytest.raises(NotFoundError):
        await resources(repo).get_resource("portainer_token")
