"""drop_orphaned_uq_race_result_constraint

Revision ID: f3a1b9c7d2e4
Revises: c6513ee7b293
Create Date: 2026-07-04 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f3a1b9c7d2e4'
down_revision: Union[str, Sequence[str], None] = 'c6513ee7b293'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the redundant uq_race_result constraint.

    Older deployments created this via imperative startup SQL in
    app/main.py, duplicating uq_race_results_race_driver (added in
    2d12a0aaec85) on the same (race_id, driver_id) columns. That
    startup SQL has been removed; this cleans up the leftover
    constraint on databases that already ran it. IF EXISTS makes this
    a no-op on databases that never had it.
    """
    op.execute("ALTER TABLE race_results DROP CONSTRAINT IF EXISTS uq_race_result")


def downgrade() -> None:
    """No-op: uq_race_results_race_driver already enforces this uniqueness."""
    pass
