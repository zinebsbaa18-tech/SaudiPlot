"""Confined file storage.

Every stored file lives under ``settings.storage_root`` with a
server-generated name; user input never becomes part of a filesystem path.
``resolve_relative`` re-verifies confinement on every read, so even a
corrupted database row cannot escape the root.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

# The only upload types the demo accepts (deed PDF or image).
UPLOAD_MIME_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


class StorageError(Exception):
    pass


def storage_root(root: Path) -> Path:
    resolved = root.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def new_stored_name(content_type: str) -> str:
    """Server-generated file name: random hex + extension derived from the
    validated MIME type. No user-controlled characters."""
    try:
        extension = UPLOAD_MIME_EXTENSIONS[content_type]
    except KeyError:
        raise StorageError(f"unsupported content type: {content_type}") from None
    return uuid.uuid4().hex + extension


def resolve_relative(root: Path, relative_path: str) -> Path:
    """Resolve a stored relative path, refusing anything outside the root."""
    if not relative_path or "\x00" in relative_path:
        raise StorageError("empty or invalid storage path")
    # Reject backslashes unconditionally: on Linux they are valid filename
    # characters (not separators), so Path("..\\evil") is a single component
    # that would slip past the traversal check below.
    if "\\" in relative_path:
        raise StorageError("storage path contains invalid characters")
    candidate = Path(relative_path)
    if candidate.is_absolute() or any(len(part) > 1 and part[1] == ":" for part in candidate.parts):
        raise StorageError("absolute storage paths are not allowed")
    resolved = (storage_root(root) / candidate).resolve()
    if not resolved.is_relative_to(storage_root(root)):
        raise StorageError("storage path escapes the storage root")
    return resolved


def write_bytes(root: Path, relative_path: str, data: bytes) -> tuple[str, int]:
    """Write data at a confined relative path; returns (sha256, size)."""
    target = resolve_relative(root, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return hashlib.sha256(data).hexdigest(), len(data)


def file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def document_relative_path(project_id: str, stored_name: str) -> str:
    return f"projects/{project_id}/documents/{stored_name}"


def run_relative_dir(project_id: str, run_id: str) -> str:
    return f"projects/{project_id}/runs/{run_id}"


def render_relative_path(project_id: str, run_id: str, stored_name: str) -> str:
    return f"projects/{project_id}/renders/{run_id}/{stored_name}"
