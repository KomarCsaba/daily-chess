"""add game metadata columns

Revision ID: 6d0301fdb270
Revises: 
Create Date: 2026-05-06 21:56:40.474916

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6d0301fdb270'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=120), nullable=False),
        sa.Column("password", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("username"),
    )

    op.create_table(
        "game",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("white_id", sa.Integer(), nullable=False),
        sa.Column("black_id", sa.Integer(), nullable=True),
        sa.Column("board_fen", sa.String(length=200), nullable=False),
        sa.Column("turn", sa.String(length=5), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("result", sa.String(length=20), nullable=True),
        sa.Column("move_history", sa.Text(), nullable=True),
        sa.Column("last_move_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("draw_offered_by", sa.Integer(), nullable=True),
        sa.Column("join_code", sa.String(length=8), nullable=True),
        sa.Column("time_control", sa.String(length=20), nullable=True),
        sa.Column("time_control_mode", sa.String(length=20), nullable=True),
        sa.Column("turn_time_seconds", sa.Integer(), nullable=True),
        sa.Column("white_time_remaining", sa.Integer(), nullable=True),
        sa.Column("black_time_remaining", sa.Integer(), nullable=True),
        sa.Column("last_move_uci", sa.String(length=10), nullable=True),
        sa.Column("last_move_flags", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["black_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["white_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("join_code"),
    )


def downgrade():
    op.drop_table("game")
    op.drop_table("user")
