"""Sanitized M7.1 fixture builders.

TEST DATA ONLY. The synthetic villa is not a real project, not a professional
design, and must never be represented as either. It exists solely to exercise
the explicit architect-review and approved-template gates.
"""

from __future__ import annotations

from pathlib import Path

from m6a_ifc_fixture import build_case_dir

from saudi_plot_design.cases.models import ArchitecturalDesignCase
from saudi_plot_design.cases.pipeline import ingest_case
from saudi_plot_design.library.commands import apply_review, import_m6a_artifacts
from saudi_plot_design.library.models import (
    CaseRole,
    CreationMetadata,
    ReviewDecisionType,
)


def metadata(at: str, source: str = "m7_synthetic_test_fixture") -> CreationMetadata:
    return CreationMetadata(created_at=at, created_by="M7 test builder", source=source)


def build_synthetic_villa_artifacts(root: Path):
    source = build_case_dir(
        root / "synthetic-villa-source",
        case_id="SYNTHETIC-VILLA-TEST-001",
        project_type="residential_villa",
        case_role="residential_villa_template_candidate",
        country="SA",
        city="Riyadh",
        architectural_character="najdi",
        approval_status="synthetic_test_fixture_only",
        approved_by="Test Reviewer",
        quality_rating="synthetic_test_fixture",
        notes=(
            "Synthetic test fixture only - not a real project, not a professional "
            "design, and not evidence of architectural quality."
        ),
    )
    artifacts = root / "synthetic-villa-artifacts"
    case = ingest_case(source, artifacts)
    return source, artifacts, case


def build_office_stress_artifacts(root: Path):
    source = build_case_dir(
        root / "office-source",
        case_id="TEST-OFFICE-001",
        project_type="mixed_use_office_building",
        case_role="ingestion_stress_test",
        country="Finland",
        city="undisclosed",
        architectural_character="not_applicable_for_saudi_villa_training",
        notes=(
            "Non-residential ingestion stress-test. Do not use as a Saudi "
            "residential-villa template."
        ),
    )
    artifacts = root / "office-artifacts"
    case = ingest_case(source, artifacts)
    return source, artifacts, case


def build_reference_library(
    library_root: Path,
    work_root: Path,
    *,
    office_artifacts: Path | None = None,
    villa_artifacts: Path | None = None,
):
    if office_artifacts is None:
        _, office_artifacts, office_case = build_office_stress_artifacts(work_root)
    else:
        office_case = None
    office_package, _ = import_m6a_artifacts(
        library_root=library_root,
        artifact_root=office_artifacts,
        case_version="1.0.0",
        case_role=CaseRole.INGESTION_STRESS_TEST,
        creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
        template_use_permitted=False,
        shareable_outputs_permitted=False,
        rights_basis="internal ingestion and validation testing only",
    )
    if villa_artifacts is None:
        _, villa_artifacts, villa_case = build_synthetic_villa_artifacts(work_root)
    else:
        villa_case = ArchitecturalDesignCase.model_validate_json(
            (villa_artifacts / "architectural_case.json").read_text(encoding="utf-8")
        )
    candidate, _ = import_m6a_artifacts(
        library_root=library_root,
        artifact_root=villa_artifacts,
        case_version="1.0.0",
        case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
        creation_metadata=metadata("2026-07-16T08:01:00+03:00"),
        template_use_permitted=True,
        shareable_outputs_permitted=True,
        rights_basis="synthetic fixture explicitly permitted for automated tests",
        synthetic_test_fixture=True,
    )
    approved, _ = apply_review(
        library_root=library_root,
        case_id=candidate.case_id,
        from_version=candidate.case_version,
        new_version="1.1.0",
        decision_type=ReviewDecisionType.APPROVED,
        reviewer_id="synthetic-test-reviewer",
        review_date="2026-07-16",
        bound_fingerprint=candidate.review_binding_fingerprint,
        rationale="Approved only for deterministic automated library tests.",
        template_use_approved=True,
        creation_metadata=metadata("2026-07-16T08:02:00+03:00"),
    )
    return {
        "office_package": office_package,
        "office_case": office_case,
        "candidate": candidate,
        "approved": approved,
        "villa_case": villa_case,
    }
