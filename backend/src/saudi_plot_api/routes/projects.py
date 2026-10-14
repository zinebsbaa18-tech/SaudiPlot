"""Project endpoints, scoped to the current anonymous session.

A project belongs to exactly one session. Requests for a project owned by a
different session return 404 -- existence is never leaked.
"""

from __future__ import annotations

from fastapi import APIRouter

from saudi_plot_api.dependencies import (
    CurrentSessionDep,
    DbDep,
    TrustedOriginDep,
    owned_project,
)
from saudi_plot_api.schemas import ProjectCreate, ProjectPatch, ProjectResponse
from saudi_plot_api.services.projects import create_project, patch_project

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=201, dependencies=[TrustedOriginDep])
def create(payload: ProjectCreate, session: CurrentSessionDep, db: DbDep) -> ProjectResponse:
    project = create_project(db, session_id=session.id, current_step=payload.current_step)
    return ProjectResponse.model_validate(project)


def _owned_project(db: DbDep, session: CurrentSessionDep, project_id: str):
    return owned_project(db, session, project_id)


@router.get("/{project_id}", response_model=ProjectResponse)
def read(project_id: str, session: CurrentSessionDep, db: DbDep) -> ProjectResponse:
    return ProjectResponse.model_validate(_owned_project(db, session, project_id))


@router.patch("/{project_id}", response_model=ProjectResponse, dependencies=[TrustedOriginDep])
def patch(
    project_id: str, payload: ProjectPatch, session: CurrentSessionDep, db: DbDep
) -> ProjectResponse:
    project = _owned_project(db, session, project_id)
    project = patch_project(db, project, payload.updates())
    return ProjectResponse.model_validate(project)
