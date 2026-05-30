"""add_topics_table

Revision ID: d09feea24704
Revises: 7e13dc0c8ae6
Create Date: 2026-05-30 15:00:15.350220

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd09feea24704'
down_revision: Union[str, Sequence[str], None] = '7e13dc0c8ae6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
