"""Catalog v2 import/export end to end: parsing, reference validation, atomicity, resource
sources and encryption, warnings, and secret-free export (application/services/catalog.py)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fakes import (
    TEST_SUFFIXES,
    InMemoryServiceRepository,
    make_cipher,
    make_resource,
    portainer_connector,
)

from capataz_api.application.services import (
    CatalogContext,
    export_catalog,
    import_catalog_yaml,
    import_startup_catalog,
    parse_catalog_yaml,
)
from capataz_api.domain.exceptions import ValidationError
from capataz_api.domain.value_objects import ActionType, ResourceType
from capataz_api.infrastructure.resources import FileSystemResourceSourceLoader

BASE = """version: 2
resources:
  - id: portainer_token
    type: secret
    source: {file: portainer_token}
connectors:
  - id: portainer_main
    type: portainer
    config: {url: "https://portainer.home.arpa", token: portainer_token}
  - {id: http, type: http}
services:
  - id: open-webui
    name: Open WebUI
    group_name: IA
    environment: homelab
    runtime:
      connector: portainer_main
      environment_id: 7
      containers: [{name: open-webui}]
    observability:
      health: {connector: http, url: "https://openwebui.home.arpa/health"}
    actions:
      - key: restart
        label: Restart
        risk_level: operate
        connector: portainer_main
        config: {operation: restart, target: selected_containers}
