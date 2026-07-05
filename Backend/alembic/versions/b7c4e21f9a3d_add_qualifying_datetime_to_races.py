"""add_qualifying_datetime_to_races

Revision ID: b7c4e21f9a3d
Revises: f3a1b9c7d2e4
Create Date: 2026-07-04 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7c4e21f9a3d'
down_revision: Union[str, Sequence[str], None] = 'f3a1b9c7d2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'races',
        sa.Column('qualifying_datetime', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('races', 'qualifying_datetime')
