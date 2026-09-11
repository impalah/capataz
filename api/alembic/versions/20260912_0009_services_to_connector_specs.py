"""move services and action definitions onto connector references (catalog v2)

services: every descriptive/integration column is folded into a single `spec` JSON document
(domain.specs.ServiceSpec) that references connectors by id; name/group_name/environment stay
as plain columns only for SQL ordering/filtering. action_definitions gain a mandatory
`connector_id` (FK -> connectors, ON DELETE RESTRICT).

Existing rows are transformed in place (action rows keep their ids, so execution history FKs
survive) and point at placeholder connectors `portainer`, `prometheus`, `grafana`, `loki`, `http`
and `ansible`, seeded from the legacy CAPATAZ_*_URL environment variables when present. Their
resources (portainer_token, ...) are NOT created here: the v2 catalog import that runs at every
API startup replaces all of this with the real definitions.

Irreversible: take a pg_dump before upgrading; downgrade refuses to run.

Revision ID: 20260912_0009
Revises: 20260912_0008
Create Date: 2026-09-12
"""
import json
import os
from typing import Any

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260912_0009"
down_revision = "20260912_0008"
branch_labels = None
depends_on = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

_PLACEHOLDER_URL = "https://capataz-placeholder.invalid"
_LEGACY_SERVICE_COLUMNS = (
    "description",
    "icon",
    "service_url",
    "documentation_url",
    "portainer_environment_id",
    "portainer_stack_name",
    "container_selectors",
    "health_config",
    "grafana_config",
    "loki_config",
    "metrics_config",
    "metadata",
    "maintenance",
)


def _url(env_var: str) -> str:
    return os.environ.get(env_var) or _PLACEHOLDER_URL


def _placeholder_connectors() -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (
            "portainer",
            "portainer",
            {"url": _url("CAPATAZ_PORTAINER_URL"), "token": "portainer_token", "verify_tls": True},
        ),
        ("prometheus", "prometheus", {"url": _url("CAPATAZ_PROMETHEUS_URL"), "verify_tls": True}),
        ("grafana", "grafana", {"url": _url("CAPATAZ_GRAFANA_URL")}),
        ("loki", "loki", {"url": _url("CAPATAZ_LOKI_URL")}),
        ("http", "http", {"allowed_host_suffixes": [], "verify_tls": True}),
        (
            "ansible",
            "ansible",
            {
                "inventory": "inventories/homelab.yml",
                "private_key": "runner_ssh_private_key",
                "known_hosts": "runner_known_hosts",
                "vault_password": "ansible_vault_password",
            },
        ),
    ]


def _selector_entries(entries: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    keys = {"name", "required", "critical"} | ({"replicas"} if kind == "services" else set())
    return [{key: value for key, value in entry.items() if key in keys} for entry in entries]


def _runtime(row: Any) -> dict[str, Any] | None:
    if not row.portainer_environment_id:
        return None
    selectors = row.container_selectors or {}
    kind = "services" if selectors.get("services") else "containers" if selectors.get("containers") else None
    if kind is None:
        return None
    return {
        "connector": "portainer",
        "environment_id": str(row.portainer_environment_id),
        "stack_name": row.portainer_stack_name,
        "aggregation": selectors.get("aggregation", "all_required"),
        kind: _selector_entries(selectors[kind], kind),
    }


def _dashboards(grafana: dict[str, Any]) -> list[dict[str, Any]]:
    uid, url = grafana.get("dashboard_uid"), grafana.get("dashboard_url")
    if not (uid or url):
        return []
    slug = None
    if uid and "/" in str(uid):
        # The v1 field sometimes carried "uid/slug" in one string; v2 keeps them apart.
        uid, slug = str(uid).split("/", 1)
    return [
        {
            "label": "grafana",
            "connector": "grafana",
            "uid": uid,
            "slug": slug,
            "url": url,
            "variables": {str(k): str(v) for k, v in (grafana.get("variables") or {}).items()},
        }
    ]


def _spec(row: Any) -> dict[str, Any]:
    health = row.health_config or {}
    loki = row.loki_config or {}
    return {
        "name": row.name,
        "description": row.description,
        "group_name": row.group_name,
        "environment": row.environment,
        "icon": row.icon,
        "tags": [],
        "service_url": row.service_url,
        "documentation_url": row.documentation_url,
        "runtime": _runtime(row),
        "observability": {
            "health": {
                "connector": "http",
                "url": health["url"],
                "method": "GET",
                "expected_status": int(health.get("expected_status", 200)),
                "timeout_seconds": int(health.get("timeout_seconds", 5)),
            }
            if health.get("url")
            else None,
            "dashboards": _dashboards(row.grafana_config or {}),
            "logs": {"connector": "loki", "query": loki["query"]} if loki.get("query") else None,
            "metrics": [
                {"label": metric["label"], "connector": "prometheus", "query": metric["query"]}
                for metric in (row.metrics_config or [])
                if metric.get("label") and metric.get("query")
            ],
        },
        "metadata": row.metadata or {},
        "maintenance": bool(row.maintenance),
    }


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("services", sa.Column("spec", json_type, nullable=True))
    op.add_column("action_definitions", sa.Column("connector_id", sa.String(128), nullable=True))

    for connector_id, connector_type, config in _placeholder_connectors():
        bind.execute(
            sa.text(
                "INSERT INTO connectors (id, type, description, config) "
                "VALUES (:id, :type, :description, CAST(:config AS JSONB)) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": connector_id,
                "type": connector_type,
                "description": "Placeholder created by migration 20260912_0009",
                "config": json.dumps(config),
            },
        )

    rows = bind.execute(sa.text("SELECT * FROM services")).mappings().all()
    for row in rows:
        bind.execute(
            sa.text("UPDATE services SET spec = CAST(:spec AS JSONB) WHERE id = :id"),
            {"id": row["id"], "spec": json.dumps(_spec(_Row(row)))},
        )

    bind.execute(
        sa.text(
            "UPDATE action_definitions SET connector_id = action_type "
            "WHERE action_type IN ('portainer', 'ansible')"
        )
    )
    # The inventory moved from each ansible action onto its connector.
    bind.execute(
        sa.text(
            "UPDATE action_definitions SET config = config - 'inventory' "
            "WHERE action_type = 'ansible'"
        )
    )
    # http/ssh/rsync definitions were modelled but never executable in v1; nothing can run them.
    bind.execute(sa.text("DELETE FROM action_definitions WHERE connector_id IS NULL"))

    op.alter_column("services", "spec", nullable=False)
    op.alter_column("action_definitions", "connector_id", nullable=False)
    op.create_foreign_key(
        "fk_action_definitions_connector_id",
        "action_definitions",
        "connectors",
        ["connector_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_action_definitions_connector_id", "action_definitions", ["connector_id"]
    )
    for column in _LEGACY_SERVICE_COLUMNS:
        op.drop_column("services", column)


class _Row:
    """Attribute access over a RowMapping (keeps _spec readable)."""

    def __init__(self, mapping: Any) -> None:
        self._mapping = mapping

    def __getattr__(self, name: str) -> Any:
        return self._mapping[name]


def downgrade() -> None:
    raise RuntimeError(
        "20260912_0009 is irreversible: restore the pg_dump taken before upgrading instead"
    )