"""


def context(
    resources_dir: Path, *, inline_permitted: bool = True, **environ: str
) -> CatalogContext:
    return CatalogContext(
        cipher=make_cipher(),
        loader=FileSystemResourceSourceLoader(resources_dir, environ=environ),
        inline_permitted=inline_permitted,
        allowed_suffixes=TEST_SUFFIXES,
    )


@pytest.fixture
def resources_dir(tmp_path: Path) -> Path:
    (tmp_path / "portainer_token").write_bytes(b"file-secret-value\n")
    return tmp_path


async def _import(
    repo: InMemoryServiceRepository, raw: str, ctx: CatalogContext, dry_run: bool = False
):  # noqa: ANN202
    return await import_catalog_yaml(repo, raw, dry_run=dry_run, context=ctx)


@pytest.mark.asyncio
async def test_import_creates_encrypted_resources_connectors_services_and_actions(
    resources_dir: Path,
) -> None:
    repo = InMemoryServiceRepository()
    outcome = await _import(repo, BASE, context(resources_dir))

    assert outcome.valid, outcome.errors
    assert outcome.counts == {
        "resources": {"created": 1, "updated": 0, "unchanged": 0},
        "connectors": {"created": 2, "updated": 0, "unchanged": 0},
        "services": {"created": 1, "updated": 0, "unchanged": 0},
    }
    resource = repo.resources["portainer_token"]
    assert b"file-secret-value" not in resource.ciphertext
    assert make_cipher().decrypt(resource.ciphertext) == b"file-secret-value\n"
    assert resource.source == {"file": "portainer_token"}
    assert set(repo.connectors) == {"portainer_main", "http"}
    service = repo.services["open-webui"]
    assert service.spec.runtime is not None and service.spec.runtime.environment_id == "7"
    action = repo.actions[("open-webui", "restart")]
    assert (action.connector_id, action.action_type) == ("portainer_main", ActionType.PORTAINER)


@pytest.mark.asyncio
async def test_reimport_is_idempotent_for_resources_and_keeps_action_ids(
    resources_dir: Path,
) -> None:
    repo = InMemoryServiceRepository()
    await _import(repo, BASE, context(resources_dir))
    first_action_id = repo.actions[("open-webui", "restart")].id

    again = await _import(repo, BASE, context(resources_dir))

    assert again.counts["resources"] == {"created": 0, "updated": 0, "unchanged": 1}
    assert again.counts["services"]["updated"] == 1
    assert repo.resources["portainer_token"].version == 1
    assert repo.actions[("open-webui", "restart")].id == first_action_id


@pytest.mark.asyncio
async def test_a_changed_resource_file_is_reencrypted(resources_dir: Path) -> None:
    repo = InMemoryServiceRepository()
    await _import(repo, BASE, context(resources_dir))
    (resources_dir / "portainer_token").write_bytes(b"rotated-token")

    outcome = await _import(repo, BASE, context(resources_dir))

    assert outcome.counts["resources"]["updated"] == 1
    assert repo.resources["portainer_token"].version == 2
    assert make_cipher().decrypt(repo.resources["portainer_token"].ciphertext) == b"rotated-token"


@pytest.mark.asyncio
async def test_a_broken_reference_is_reported_with_its_line_and_nothing_is_written(
    resources_dir: Path,
) -> None:
    repo = InMemoryServiceRepository()
    raw = BASE.replace(
        "      connector: portainer_main\n      environment_id",
        "      connector: ghost\n      environment_id",
    )

    outcome = await _import(repo, raw, context(resources_dir))

    assert not outcome.valid
    runtime_error, action_error = outcome.errors
    assert (runtime_error.path, runtime_error.line) == ("services.0.runtime.connector", 17)
    # The Portainer action no longer uses the (now different) runtime connector either.
    assert action_error.path == "services.0.actions.0.config.target"
    # All-or-nothing: the valid resource and connectors in the same document weren't written.
    assert (repo.resources, repo.connectors, repo.services) == ({}, {}, {})


@pytest.mark.asyncio
async def test_a_missing_resource_file_is_an_error_on_its_source_line(tmp_path: Path) -> None:
    outcome = await _import(InMemoryServiceRepository(), BASE, context(tmp_path))
    assert not outcome.valid
    assert outcome.errors[0].path == "resources.0.source"
    assert "does not exist" in outcome.errors[0].message
    assert outcome.errors[0].line == 5


@pytest.mark.asyncio
async def test_a_resource_of_the_wrong_type_is_rejected(resources_dir: Path) -> None:
    raw = BASE.replace("    type: secret\n", "    type: ssh_private_key\n")
    outcome = await _import(InMemoryServiceRepository(), raw, context(resources_dir))
    assert not outcome.valid
    assert outcome.errors[0].path == "connectors.0.config.token"
    assert "expected secret" in outcome.errors[0].message


INLINE = BASE.replace(
    "source: {file: portainer_token}", f"source: {{base64: {base64.b64encode(b'tok').decode()}}}"
)


@pytest.mark.asyncio
async def test_inline_resources_warn_in_development_and_are_refused_in_production(
    tmp_path: Path,
) -> None:
    dev = await _import(InMemoryServiceRepository(), INLINE, context(tmp_path))
    assert dev.valid
    assert dev.warnings[0].path == "resources.0.source"
    assert dev.warnings[0].line == 5

    prod = await _import(
        InMemoryServiceRepository(), INLINE, context(tmp_path, inline_permitted=False)
    )
    assert not prod.valid
    assert "refused in production" in prod.errors[0].message


@pytest.mark.asyncio
async def test_env_sources_are_decoded(tmp_path: Path) -> None:
    raw = BASE.replace(
        "source: {file: portainer_token}", "source: {env: PORTAINER_TOKEN_B64, encoding: base64}"
    )
    repo = InMemoryServiceRepository()
    outcome = await _import(
        repo, raw, context(tmp_path, PORTAINER_TOKEN_B64=base64.b64encode(b"from-env").decode())
    )
    assert outcome.valid
    assert make_cipher().decrypt(repo.resources["portainer_token"].ciphertext) == b"from-env"


@pytest.mark.asyncio
async def test_a_resource_without_source_must_already_have_been_uploaded(tmp_path: Path) -> None:
    raw = BASE.replace("    source: {file: portainer_token}\n", "")
    missing = await _import(InMemoryServiceRepository(), raw, context(tmp_path))
    assert not missing.valid
    assert "has not been uploaded yet" in missing.errors[0].message

    repo = InMemoryServiceRepository()
    repo.resources["portainer_token"] = make_resource("portainer_token", ResourceType.SECRET)
    uploaded = await _import(repo, raw, context(tmp_path))
    assert uploaded.valid
    assert uploaded.counts["resources"]["unchanged"] == 1


@pytest.mark.asyncio
async def test_action_config_is_validated_against_its_connector_type(resources_dir: Path) -> None:
    raw = BASE.replace(
        "config: {operation: restart, target: selected_containers}",
        "config: {playbook: playbooks/restart_service.yml, limit: node-ai-01}",
    )
    outcome = await _import(InMemoryServiceRepository(), raw, context(resources_dir))
    assert not outcome.valid
    assert outcome.errors[0].path == "services.0.actions.0.config"


@pytest.mark.asyncio
async def test_portainer_action_target_must_match_the_runtime_selector_kind(
    resources_dir: Path,
) -> None:
    raw = BASE.replace("target: selected_containers", "target: selected_services")
    outcome = await _import(InMemoryServiceRepository(), raw, context(resources_dir))
    assert not outcome.valid
    assert outcome.errors[0].path == "services.0.actions.0.config.target"


@pytest.mark.asyncio
async def test_connector_urls_and_http_allow_lists_cannot_escape_the_global_ceiling(
    resources_dir: Path,
) -> None:
    raw = BASE.replace("https://portainer.home.arpa", "https://portainer.evil.example").replace(
        "{id: http, type: http}",
        "{id: http, type: http, config: {allowed_host_suffixes: [.example.com]}}",
    )
    outcome = await _import(InMemoryServiceRepository(), raw, context(resources_dir))
    assert not outcome.valid
    assert [error.path for error in outcome.errors][:2] == [
        "connectors.0.config.url",
        "connectors.1.config.allowed_host_suffixes.0",
    ]


@pytest.mark.asyncio
async def test_references_can_point_at_connectors_already_in_the_database(tmp_path: Path) -> None:
    repo = InMemoryServiceRepository()
    repo.connectors["portainer_main"] = portainer_connector()
    repo.resources["portainer_token"] = make_resource("portainer_token")
    raw = """version: 2
