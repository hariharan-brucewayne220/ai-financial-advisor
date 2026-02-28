"""add message audit columns

Revision ID: 20260227_add_message_audit
Revises: 
Create Date: 2026-02-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260227_add_message_audit'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('messages', sa.Column('market_data_symbols', postgresql.ARRAY(sa.String()), server_default='{}', nullable=True))
    op.add_column('messages', sa.Column('market_data_available', sa.String(length=20), nullable=True))
    op.add_column('messages', sa.Column('data_sources_json', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'data_sources_json')
    op.drop_column('messages', 'market_data_available')
    op.drop_column('messages', 'market_data_symbols')
    op.drop_column('messages', 'retrieved_at')
