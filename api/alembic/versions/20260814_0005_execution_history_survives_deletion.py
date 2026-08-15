"""execution history survives service/action deletion (CR-077)

Adds executions.service_id_snapshot (immutable display label, backfilled from service_id since
Service.id is a human-readable slug, not a surrogate key — unlike action_key, which was already
denormalized this way). Changes executions.service_id/action_definition_id to nullable with
ON DELETE SET NULL, so deleting a service/action with historical (non-active) executions no
longer fails with a misleading "already exists" conflict error.

Revision ID: 20260814_0005
Revises: 20260814_0004
Create Date: 2026-08-14
"""
from alembic import op
import sqlalchemy as sa

revision = "20260814_0005"
down_revision = "20260814_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("executions", sa.Column("service_id_snapshot", sa.String(128), nullable=True))
    op.execute(
        "UPDATE executions SET service_id_snapshot = service_id WHERE service_id_snapshot IS NULL"
    )
    op.alter_column("executions", "service_id_snapshot", nullable=False)

    op.drop_constraint("executions_service_id_fkey", "executions", type_="foreignkey")
    op.create_foreign_key(
        "executions_service_id_fkey",
        "executions",
        "services",
        ["service_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("executions", "service_id", nullable=True)

    op.drop_constraint(
        "executions_action_definition_id_fkey", "executions", type_="foreignkey"
    )
    op.create_foreign_key(
        "executions_action_definition_id_fkey",
        "executions",
        "action_definitions",
        ["action_definition_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("executions", "action_definition_id", nullable=True)


def downgrade() -> None:
    # Note: fails if any row has service_id/action_definition_id already NULL (real data loss
    # from SET NULL in production use) — expand/contract, not a guaranteed-safe rollback.
    op.alter_column("executions", "action_definition_id", nullable=False)
    op.drop_constraint(
        "executions_action_definition_id_fkey", "executions", type_="foreignkey"
    )
    op.create_foreign_key(
        "executions_action_definition_id_fkey",
        "executions",
        "action_definitions",
        ["action_definition_id"],
        ["id"],
    )

    op.alter_column("executions", "service_id", nullable=False)
    op.drop_constraint("executions_service_id_fkey", "executions", type_="foreignkey")
    op.create_foreign_key(
        "executions_service_id_fkey", "executions", "services", ["service_id"], ["id"]
    )

    op.drop_column("executions", "service_id_snapshot")
