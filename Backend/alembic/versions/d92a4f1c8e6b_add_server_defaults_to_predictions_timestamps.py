"""add_server_defaults_to_predictions_timestamps

Revision ID: d92a4f1c8e6b
Revises: b7c4e21f9a3d
Create Date: 2026-07-04 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd92a4f1c8e6b'
down_revision: Union[str, Sequence[str], None] = 'b7c4e21f9a3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """predictions.created_at/updated_at only had a client-side (SQLAlchemy
    ORM) default, so raw-SQL inserts like database/crud.py's save_prediction
    left them NULL. Add real server-side defaults so any insert path gets a
    correct timestamp."""
    op.alter_column('predictions', 'created_at', server_default=sa.text('now()'))
    op.alter_column('predictions', 'updated_at', server_default=sa.text('now()'))


def downgrade() -> None:
    op.alter_column('predictions', 'created_at', server_default=None)
    op.alter_column('predictions', 'updated_at', server_default=None)
