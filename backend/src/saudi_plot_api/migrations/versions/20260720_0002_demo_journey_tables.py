"""Demo journey tables (W2): documents, plot, brief, program, runs, outputs,
renders, share tokens, pricing. Seeds one active demo pricing configuration.

Revision ID: w2_0002
Revises: w1_0001
Create Date: 2026-07-20

"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "w2_0002"
down_revision = "w1_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_name", sa.String(length=64), nullable=False),
        sa.Column("relative_path", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("extraction_json", sa.Text(), nullable=True),
        sa.Column("extraction_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    op.create_index("ix_project_documents_project_id", "project_documents", ["project_id"])

    op.create_table(
        "plot_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("width_m", sa.Float(), nullable=False),
        sa.Column("height_m", sa.Float(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("rotation_deg", sa.Float(), nullable=False),
        sa.Column("street_width_m", sa.Float(), nullable=True),
        sa.Column("boundaries_json", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("corrections_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.UniqueConstraint("project_id"),
    )

    op.create_table(
        "design_briefs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("answers_json", sa.Text(), nullable=False),
        sa.Column("character_json", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.UniqueConstraint("project_id"),
    )

    op.create_table(
        "room_programs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("counts_json", sa.Text(), nullable=False),
        sa.Column("validation_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.UniqueConstraint("project_id"),
    )

    op.create_table(
        "design_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("support_status", sa.String(length=40), nullable=True),
        sa.Column("design_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("assumptions_json", sa.Text(), nullable=True),
        sa.Column("unapplied_answers_json", sa.Text(), nullable=True),
        sa.Column("unsupported_json", sa.Text(), nullable=True),
        sa.Column("character_json", sa.Text(), nullable=True),
        sa.Column("engine_summary_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    op.create_index("ix_design_runs_project_id", "design_runs", ["project_id"])

    op.create_table(
        "design_run_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["design_runs.id"]),
    )
    op.create_index("ix_design_run_events_run_id", "design_run_events", ["run_id"])

    op.create_table(
        "output_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("relative_path", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("shareable", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["design_runs.id"]),
    )
    op.create_index("ix_output_files_run_id", "output_files", ["run_id"])

    op.create_table(
        "presentation_renders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("design_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("relative_path", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=64), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["design_runs.id"]),
    )
    op.create_index("ix_presentation_renders_run_id", "presentation_renders", ["run_id"])

    op.create_table(
        "share_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_share_tokens_project_id", "share_tokens", ["project_id"])

    op.create_table(
        "pricing_configurations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # One active demo price so GET /api/v1/pricing/current works out of the
    # box. Demo configuration, not a real commercial offer.
    op.execute(
        sa.text(
            "INSERT INTO pricing_configurations "
            "(id, active, label, currency, amount, updated_at) "
            "VALUES (:id, :active, :label, :currency, :amount, CURRENT_TIMESTAMP)"
        ).bindparams(
            id=str(uuid.uuid4()),
            active=True,
            label="demo_concept_package",
            currency="SAR",
            amount=18000.0,
        )
    )


def downgrade() -> None:
    for index, table in (
        ("ix_share_tokens_project_id", "share_tokens"),
        ("ix_presentation_renders_run_id", "presentation_renders"),
        ("ix_output_files_run_id", "output_files"),
        ("ix_design_run_events_run_id", "design_run_events"),
        ("ix_design_runs_project_id", "design_runs"),
        ("ix_project_documents_project_id", "project_documents"),
    ):
        op.drop_index(index, table_name=table)
    for table in (
        "pricing_configurations",
        "share_tokens",
        "presentation_renders",
        "output_files",
        "design_run_events",
        "design_runs",
        "room_programs",
        "design_briefs",
        "plot_records",
        "project_documents",
    ):
        op.drop_table(table)
