
"""add bots

Revision ID: a1b2c3d4e5f6
Revises: c36b4db1e66f
Create Date: 2026-06-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'c36b4db1e66f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'is_bot', sa.Boolean(), nullable=False,
            server_default=sa.false()
        )
    )
    op.create_table(
        'bots',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('engine_enabled', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('strength', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_date', sa.DateTime(),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_date', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bots_user_id'), 'bots', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_bots_user_id'), table_name='bots')
    op.drop_table('bots')
    op.drop_column('users', 'is_bot')
