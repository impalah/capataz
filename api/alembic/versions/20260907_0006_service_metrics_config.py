"""add metrics_config: a per-service list of admin-authored metric definitions (label/type/query)

Revision ID: 20260907_0006
Revises: 20260814_0005
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260907_0006"
down_revision = "20260814_0005"
branch_labels = None
depends_on = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "services",
        sa.Column("metrics_config", json_type, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("services", "metrics_config")
