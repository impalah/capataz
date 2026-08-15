"""add unattended flag to action_definitions

Revision ID: 20260813_0002
Revises: 20260808_0001
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

revision = "20260813_0002"
down_revision = "20260808_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "action_definitions",
        sa.Column("unattended", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("action_definitions", "unattended")
