"""Add halfmove_clock and position_history for threefold repetition and fifty-move rule

Revision ID: 642e3983818c
Revises: 6d0301fdb270
Create Date: 2026-05-06 22:14:41.953851

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '642e3983818c'
down_revision = '6d0301fdb270'
branch_labels = None
depends_on = None


def upgrade():
    # Add halfmove_clock column
    op.add_column('game', sa.Column('halfmove_clock', sa.Integer(), nullable=True, default=0))
    
    # Add position_history column
    op.add_column('game', sa.Column('position_history', sa.Text(), nullable=True, default=""))
    
    # Update existing records to have default values
    op.execute("UPDATE game SET halfmove_clock = 0 WHERE halfmove_clock IS NULL")
    op.execute("UPDATE game SET position_history = '' WHERE position_history IS NULL")


def downgrade():
    # Remove the new columns
    op.drop_column('game', 'position_history')
    op.drop_column('game', 'halfmove_clock')
