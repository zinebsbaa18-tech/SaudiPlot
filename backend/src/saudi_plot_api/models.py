"""ORM models for W1: anonymous sessions and projects.

Deliberately no personal deed fields yet (WEB_BACKEND_SCOPE.md). Session tokens
are never stored — only their SHA-256 hash.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from saudi_plot_api.database import Base, UTCDateTime, utcnow

SESSION_STATUS_ACTIVE = "active"
SESSION_STATUS_EXPIRED = "expired"

PROJECT_STATUSES = ("draft", "in_progress", "completed")

# The only steps a project may point at: the frozen frontend journey
# (docs/FROZEN_FRONTEND_CONTRACT.md §1). The backend adapts to the accepted UI;
# it never invents steps of its own.
FROZEN_FRONTEND_STEPS = (
    "landing",
    "upload",
    "manual-entry",
    "confirm-data",
    "questions/1",
    "questions/2",
    "questions/3",
    "questions/4",
    "questions/5",
    "questions/6",
    "room-catalog",
    "generating",
    "result-3d",
)


def new_id() -> str:
    return str(uuid.uuid4())


class AnonymousSession(Base):
    __tablename__ = "anonymous_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=SESSION_STATUS_ACTIVE)

    projects: Mapped[list[Project]] = relationship(back_populates="session")


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_session_id", "session_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("anonymous_sessions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    current_step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    session: Mapped[AnonymousSession] = relationship(back_populates="projects")


# ── Demo journey (W2) ───────────────────────────────────────────────────────

DOCUMENT_STATUSES = ("uploaded", "extracting", "extracted", "extraction_failed")

DESIGN_RUN_STATUSES = (
    "preparing_inputs",
    "extracting_deed",
    "resolving_character",
    "validating_requirements",
    "generating_candidates",
    "evaluating_candidates",
    "preparing_outputs",
    "generating_presentation_render",
    "completed",
    "completed_with_assumptions",
    "unsupported_requirements",
    "failed",
)
DESIGN_RUN_TERMINAL_STATUSES = (
    "completed",
    "completed_with_assumptions",
    "unsupported_requirements",
    "failed",
)

SUPPORT_STATUSES = ("supported", "supported_with_assumptions", "unsupported_requirements")

RENDER_STATUSES = ("pending", "completed", "failed", "unconfigured")


class ProjectDocument(Base):
    __tablename__ = "project_documents"
    __table_args__ = (Index("ix_project_documents_project_id", "project_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="deed")
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(64), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="uploaded")
    extraction_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class PlotRecord(Base):
    __tablename__ = "plot_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False, unique=True
    )
    width_m: Mapped[float] = mapped_column(Float, nullable=False)
    height_m: Mapped[float] = mapped_column(Float, nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    rotation_deg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    street_width_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    boundaries_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    # User corrections against the immutable extraction result live here,
    # never inside project_documents.extraction_json.
    corrections_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class DesignBrief(Base):
    __tablename__ = "design_briefs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False, unique=True
    )
    answers_json: Mapped[str] = mapped_column(Text, nullable=False)
    character_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class RoomProgram(Base):
    __tablename__ = "room_programs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False, unique=True
    )
    counts_json: Mapped[str] = mapped_column(Text, nullable=False)
    validation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class DesignRun(Base):
    __tablename__ = "design_runs"
    __table_args__ = (Index("ix_design_runs_project_id", "project_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="preparing_inputs")
    support_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    design_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assumptions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    unapplied_answers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    unsupported_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    character_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class DesignRunEvent(Base):
    __tablename__ = "design_run_events"
    __table_args__ = (Index("ix_design_run_events_run_id", "run_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("design_runs.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class OutputFile(Base):
    __tablename__ = "output_files"
    __table_args__ = (Index("ix_output_files_run_id", "run_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("design_runs.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # True for outputs safe to expose through a share link (no deed/owner
    # data, no input echoes) -- everything else stays private to the session.
    shareable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class PresentationRender(Base):
    __tablename__ = "presentation_renders"
    __table_args__ = (Index("ix_presentation_renders_run_id", "run_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("design_runs.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    provider: Mapped[str] = mapped_column(String(24), nullable=False, default="gemini")
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    design_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    relative_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class ShareToken(Base):
    __tablename__ = "share_tokens"
    __table_args__ = (Index("ix_share_tokens_project_id", "project_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PricingConfiguration(Base):
    __tablename__ = "pricing_configurations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="SAR")
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
