"""add_project_title

Revision ID: 0003_project_title
Revises: 0002_lifecycle
Create Date: 2026-02-26

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003_project_title"
down_revision: Union[str, Sequence[str], None] = "0002_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "title",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'Untitled Project'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "title")