services:
  - id: one
    name: One
    group_name: G
    environment: dev
    runtime: {connector: portainer_main, environment_id: 7, containers: [{name: one}]}
"""
    assert (await _import(repo, raw, context(tmp_path))).valid


def test_structural_errors_keep_their_yaml_line_numbers() -> None:
    raw = BASE.replace(
        "config: {operation: restart, target: selected_containers}", "config: {command: rm -rf /}"
    )
    with pytest.raises(ValidationError) as excinfo:
        parse_catalog_yaml(raw)
    (field_error,) = excinfo.value.field_errors
    assert field_error.path == "services.0.actions.0.config"
    assert "command is never permitted" in field_error.message
    assert field_error.line == 27


def test_version_1_catalogs_are_rejected_with_a_conversion_hint() -> None:
    with pytest.raises(ValidationError) as excinfo:
        parse_catalog_yaml("version: 1\nservices: []\n")
    assert "convert_catalog_v1_to_v2.py" in excinfo.value.field_errors[0].message


def test_duplicate_ids_are_rejected() -> None:
    raw = BASE.replace("{id: http, type: http}", "{id: portainer_main, type: http}")
    with pytest.raises(ValidationError, match="validation error"):
        parse_catalog_yaml(raw)


@pytest.mark.asyncio
async def test_export_never_contains_resource_content_and_round_trips(tmp_path: Path) -> None:
    (tmp_path / "portainer_token").write_bytes(b"file-secret-value")
    inline_secret = b"inline-secret-value"
    raw = BASE.replace(
        "connectors:",
        "  - id: extra_token\n"
        "    type: secret\n"
        f"    source: {{base64: {base64.b64encode(inline_secret).decode()}}}\n"
        "connectors:",
    )
    repo = InMemoryServiceRepository()
    assert (await _import(repo, raw, context(tmp_path))).valid

    exported = await export_catalog(repo)

    for secret in (b"file-secret-value", inline_secret):
        assert secret.decode() not in exported
        assert base64.b64encode(secret).decode() not in exported
    reparsed = parse_catalog_yaml(exported)
    by_id = {resource.id: resource for resource in reparsed.resources}
    assert by_id["portainer_token"].source is not None  # file source is kept
    assert by_id["extra_token"].source is None  # inline content is never re-emitted
    # The export re-imports cleanly against the same database.
    assert (await _import(repo, exported, context(tmp_path), dry_run=True)).valid


@pytest.mark.asyncio
async def test_startup_import_raises_on_invalid_or_missing_catalogs(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    with pytest.raises(RuntimeError, match="does not exist"):
        await import_startup_catalog(InMemoryServiceRepository(), str(tmp_path / "nope.yml"), ctx)

    invalid = tmp_path / "catalog.yml"
    invalid.write_text(BASE)  # its file resource is missing from tmp_path
    with pytest.raises(ValidationError, match="Initial catalog is invalid"):
        await import_startup_catalog(InMemoryServiceRepository(), str(invalid), ctx)

    await import_startup_catalog(InMemoryServiceRepository(), None, ctx)  # no-op
