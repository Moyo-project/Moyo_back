"""merge_heads

Revision ID: 7e13dc0c8ae6
Revises: 00ea24364b3c, a1b2c3d4e5f6
Create Date: 2026-05-30 14:59:54.702812

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7e13dc0c8ae6'
down_revision: Union[str, Sequence[str], None] = ('00ea24364b3c', 'a1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
