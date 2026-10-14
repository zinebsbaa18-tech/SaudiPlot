"""Deed document intake: validated upload, confined storage, extraction.

The browser uploads the file to this backend only; all Gemini processing is
server-side. File names are server-generated; the original filename is kept
as display metadata only and never used in a path.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from saudi_plot_api.config import Settings
from saudi_plot_api.errors import ApiError
from saudi_plot_api.models import ProjectDocument
from saudi_plot_api.services import gemini, storage


def store_deed_upload(
    db: Session,
    settings: Settings,
    project_id: str,
    original_filename: str,
    content_type: str,
    data: bytes,
) -> ProjectDocument:
    if content_type not in storage.UPLOAD_MIME_EXTENSIONS:
        raise ApiError(
            415,
            "unsupported_file_type",
            "Only PDF, JPEG, or PNG deed files are accepted.",
            {"allowed": sorted(storage.UPLOAD_MIME_EXTENSIONS)},
        )
    if len(data) == 0:
        raise ApiError(422, "empty_file", "The uploaded file is empty.")
    if len(data) > settings.upload_max_bytes:
        raise ApiError(
            413,
            "file_too_large",
            "The uploaded file exceeds the size limit.",
            {"max_bytes": settings.upload_max_bytes},
        )

    stored_name = storage.new_stored_name(content_type)
    relative = storage.document_relative_path(project_id, stored_name)
    digest, size = storage.write_bytes(settings.storage_root, relative, data)
    document = ProjectDocument(
        project_id=project_id,
        kind="deed",
        original_filename=(original_filename or "deed")[:255],
        stored_name=stored_name,
        relative_path=relative,
        content_type=content_type,
        size_bytes=size,
        sha256=digest,
        status="uploaded",
    )
    db.add(document)
    db.commit()
    return document


def run_extraction(db: Session, settings: Settings, document: ProjectDocument) -> ProjectDocument:
    """Extract the stored deed server-side. Structured failure codes; the
    stored document survives either way, and manual entry stays available."""
    document.status = "extracting"
    db.commit()
    try:
        path = storage.resolve_relative(settings.storage_root, document.relative_path)
        result = gemini.extract_deed(settings, path.read_bytes(), document.content_type)
    except gemini.GeminiUnavailable:
        document.status = "extraction_failed"
        document.extraction_error_code = "extraction_unconfigured"
        db.commit()
        return document
    except gemini.GeminiError as error:
        document.status = "extraction_failed"
        document.extraction_error_code = error.code
        db.commit()
        return document
    except Exception:
        # Whatever goes wrong, the document must land in a terminal state --
        # never stuck at "extracting".
        document.status = "extraction_failed"
        document.extraction_error_code = "extraction_internal_error"
        db.commit()
        raise

    document.status = "extracted"
    document.extraction_json = json.dumps(result, ensure_ascii=False)
    document.extraction_error_code = None
    db.commit()
    return document
