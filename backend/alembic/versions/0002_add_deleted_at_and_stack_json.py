"""add_deleted_at_and_stack_json

Revision ID: 0002_lifecycle
Revises: 894558d99604
Create Date: 2026-02-26

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0002_lifecycle"
down_revision: Union[str, Sequence[str], None] = "894558d99604"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("projects", sa.Column("stack_json", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "stack_json")
    op.drop_column("projects", "deleted_at")
