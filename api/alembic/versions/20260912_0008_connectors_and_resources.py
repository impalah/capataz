"""add resources (encrypted files/secrets) and connectors (typed connection plugins)

Purely additive: services/action_definitions keep their current shape until 20260912_0009
moves them onto connector references (see docs/adr/008-connectors-and-resources).

Revision ID: 20260912_0008
Revises: 20260907_0007
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260912_0008"
down_revision = "20260907_0007"
branch_labels = None
depends_on = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "resources",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("source", json_type, nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "connectors",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("config", json_type, nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("connectors")
    op.drop_table("resources")
