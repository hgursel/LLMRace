"""add encrypted api key column to connections

Revision ID: 0002_connection_api_key_encrypted
Revises: 0001_initial
Create Date: 2026-02-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_connection_api_key_encrypted"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("api_key_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("connections", "api_key_encrypted")
