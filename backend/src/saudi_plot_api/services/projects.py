"""Project service: persistence scoped to the owning anonymous session.

Every read/update is filtered by ``session_id`` so a project from another
session is indistinguishable from a missing one (routes turn that into 404).
"""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from saudi_plot_api.database import utcnow
from saudi_plot_api.models import Project

PROJECT_SCHEMA_VERSION = 1


def create_project(db: Session, session_id: str, current_step: str | None) -> Project:
    project = Project(
        session_id=session_id,
        current_step=current_step,
        schema_version=PROJECT_SCHEMA_VERSION,
    )
    db.add(project)
    db.commit()
    return project


def get_project(db: Session, session_id: str, project_id: str) -> Project | None:
    return db.execute(
        select(Project).where(Project.id == project_id, Project.session_id == session_id)
    ).scalar_one_or_none()


def patch_project(db: Session, project: Project, updates: Mapping[str, str | None]) -> Project:
    """Apply the fields the client actually sent (explicit null clears a
    nullable field) -- an accepted answer is never silently ignored."""
    changed = False
    if "status" in updates and updates["status"] != project.status:
        project.status = updates["status"]
        changed = True
    if "current_step" in updates and updates["current_step"] != project.current_step:
        project.current_step = updates["current_step"]
        changed = True
    if changed:
        project.updated_at = utcnow()
        db.commit()
    return project
