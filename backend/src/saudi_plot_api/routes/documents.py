"""Deed document endpoints: upload to the backend, server-side extraction."""

from __future__ import annotations

import json

from fastapi import APIRouter, UploadFile
from sqlalchemy import select

from saudi_plot_api.dependencies import (
    CurrentSessionDep,
    DbDep,
    SettingsDep,
    TrustedOriginDep,
    owned_project,
)
from saudi_plot_api.errors import ApiError
from saudi_plot_api.models import Project, ProjectDocument
from saudi_plot_api.schemas import DocumentResponse, ExtractionResponse
from saudi_plot_api.services.documents import run_extraction, store_deed_upload

router = APIRouter(prefix="/api/v1", tags=["documents"])


@router.post(
    "/projects/{project_id}/documents",
    response_model=ExtractionResponse,
    status_code=201,
    dependencies=[TrustedOriginDep],
)
def upload_document(
    project_id: str,
    file: UploadFile,
    session: CurrentSessionDep,
    db: DbDep,
    settings: SettingsDep,
) -> ExtractionResponse:
    """Store the deed and run server-side extraction in the same request.

    The response carries the extraction result (or a structured error code);
    the stored document survives extraction failure, and manual entry remains
    fully available."""
    owned_project(db, session, project_id)
    data = file.file.read(settings.upload_max_bytes + 1)
    document = store_deed_upload(
        db,
        settings,
        project_id,
        original_filename=file.filename or "deed",
        content_type=file.content_type or "application/octet-stream",
        data=data,
    )
    document = run_extraction(db, settings, document)
    return _extraction_response(document)


def _owned_document(db: DbDep, session: CurrentSessionDep, document_id: str) -> ProjectDocument:
    document = db.execute(
        select(ProjectDocument)
        .join(Project, Project.id == ProjectDocument.project_id)
        .where(ProjectDocument.id == document_id, Project.session_id == session.id)
    ).scalar_one_or_none()
    if document is None:
        raise ApiError(404, "document_not_found", "The document does not exist.")
    return document


def _extraction_response(document: ProjectDocument) -> ExtractionResponse:
    return ExtractionResponse(
        document_id=document.id,
        status=document.status,
        extraction=json.loads(document.extraction_json) if document.extraction_json else None,
        error_code=document.extraction_error_code,
    )


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def read_document(document_id: str, session: CurrentSessionDep, db: DbDep) -> DocumentResponse:
    return DocumentResponse.model_validate(_owned_document(db, session, document_id))


@router.get("/documents/{document_id}/extraction", response_model=ExtractionResponse)
def read_extraction(document_id: str, session: CurrentSessionDep, db: DbDep) -> ExtractionResponse:
    return _extraction_response(_owned_document(db, session, document_id))
