"""Runs the real Alembic chain against Postgres and checks that 20260912_0009 moves v1 service
and action rows onto connector specs in place, without losing execution history."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from capataz_api.domain.specs import ServiceSpec

API_ROOT = Path(__file__).resolve().parents[2]


def _sync_url(url: str) -> str:
    return url.replace("postgresql+asyncpg", "postgresql+psycopg")


@pytest.fixture
def migration_db_url(postgres_url: str) -> Iterator[str]:
    """A fresh, empty database in the shared container (the other suites create_all theirs)."""
    name = f"capataz_migration_{uuid4().hex[:8]}"
    admin = sa.create_engine(_sync_url(postgres_url), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE DATABASE "{name}"'))
    base, _, _ = postgres_url.rpartition("/")
    yield f"{base}/{name}"
    with admin.connect() as connection:
        connection.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


def _alembic_config() -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    return config


def _jsonb(value: object) -> str:
    return json.dumps(value)


def test_0009_moves_v1_rows_onto_connector_specs(
    migration_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "capataz_api.core.settings.get_settings",
        lambda: SimpleNamespace(database_url=migration_db_url),
    )
    monkeypatch.setenv("CAPATAZ_PORTAINER_URL", "https://portainer.home.arpa")
    monkeypatch.delenv("CAPATAZ_GRAFANA_URL", raising=False)
    config = _alembic_config()
    command.upgrade(config, "20260912_0008")

    engine = sa.create_engine(_sync_url(migration_db_url))
    restart_id, backup_id, http_id, execution_id = uuid4(), uuid4(), uuid4(), uuid4()
    with engine.begin() as connection:
        insert_service = sa.text(
            "INSERT INTO services (id, name, description, group_name, icon, environment, "
            "service_url, documentation_url, portainer_environment_id, portainer_stack_name, "
            "container_selectors, health_config, grafana_config, loki_config, metrics_config, "
            "metadata, maintenance) VALUES (:id, :name, :description, :group_name, :icon, "
            ":environment, :service_url, NULL, :env_id, :stack, CAST(:selectors AS JSONB), "
            "CAST(:health AS JSONB), CAST(:grafana AS JSONB), CAST(:loki AS JSONB), "
            "CAST(:metrics AS JSONB), CAST(:metadata AS JSONB), false)"
        )
        connection.execute(
            insert_service,
            {
                "id": "authentik",
                "name": "Authentik",
                "description": "SSO",
                "group_name": "Security",
                "icon": "lock",
                "environment": "homelab",
                "service_url": "https://authentik.home.arpa",
                "env_id": "7",
                "stack": "authentik",
                "selectors": _jsonb(
                    {
                        "aggregation": "any_healthy",
                        "services": [{"name": "authentik-server", "replicas": 2, "required": True}],
                    }
                ),
                "health": _jsonb(
                    {
                        "type": "http",
                        "url": "https://authentik.home.arpa/-/health/live/",
                        "expected_status": 204,
                        "timeout_seconds": 3,
                    }
                ),
                "grafana": _jsonb(
                    {
                        "dashboard_uid": "homelab-generic/generic-service",
                        "variables": {"var-service": "authentik"},
                    }
                ),
                "loki": _jsonb({"query": '{stack="authentik"}'}),
                "metrics": _jsonb([{"label": "CPU", "type": "prometheus", "query": "up"}]),
                "metadata": _jsonb({"owner": "ana"}),
            },
        )
        connection.execute(
            insert_service,
            {
                "id": "bare",
                "name": "Bare",
                "description": None,
                "group_name": "Misc",
                "icon": None,
                "environment": "dev",
                "service_url": None,
                "env_id": None,
                "stack": None,
                "selectors": _jsonb({}),
                "health": _jsonb({}),
                "grafana": _jsonb({}),
                "loki": _jsonb({}),
                "metrics": _jsonb([]),
                "metadata": _jsonb({}),
            },
        )
        insert_action = sa.text(
            "INSERT INTO action_definitions (id, service_id, key, label, action_type, risk_level, "
            "requires_confirmation, enabled, unattended, config, allowed_parameters_schema) "
            "VALUES (:id, 'authentik', :key, :key, :type, 'operate', false, true, false, "
            "CAST(:config AS JSONB), CAST('{}' AS JSONB))"
        )
        connection.execute(
            insert_action,
            {
                "id": restart_id,
                "key": "restart",
                "type": "portainer",
                "config": _jsonb({"operation": "restart", "target": "selected_services"}),
            },
        )
        connection.execute(
            insert_action,
            {
                "id": backup_id,
                "key": "backup",
                "type": "ansible",
                "config": _jsonb(
                    {
                        "playbook": "playbooks/backup_service.yml",
                        "inventory": "inventories/homelab.yml",
                        "limit": "node-ai-01",
                    }
                ),
            },
        )
        connection.execute(
            insert_action,
            {"id": http_id, "key": "webhook", "type": "http", "config": _jsonb({})},
        )
        connection.execute(
            sa.text(
                "INSERT INTO executions (id, service_id, service_id_snapshot, "
                "action_definition_id, action_key, requested_by_subject, source, params, status, "
                "correlation_id) VALUES (:id, 'authentik', 'authentik', :action, 'restart', "
                "'ana', 'ui', CAST('{}' AS JSONB), 'succeeded', 'r1')"
            ),
            {"id": execution_id, "action": restart_id},
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        columns = {column["name"] for column in sa.inspect(connection).get_columns("services")}
        assert columns == {
            "id",
            "spec",
            "name",
            "group_name",
            "environment",
            "status_cache",
            "status_cache_updated_at",
            "version",
            "created_at",
            "updated_at",
        }
        spec = ServiceSpec.model_validate(
            connection.execute(
                sa.text("SELECT spec FROM services WHERE id = 'authentik'")
            ).scalar_one()
        )
        assert spec.runtime is not None
        assert (spec.runtime.connector, spec.runtime.environment_id, spec.runtime.stack_name) == (
            "portainer",
            "7",
            "authentik",
        )
        assert spec.runtime.aggregation.value == "any_healthy"
        assert spec.runtime.services is not None and spec.runtime.services[0].replicas == 2
        health = spec.observability.health
        assert health is not None
        assert (health.connector, health.expected_status, health.timeout_seconds) == (
            "http",
            204,
            3,
        )
        dashboard = spec.observability.dashboards[0]
        assert (dashboard.uid, dashboard.slug) == ("homelab-generic", "generic-service")
        assert spec.observability.logs is not None and spec.observability.logs.connector == "loki"
        assert [metric.connector for metric in spec.observability.metrics] == ["prometheus"]
        assert spec.metadata == {"owner": "ana"}

        bare = ServiceSpec.model_validate(
            connection.execute(sa.text("SELECT spec FROM services WHERE id = 'bare'")).scalar_one()
        )
        assert bare.runtime is None and bare.observability.health is None

        actions = dict(
            connection.execute(sa.text("SELECT key, connector_id FROM action_definitions")).all()
        )
        assert actions == {"restart": "portainer", "backup": "ansible"}  # http one dropped
        backup_config = connection.execute(
            sa.text("SELECT config FROM action_definitions WHERE key = 'backup'")
        ).scalar_one()
        assert "inventory" not in backup_config
        assert (
            connection.execute(
                sa.text("SELECT action_definition_id FROM executions WHERE id = :id"),
                {"id": execution_id},
            ).scalar_one()
            == restart_id
        )
        connector_urls = dict(
            connection.execute(sa.text("SELECT id, config->>'url' FROM connectors")).all()
        )
        assert connector_urls["portainer"] == "https://portainer.home.arpa"
        assert connector_urls["grafana"] == "https://capataz-placeholder.invalid"

    with pytest.raises(RuntimeError, match="irreversible"):
        command.downgrade(config, "20260912_0008")
    engine.dispose()
