"""Initial tables: anonymous_sessions and projects (W1).

No personal deed fields yet (docs/WEB_BACKEND_SCOPE.md).

Revision ID: w1_0001
Revises:
Create Date: 2026-07-20

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "w1_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "anonymous_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("current_step", sa.String(length=32), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["anonymous_sessions.id"]),
    )
    op.create_index("ix_projects_session_id", "projects", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_projects_session_id", table_name="projects")
    op.drop_table("projects")
    op.drop_table("anonymous_sessions")
