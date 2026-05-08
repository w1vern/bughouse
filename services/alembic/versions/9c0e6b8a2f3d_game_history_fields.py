"""game history fields

Revision ID: 9c0e6b8a2f3d
Revises: 106fb4ae6b95
Create Date: 2026-05-08 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "9c0e6b8a2f3d"
down_revision: Union[str, None] = "106fb4ae6b95"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "game_users",
        "board",
        new_column_name="board_number",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
    op.add_column(
        "games",
        sa.Column("rated", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.alter_column("games", "rated", server_default=None)
    op.add_column("games", sa.Column("end_reason", sa.String(), nullable=True))
    op.alter_column(
        "moves",
        "time_to_move",
        existing_type=sa.Float(),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="round(time_to_move * 1000)::integer",
    )


def downgrade() -> None:
    op.alter_column(
        "moves",
        "time_to_move",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        existing_nullable=False,
        postgresql_using="time_to_move / 1000.0",
    )
    op.drop_column("games", "end_reason")
    op.drop_column("games", "rated")
    op.alter_column(
        "game_users",
        "board_number",
        new_column_name="board",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
