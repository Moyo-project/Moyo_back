"""add reply_to_id to messages

Revision ID: a1b2c3d4e5f6
Revises: f0fe6a557071
Create Date: 2026-05-28 00:00:00.000000

"""
from typing import Union, Sequence
import sqlalchemy as sa
from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f0fe6a557071'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'messages',
        sa.Column('reply_to_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_messages_reply_to_id',
        'messages', 'messages',
        ['reply_to_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_messages_reply_to_id', 'messages', type_='foreignkey')
    op.drop_column('messages', 'reply_to_id')
