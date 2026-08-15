"""denormalize action_key onto executions; capture actor/requester display name and email

Revision ID: 20260813_0003
Revises: 20260813_0002
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

revision = "20260813_0003"
down_revision = "20260813_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("executions", sa.Column("action_key", sa.String(128), nullable=True))
    op.add_column("executions", sa.Column("requested_by_name", sa.String(255), nullable=True))
    op.add_column("audit_events", sa.Column("actor_name", sa.String(255), nullable=True))
    op.add_column("audit_events", sa.Column("actor_email", sa.String(255), nullable=True))
    op.execute(
        """
        UPDATE executions AS e
        SET action_key = ad.key
        FROM action_definitions AS ad
        WHERE ad.id = e.action_definition_id AND e.action_key IS NULL
        """
    )
    op.execute("UPDATE executions SET action_key = '' WHERE action_key IS NULL")
    op.alter_column("executions", "action_key", nullable=False)


def downgrade() -> None:
    op.drop_column("executions", "action_key")
    op.drop_column("executions", "requested_by_name")
    op.drop_column("audit_events", "actor_name")
    op.drop_column("audit_events", "actor_email")
