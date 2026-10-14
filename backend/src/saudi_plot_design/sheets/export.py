"""Write and hash deterministic M6.3 architectural sheet artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from saudi_plot_design.model import SpdInputError
from saudi_plot_design.output import DISCLAIMER
from saudi_plot_design.sheets.engine import build_architectural_sheets
from saudi_plot_design.sheets.graphics import write_sheet_pdf, write_sheet_svg
from saudi_plot_design.sheets.models import (
    GRAPHIC_PROFILE,
    SHEET_ENGINE_VERSION,
    SHEET_SCHEMA_VERSION,
    ArchitecturalSheetExport,
    SheetSetMode,
)

CONCEPT_PDF = "architectural_concept_sheet_set.pdf"
REVIEW_PDF = "architectural_review_sheet_set.pdf"
SHEET_INDEX = "architectural_sheet_index.json"
SHEET_MANIFEST = "architectural_sheet_manifest.json"
COLLISION_REPORT = "annotation_collision_report.json"


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: str | Path, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def export_architectural_sheets(
    out_dir: str | Path,
    *,
    plot,
    envelope,
    rules,
    concept,
    facade,
    pack_ref,
    pack_data,
    quality_assessment,
    candidate_id: str,
    generation_timestamp: str,
    mode: SheetSetMode,
) -> ArchitecturalSheetExport:
    """Generate the selected professional sheet mode inside a staging root."""
    if mode == "none":
        raise ValueError("sheet export must not be called with mode='none'")
    issue_date = generation_timestamp[:10]
    build = build_architectural_sheets(
        plot=plot,
        envelope=envelope,
        rules=rules,
        concept=concept,
        facade=facade,
        pack_ref=pack_ref,
        pack_data=pack_data,
        quality_assessment=quality_assessment,
        candidate_id=candidate_id,
        issue_date=issue_date,
        mode=mode,
        profile=GRAPHIC_PROFILE,
    )
    if not build.validation.passed:
        failed = [
            str(check["id"]) for check in build.validation.checks if not bool(check["passed"])
        ]
        raise SpdInputError("sheet export blocked: validation failed: " + ", ".join(failed))

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[Path] = []
    svg_paths: list[Path] = []
    for relative_name, page in build.individual_pages:
        path = write_sheet_svg(out_dir / relative_name, page, build.profile)
        artifacts.append(path)
        svg_paths.append(path)

    concept_pdf_path: Path | None = None
    review_pdf_path: Path | None = None
    if mode in {"concept", "all"}:
        concept_pdf_path = write_sheet_pdf(
            out_dir / CONCEPT_PDF,
            build.concept_pages,
            build.profile,
            title="Saudi Plot Design - Architectural Concept Sheet Set",
            candidate_id=candidate_id,
            geometry_fingerprint=build.concept_pages[0].geometry_fingerprint,
        )
        artifacts.append(concept_pdf_path)
    if mode in {"review", "all"}:
        review_pdf_path = write_sheet_pdf(
            out_dir / REVIEW_PDF,
            build.review_pages,
            build.profile,
            title="Saudi Plot Design - Architectural Design Review Sheet Set",
            candidate_id=candidate_id,
            geometry_fingerprint=build.review_pages[0].geometry_fingerprint,
        )
        artifacts.append(review_pdf_path)

    index_payload = {
        "schema_version": SHEET_SCHEMA_VERSION,
        "sheet_engine_version": SHEET_ENGINE_VERSION,
        "disclaimer": DISCLAIMER,
        "graphic_profile": asdict(build.profile),
        "sheet_set_mode": mode,
        "source_candidate_id": candidate_id,
        "source_geometry_fingerprint": build.concept_pages[0].geometry_fingerprint,
        "sheets": [asdict(entry) for entry in build.index_entries],
        "pdf_sets": {
            "concept": {
                "filename": CONCEPT_PDF if concept_pdf_path else None,
                "page_order": [page.number for page in build.concept_pages]
                if concept_pdf_path
                else [],
            },
            "review": {
                "filename": REVIEW_PDF if review_pdf_path else None,
                "page_order": [page.number for page in build.review_pages]
                if review_pdf_path
                else [],
            },
        },
    }
    index_path = _write_json(out_dir / SHEET_INDEX, index_payload)
    artifacts.append(index_path)

    collision_payload = {
        "schema_version": SHEET_SCHEMA_VERSION,
        "sheet_engine_version": SHEET_ENGINE_VERSION,
        "disclaimer": DISCLAIMER,
        "source_candidate_id": candidate_id,
        "source_geometry_fingerprint": build.concept_pages[0].geometry_fingerprint,
        "annotation_collisions": [asdict(record) for record in build.collisions],
        "summary": {
            "reported_conditions": len(build.collisions),
            "unresolved_collisions": sum(record.unresolved for record in build.collisions),
            "required_annotations_silently_omitted": 0,
        },
        "concept_furniture": [asdict(record) for record in build.furniture],
    }
    collision_path = _write_json(out_dir / COLLISION_REPORT, collision_payload)
    artifacts.append(collision_path)

    records = {
        _relative(path, out_dir): {
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for path in sorted(artifacts, key=lambda item: _relative(item, out_dir))
    }
    manifest_payload = {
        "schema_version": SHEET_SCHEMA_VERSION,
        "sheet_engine_version": SHEET_ENGINE_VERSION,
        "disclaimer": DISCLAIMER,
        "graphic_profile_id": build.profile.profile_id,
        "sheet_set_mode": mode,
        "source_candidate_id": candidate_id,
        "source_geometry_fingerprint": build.concept_pages[0].geometry_fingerprint,
        "paper": {
            "size": build.profile.paper_size,
            "orientation": build.profile.orientation,
            "width_mm": build.profile.paper_width_mm,
            "height_mm": build.profile.paper_height_mm,
        },
        "pdf_page_order": {
            "concept": [page.number for page in build.concept_pages] if concept_pdf_path else [],
            "review": [page.number for page in build.review_pages] if review_pdf_path else [],
        },
        "validation": {
            "status": "all_sheet_checks_passed",
            "checks": list(build.validation.checks),
            "annotation_collision_count": len(build.collisions),
            "unresolved_annotation_collision_count": sum(
                record.unresolved for record in build.collisions
            ),
        },
        "artifacts": records,
    }
    _write_json(out_dir / SHEET_MANIFEST, manifest_payload)
    return ArchitecturalSheetExport(
        mode=mode,
        profile_id=build.profile.profile_id,
        output_paths=tuple(sorted((*records, SHEET_MANIFEST))),
        concept_pdf_path=CONCEPT_PDF if concept_pdf_path else None,
        review_pdf_path=REVIEW_PDF if review_pdf_path else None,
        sheet_index_path=SHEET_INDEX,
        sheet_manifest_path=SHEET_MANIFEST,
        collision_report_path=COLLISION_REPORT,
        svg_paths=tuple(_relative(path, out_dir) for path in svg_paths),
        sheet_numbers=tuple(entry.sheet_number for entry in build.index_entries),
        validation_status="all_sheet_checks_passed",
        collision_count=len(build.collisions),
        unresolved_collision_count=sum(record.unresolved for record in build.collisions),
    )


def verify_sheet_manifest(root: str | Path) -> tuple[str, ...]:
    """Return deterministic validation errors for a generated sheet manifest."""
    root = Path(root)
    payload = json.loads((root / SHEET_MANIFEST).read_text(encoding="utf-8"))
    errors: list[str] = []
    for name, expected in payload["artifacts"].items():
        path = root / name
        if not path.is_file():
            errors.append(f"missing artifact: {name}")
            continue
        if path.stat().st_size != expected["size_bytes"]:
            errors.append(f"size mismatch: {name}")
        if _sha256_file(path) != expected["sha256"]:
            errors.append(f"hash mismatch: {name}")
    return tuple(errors)


__all__ = [
    "COLLISION_REPORT",
    "CONCEPT_PDF",
    "REVIEW_PDF",
    "SHEET_INDEX",
    "SHEET_MANIFEST",
    "export_architectural_sheets",
    "verify_sheet_manifest",
]
