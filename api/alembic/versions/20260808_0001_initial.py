"""initial Capataz schema

Revision ID: 20260808_0001
Revises:
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260808_0001"
down_revision = None
branch_labels = None
depends_on = None
json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table("services", sa.Column("id", sa.String(128), primary_key=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("description", sa.Text()), sa.Column("group_name", sa.String(128), nullable=False), sa.Column("icon", sa.String(128)), sa.Column("environment", sa.String(128), nullable=False), sa.Column("service_url", sa.Text()), sa.Column("documentation_url", sa.Text()), sa.Column("portainer_environment_id", sa.String(128)), sa.Column("portainer_stack_name", sa.String(255)), sa.Column("container_selectors", json_type, nullable=False), sa.Column("health_config", json_type, nullable=False), sa.Column("grafana_config", json_type, nullable=False), sa.Column("loki_config", json_type, nullable=False), sa.Column("metadata", json_type, nullable=False), sa.Column("maintenance", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("action_definitions", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("service_id", sa.String(128), sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=False), sa.Column("key", sa.String(128), nullable=False), sa.Column("label", sa.String(255), nullable=False), sa.Column("description", sa.Text()), sa.Column("icon", sa.String(128)), sa.Column("action_type", sa.String(32), nullable=False), sa.Column("risk_level", sa.String(32), nullable=False), sa.Column("requires_confirmation", sa.Boolean(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("config", json_type, nullable=False), sa.Column("allowed_parameters_schema", json_type, nullable=False), sa.UniqueConstraint("service_id", "key", name="uq_action_service_key"))
    op.create_table("executions", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("service_id", sa.String(128), sa.ForeignKey("services.id"), nullable=False), sa.Column("action_definition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("action_definitions.id"), nullable=False), sa.Column("requested_by_subject", sa.String(255), nullable=False), sa.Column("requested_by_email", sa.String(255)), sa.Column("source", sa.String(32), nullable=False), sa.Column("params", json_type, nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)), sa.Column("correlation_id", sa.String(128), nullable=False), sa.Column("worker_task_id", sa.String(255)), sa.Column("result_summary", sa.Text()), sa.Column("error_code", sa.String(128)), sa.Column("error_summary", sa.Text()))
    op.create_table("execution_events", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("execution_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("executions.id", ondelete="CASCADE"), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("level", sa.String(32), nullable=False), sa.Column("event_type", sa.String(128), nullable=False), sa.Column("message", sa.Text(), nullable=False), sa.Column("data", json_type, nullable=False), sa.UniqueConstraint("execution_id", "sequence", name="uq_execution_event_sequence"))
    op.create_table("audit_events", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("actor", sa.String(255), nullable=False), sa.Column("action", sa.String(128), nullable=False), sa.Column("resource", sa.String(255), nullable=False), sa.Column("outcome", sa.String(64), nullable=False), sa.Column("ip_address", sa.String(64)), sa.Column("request_id", sa.String(128)), sa.Column("metadata", json_type, nullable=False))


def downgrade() -> None:
    op.drop_table("audit_events"); op.drop_table("execution_events"); op.drop_table("executions"); op.drop_table("action_definitions"); op.drop_table("services")
