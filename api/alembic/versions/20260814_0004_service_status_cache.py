"""persist the aggregated service status as a queryable column (CR-063)

Revision ID: 20260814_0004
Revises: 20260813_0003
Create Date: 2026-08-14
"""
from alembic import op
import sqlalchemy as sa

revision = "20260814_0004"
down_revision = "20260813_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("services", sa.Column("status_cache", sa.String(20), nullable=True))
    op.add_column(
        "services", sa.Column("status_cache_updated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("services", "status_cache_updated_at")
    op.drop_column("services", "status_cache")
