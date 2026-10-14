"""Case metadata loading, usage-rights gate, and anonymization (M6A).

Confidential source files are NEVER copied into tracked paths: this module
only reads from the private source directory and scrubs sensitive values
from everything that leaves it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import ValidationError

from saudi_plot_design.cases.models import CaseMetadata
from saudi_plot_design.model import SpdInputError

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
# Sensitive free-text markers that must not survive anonymization.
_SENSITIVE_LINE = re.compile(
    r"(?i)\b(client|owner|مالك|العميل|address|عنوان|price|cost|SAR|riyal|ريال)\b[^\n]*"
)

ANONYMIZED = "[REDACTED]"


def load_case_metadata(source_dir: str | Path) -> CaseMetadata:
    path = Path(source_dir) / "case_metadata.json"
    if not path.is_file():
        raise SpdInputError(f"case metadata not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpdInputError(f"case metadata is not valid JSON: {exc}") from None
    try:
        metadata = CaseMetadata.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(loc) for loc in first["loc"]) or "<root>"
        raise SpdInputError(f"case metadata rejected at '{field}': {first['msg']}") from None
    return metadata


def enforce_usage_rights(metadata: CaseMetadata) -> None:
    """Hard gate: no ingestion without explicitly confirmed usage rights."""
    if metadata.usage_rights_confirmed is not True:
        raise SpdInputError(
            f"case '{metadata.case_id}': usage_rights_confirmed is not true - "
            f"ingestion is blocked until the rights holder explicitly confirms "
            f"permitted usage"
        )


def anonymize_text(text: str) -> str:
    """Scrub emails, phone numbers, and sensitive free-text markers."""
    text = _EMAIL.sub(ANONYMIZED, text)
    text = _PHONE.sub(ANONYMIZED, text)
    text = _SENSITIVE_LINE.sub(ANONYMIZED, text)
    return text


def anonymize_metadata(metadata: CaseMetadata) -> CaseMetadata:
    """Apply anonymization when required: scrub notes, drop the district."""
    if not metadata.anonymization_required:
        return metadata
    return metadata.model_copy(
        update={
            "notes": anonymize_text(metadata.notes),
            "district": None,
            "approved_by": ANONYMIZED if metadata.approved_by else None,
        }
    )


def safe_source_display(source_dir: str | Path, metadata: CaseMetadata) -> str:
    """The path recorded in outputs: never leaks beyond the case folder name,
    and never includes the folder name at all when the case is confidential
    (folder names conventionally carry the project code)."""
    if metadata.confidential:
        return "private_cases/<confidential>"
    return f"private_cases/{Path(source_dir).name}"
