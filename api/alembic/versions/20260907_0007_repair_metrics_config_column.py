"""repair: services.metrics_config is missing in production despite alembic_version already

recording 20260907_0006 as applied there — the live DB's `alembic_version` table advanced past
that revision without the ADD COLUMN actually taking effect (root cause not fully diagnosed;
most likely several `alembic upgrade head` invocations raced during a crash-loop before this
repair was written). This migration is a defensive, idempotent no-op wherever the column already
exists, and a real fix wherever it doesn't.

Revision ID: 20260907_0007
Revises: 20260907_0006
Create Date: 2026-09-07
"""
from alembic import op

revision = "20260907_0007"
down_revision = "20260907_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE services ADD COLUMN IF NOT EXISTS metrics_config jsonb NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    # No-op: this migration only ever repairs a column that migration 20260907_0006 (still in
    # history) already owns dropping.
    pass
