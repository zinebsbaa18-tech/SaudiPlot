"""M7.2 villa intake, architect-review package, corrections, and decisions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

pytest.importorskip("ifcopenshell")

from m7_library_fixture import (
    build_reference_library,
    build_synthetic_villa_artifacts,
    metadata,
)

from saudi_plot_design.library.commands import (
    apply_architect_corrections,
    apply_architect_decision,
    import_m6a_artifacts,
    review_status_payload,
)
from saudi_plot_design.library.models import (
    SYNTHETIC_FIXTURE_DISCLAIMER,
    CaseRole,
    LifecycleState,
    ReviewState,
)
from saudi_plot_design.library.review import (
    REVIEW_PACKAGE_FILES,
    _spreadsheet_safe,
    feature_map,
    prepare_review_package,
    validate_review_package,
)
from saudi_plot_design.library.storage import load_case_version
from saudi_plot_design.model import SpdInputError

REVIEWER = "synthetic-test-reviewer"
REVIEW_DATE = "2026-07-17"


@pytest.fixture(scope="module")
def reference(tmp_path_factory):
    root = tmp_path_factory.mktemp("m7-2-reference")
    library = root / "library"
    context = build_reference_library(library, root / "work")
    package_dir = root / "review-package"
    manifest = prepare_review_package(
        library,
        package_dir,
        case_id=context["approved"].case_id,
        case_version="1.1.0",
    )
    return library, context, package_dir, manifest


@pytest.fixture()
def candidate_library(tmp_path):
    """A fresh library holding only the villa candidate 1.0.0."""
    _, artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    library = tmp_path / "library"
    candidate, _ = import_m6a_artifacts(
        library_root=library,
        artifact_root=artifacts,
        case_version="1.0.0",
        case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
        creation_metadata=metadata("2026-07-17T08:00:00+03:00"),
        template_use_permitted=True,
        shareable_outputs_permitted=True,
        rights_basis="synthetic fixture explicitly permitted for automated tests",
        synthetic_test_fixture=True,
    )
    return library, candidate


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _csv_rows(path: Path) -> list[dict]:
    import csv

    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _correction(ctype: str, target: str, old, new, **overrides) -> dict:
    record = {
        "correction_type": ctype,
        "target_id": target,
        "old_value": old,
        "new_value": new,
        "reviewer_id": REVIEWER,
        "review_date": REVIEW_DATE,
        "reason": "architect correction for deterministic automated tests",
        "source_evidence": "review of the plan preview drawing",
    }
    record.update(overrides)
    return record


def _write_corrections(path: Path, package, corrections: list[dict], **overrides) -> Path:
    document = {
        "corrections_schema_version": 1,
        "case_id": package.case_id,
        "case_version": package.case_version,
        "review_binding_fingerprint": package.review_binding_fingerprint,
        "corrections": corrections,
        "notes": "",
    }
    document.update(overrides)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_decision(path: Path, package, decision: str, **overrides) -> Path:
    document = {
        "decision_schema_version": 1,
        "case_id": package.case_id,
        "case_version": package.case_version,
        "decision": decision,
        "reviewer_id": REVIEWER,
        "review_date": REVIEW_DATE,
        "bound_fingerprint": package.review_binding_fingerprint,
        "template_use_approved": decision == "approved_template",
        "rationale": "Deterministic automated review-workflow test decision.",
    }
    document.update(overrides)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _room_target(library: Path, case_id: str, version: str) -> tuple[str, str]:
    _, _, features = load_case_version(library, case_id, version)
    room = (feature_map(features)["room_geometry.rooms"])[0]
    return str(room["room_id"]), str(room["room_type"])


def _entrance_target(library: Path, case_id: str, version: str) -> tuple[str, str]:
    _, _, features = load_case_version(library, case_id, version)
    entrance = (feature_map(features)["entrances.inventory"])[0]
    return str(entrance["door_id"]), str(entrance["entrance_type"])


# Review package -----------------------------------------------------------


def test_review_package_contains_required_files(reference):
    _, _, package_dir, _ = reference
    names = sorted(path.name for path in package_dir.iterdir())
    assert names == sorted(REVIEW_PACKAGE_FILES)


def test_review_package_is_deterministic(reference, tmp_path):
    library, context, package_dir, _ = reference
    again = tmp_path / "again"
    prepare_review_package(
        library, again, case_id=context["approved"].case_id, case_version="1.1.0"
    )
    for name in REVIEW_PACKAGE_FILES:
        assert (again / name).read_bytes() == (package_dir / name).read_bytes(), name


def test_review_package_manifest_integrity(reference):
    _, _, package_dir, manifest = reference
    assert validate_review_package(package_dir) == ()
    payload = _read(package_dir / "review_package_manifest.json")
    for record in payload["artifacts"]:
        path = package_dir / record["relative_path"]
        assert path.stat().st_size == record["size_bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
    assert payload["review_binding_fingerprint"] == manifest.review_binding_fingerprint


def test_tampered_review_package_fails_validation(reference, tmp_path):
    library, context, _, _ = reference
    package_dir = tmp_path / "tampered"
    prepare_review_package(
        library, package_dir, case_id=context["approved"].case_id, case_version="1.1.0"
    )
    (package_dir / "rooms_review.csv").write_bytes(b"tampered\n")
    errors = validate_review_package(package_dir)
    assert any("hash mismatch: rooms_review.csv" in error for error in errors)
    manifest_path = package_dir / "review_package_manifest.json"
    payload = _read(manifest_path)
    payload["generated_at"] = "2030-01-01T00:00:00+00:00"
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    errors = validate_review_package(package_dir)
    assert errors and "root fingerprint" in errors[0]


def test_intake_summary_shows_identity_program_and_eligibility(reference):
    _, context, package_dir, _ = reference
    summary = (package_dir / "intake_summary.md").read_text(encoding="utf-8")
    approved = context["approved"]
    assert f"`{approved.case_id}`" in summary
    assert "`1.1.0`" in summary
    assert "`residential_villa`" in summary
    assert "Bedrooms:" in summary
    assert "Majlis present:" in summary
    assert approved.review_binding_fingerprint in summary
    assert approved.source_bundle_fingerprint in summary
    assert "## Limitations" in summary


def test_synthetic_fixture_disclaimer_is_verbatim(reference):
    _, _, package_dir, _ = reference
    summary = (package_dir / "intake_summary.md").read_text(encoding="utf-8")
    assert SYNTHETIC_FIXTURE_DISCLAIMER in summary
    corrections = _read(package_dir / "architect_corrections_template.json")
    decision = _read(package_dir / "architect_review_decision_template.json")
    assert corrections["synthetic_test_fixture_disclaimer"] == SYNTHETIC_FIXTURE_DISCLAIMER
    assert decision["synthetic_test_fixture_disclaimer"] == SYNTHETIC_FIXTURE_DISCLAIMER
    assert SYNTHETIC_FIXTURE_DISCLAIMER == (
        "TEST DATA only. Not a real project, not a professional architectural design, "
        "and not evidence of regulatory, cultural, municipal, or permit approval."
    )


def test_residential_program_review_output(reference):
    _, _, package_dir, _ = reference
    rows = {row["item"]: row for row in _csv_rows(package_dir / "residential_program_review.csv")}
    assert int(rows["bedroom_count"]["value"]) >= 1
    assert int(rows["bathroom_count"]["value"]) >= 1
    assert rows["majlis_present"]["value"] == "true"
    assert rows["room_type_counts"]["status"] == "extracted"


def test_rooms_review_output(reference):
    _, _, package_dir, _ = reference
    rows = _csv_rows(package_dir / "rooms_review.csv")
    assert rows
    assert {"room_id", "room_type", "zone", "corrected_room_type", "corrected_zone"} <= set(rows[0])
    assert all(row["room_id"] for row in rows)


def test_entrances_review_output(reference):
    _, _, package_dir, _ = reference
    rows = _csv_rows(package_dir / "entrances_review.csv")
    assert rows
    assert all(row["actual_door_evidence"] == "true" for row in rows)
    assert any(row["entrance_type"] == "main_family_entrance" for row in rows)


def test_routes_review_output(reference):
    _, _, package_dir, _ = reference
    rows = {row["route_id"]: row for row in _csv_rows(package_dir / "routes_review.csv")}
    assert {"guest_route", "family_route", "service_route"} <= set(rows)
    assert any(key.startswith("entrance_route:") for key in rows)


def test_adjacency_review_output(reference):
    _, _, package_dir, _ = reference
    rows = _csv_rows(package_dir / "adjacency_review.csv")
    assert any(row["relationship"] == "room_adjacency" for row in rows)
    assert all("|" in row["pair_id"] for row in rows)


def test_wet_areas_review_output(reference):
    _, _, package_dir, _ = reference
    rows = _csv_rows(package_dir / "wet_areas_review.csv")
    assert all(row["room_ids"] for row in rows)


def test_quality_findings_review_output(reference):
    _, _, package_dir, _ = reference
    rows = {
        (row["finding"], row["value"])
        for row in _csv_rows(package_dir / "quality_findings_review.csv")
    }
    assert ("assessment_version", "not_evaluated") in rows


def test_intake_validation_report(reference):
    _, context, package_dir, _ = reference
    report = _read(package_dir / "intake_validation_report.json")
    assert report["case_id"] == context["approved"].case_id
    assert report["template_eligible"] is True
    assert report["source_validation_summary"]["passed"] is True


def test_prepare_review_dry_run_writes_nothing(reference, tmp_path, capsys):
    from saudi_plot_design.cli import main

    library, context, _, _ = reference
    out_dir = tmp_path / "never-written"
    result = main(
        [
            "library",
            "prepare-review",
            "--library-root",
            str(library),
            "--case-id",
            context["approved"].case_id,
            "--case-version",
            "1.1.0",
            "--out",
            str(out_dir),
            "--dry-run",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 0 and payload["disposition"] == "dry_run"
    assert not out_dir.exists()


def test_prepare_review_cli_json_and_validate_exit_codes(reference, tmp_path, capsys):
    from saudi_plot_design.cli import main

    library, context, _, _ = reference
    out_dir = tmp_path / "cli-package"
    result = main(
        [
            "library",
            "prepare-review",
            "--library-root",
            str(library),
            "--case-id",
            context["approved"].case_id,
            "--case-version",
            "1.1.0",
            "--out",
            str(out_dir),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 0 and payload["disposition"] == "written"
    assert payload["artifact_count"] == len(REVIEW_PACKAGE_FILES)
    result = main(["library", "validate-review-package", "--package", str(out_dir), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 0 and payload["passed"] is True
    (out_dir / "routes_review.csv").write_bytes(b"tampered\n")
    result = main(["library", "validate-review-package", "--package", str(out_dir), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 3 and payload["passed"] is False


def test_no_private_paths_or_sources_in_review_package(reference):
    library, _, package_dir, _ = reference
    serialized = "\n".join(
        (package_dir / name).read_text(encoding="utf-8") for name in REVIEW_PACKAGE_FILES
    ).replace("\\", "/")
    assert "private_cases/" not in serialized
    assert str(library).replace("\\", "/") not in serialized
    for suffix in ("*.ifc", "*.rvt", "*.dwg", "*.png", "*.pdf"):
        assert not list(package_dir.glob(suffix))


def test_no_m8_retrieval_logic_in_review_outputs(reference):
    _, _, package_dir, _ = reference
    serialized = "\n".join(
        (package_dir / name).read_text(encoding="utf-8") for name in REVIEW_PACKAGE_FILES
    ).lower()
    # Implementation-shaped tokens must be absent; the word "embedding" may
    # appear only inside the recorded prohibition statements.
    for token in (
        "embedding_vector",
        "similarity_score",
        "ranking_score",
        "vector_index",
        "nearest_neighbor",
        "cosine",
        "knn",
    ):
        assert token not in serialized
    assert "performs no template" in serialized or "performs no embedding" in serialized


# Corrections --------------------------------------------------------------


def test_valid_room_correction_creates_new_immutable_version(candidate_library, tmp_path):
    library, candidate = candidate_library
    room_id, room_type = _room_target(library, candidate.case_id, "1.0.0")
    corrections = _write_corrections(
        tmp_path / "corrections.json",
        candidate,
        [_correction("room_type", room_id, room_type, "storage")],
    )
    corrected, created = apply_architect_corrections(
        library_root=library,
        corrections_path=corrections,
        case_id=candidate.case_id,
        from_version="1.0.0",
        new_version="1.1.0",
        creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
    )
    assert created is True
    assert corrected.case_version == "1.1.0"
    assert corrected.lifecycle_state is LifecycleState.CORRECTED
    assert corrected.review_state is ReviewState.REQUIRES_REVIEW
    assert corrected.review_decision is None
    assert corrected.supersedes_case_version == "1.0.0"
    assert corrected.review_binding_fingerprint != candidate.review_binding_fingerprint

    # Original extracted values are preserved verbatim in the corrected
    # version; the correction is an overlay record.
    _, _, original_features = load_case_version(library, candidate.case_id, "1.0.0")
    _, _, corrected_features = load_case_version(library, candidate.case_id, "1.1.0")
    original_rooms = feature_map(original_features)["room_geometry.rooms"]
    corrected_rooms = feature_map(corrected_features)["room_geometry.rooms"]
    assert corrected_rooms == original_rooms
    records = feature_map(corrected_features)["corrections.records"]
    assert len(records) == 1
    assert records[0]["target_id"] == room_id
    assert records[0]["old_value"] == room_type
    assert records[0]["new_value"] == "storage"
    assert records[0]["reviewer_id"] == REVIEWER


def test_valid_entrance_correction(candidate_library, tmp_path):
    library, candidate = candidate_library
    door_id, entrance_type = _entrance_target(library, candidate.case_id, "1.0.0")
    corrections = _write_corrections(
        tmp_path / "corrections.json",
        candidate,
        [_correction("entrance_classification", door_id, entrance_type, "service_entrance")],
    )
    corrected, created = apply_architect_corrections(
        library_root=library,
        corrections_path=corrections,
        case_id=candidate.case_id,
        from_version="1.0.0",
        new_version="1.1.0",
        creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
    )
    assert created is True
    _, _, features = load_case_version(library, candidate.case_id, "1.1.0")
    records = feature_map(features)["corrections.records"]
    assert records[0]["correction_type"] == "entrance_classification"


@pytest.mark.parametrize(
    ("ctype", "target"),
    (
        ("room_type", "not-a-real-room-id"),
        ("entrance_classification", "not-a-real-door-id"),
        ("adjacency_relationship", "fake|pair"),
        ("route_interpretation", "teleport_route"),
    ),
)
def test_invalid_canonical_reference_is_rejected(candidate_library, tmp_path, ctype, target):
    library, candidate = candidate_library
    corrections = _write_corrections(
        tmp_path / "corrections.json",
        candidate,
        [_correction(ctype, target, "x", "y")],
    )
    with pytest.raises(SpdInputError, match="unknown canonical id"):
        apply_architect_corrections(
            library_root=library,
            corrections_path=corrections,
            case_id=candidate.case_id,
            from_version="1.0.0",
            new_version="1.1.0",
            creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
        )


def test_conflicting_duplicate_corrections_are_rejected(candidate_library, tmp_path):
    library, candidate = candidate_library
    room_id, room_type = _room_target(library, candidate.case_id, "1.0.0")
    corrections = _write_corrections(
        tmp_path / "corrections.json",
        candidate,
        [
            _correction("room_type", room_id, room_type, "storage"),
            _correction("room_type", room_id, room_type, "laundry"),
        ],
    )
    with pytest.raises(SpdInputError, match="conflicting duplicate corrections"):
        apply_architect_corrections(
            library_root=library,
            corrections_path=corrections,
            case_id=candidate.case_id,
            from_version="1.0.0",
            new_version="1.1.0",
            creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
        )


def test_blank_reviewer_is_rejected(candidate_library, tmp_path):
    library, candidate = candidate_library
    room_id, room_type = _room_target(library, candidate.case_id, "1.0.0")
    corrections = _write_corrections(
        tmp_path / "corrections.json",
        candidate,
        [_correction("room_type", room_id, room_type, "storage", reviewer_id="   ")],
    )
    with pytest.raises(SpdInputError, match="must not be blank"):
        apply_architect_corrections(
            library_root=library,
            corrections_path=corrections,
            case_id=candidate.case_id,
            from_version="1.0.0",
            new_version="1.1.0",
            creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
        )


def test_invalid_review_date_is_rejected(candidate_library, tmp_path):
    library, candidate = candidate_library
    room_id, room_type = _room_target(library, candidate.case_id, "1.0.0")
    corrections = _write_corrections(
        tmp_path / "corrections.json",
        candidate,
        [_correction("room_type", room_id, room_type, "storage", review_date="17/07/2026")],
    )
    with pytest.raises(SpdInputError, match="ISO date"):
        apply_architect_corrections(
            library_root=library,
            corrections_path=corrections,
            case_id=candidate.case_id,
            from_version="1.0.0",
            new_version="1.1.0",
            creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
        )


def test_wrong_old_value_is_rejected(candidate_library, tmp_path):
    library, candidate = candidate_library
    room_id, _ = _room_target(library, candidate.case_id, "1.0.0")
    corrections = _write_corrections(
        tmp_path / "corrections.json",
        candidate,
        [_correction("room_type", room_id, "not-the-stored-type", "storage")],
    )
    with pytest.raises(SpdInputError, match="old_value does not match"):
        apply_architect_corrections(
            library_root=library,
            corrections_path=corrections,
            case_id=candidate.case_id,
            from_version="1.0.0",
            new_version="1.1.0",
            creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
        )


def test_stale_corrections_document_is_rejected(candidate_library, tmp_path):
    library, candidate = candidate_library
    room_id, room_type = _room_target(library, candidate.case_id, "1.0.0")
    corrections = _write_corrections(
        tmp_path / "corrections.json",
        candidate,
        [_correction("room_type", room_id, room_type, "storage")],
        review_binding_fingerprint="f" * 64,
    )
    with pytest.raises(SpdInputError, match="stale"):
        apply_architect_corrections(
            library_root=library,
            corrections_path=corrections,
            case_id=candidate.case_id,
            from_version="1.0.0",
            new_version="1.1.0",
            creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
        )


def test_corrections_dry_run_writes_nothing(candidate_library, tmp_path, capsys):
    from saudi_plot_design.cli import main

    library, candidate = candidate_library
    room_id, room_type = _room_target(library, candidate.case_id, "1.0.0")
    corrections = _write_corrections(
        tmp_path / "corrections.json",
        candidate,
        [_correction("room_type", room_id, room_type, "storage")],
    )
    result = main(
        [
            "library",
            "apply-corrections",
            "--library-root",
            str(library),
            "--case-id",
            candidate.case_id,
            "--from-version",
            "1.0.0",
            "--new-version",
            "1.1.0",
            "--corrections",
            str(corrections),
            "--created-at",
            "2026-07-17T09:00:00+03:00",
            "--created-by",
            "test",
            "--dry-run",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 0 and payload["disposition"] == "dry_run"
    assert not (library / "project_packages" / candidate.case_id / "1.1.0").exists()


# Decisions ----------------------------------------------------------------


def test_requires_revision_decision_records_and_stays_pending(candidate_library, tmp_path):
    library, candidate = candidate_library
    decision = _write_decision(tmp_path / "decision.json", candidate, "requires_revision")
    package, created = apply_architect_decision(
        library_root=library,
        decision_path=decision,
        case_id=candidate.case_id,
        from_version="1.0.0",
        new_version="1.1.0",
        creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
    )
    assert created is True
    assert package.review_state is ReviewState.REQUIRES_REVIEW
    assert package.lifecycle_state is LifecycleState.REQUIRES_REVIEW
    assert package.review_decision is not None
    assert package.review_decision.decision.value == "requires_revision"
    status = review_status_payload(library, candidate.case_id, "1.1.0")
    assert status["active_template"] is False
    assert status["decision"]["decision"] == "requires_revision"


def test_stale_decision_after_corrections_is_rejected(candidate_library, tmp_path):
    library, candidate = candidate_library
    # The decision is prepared against 1.0.0, then corrections change the
    # bound content: the old decision must be rejected as stale.
    decision = _write_decision(
        tmp_path / "decision.json",
        candidate,
        "approved_template",
        case_version="1.1.0",
    )
    room_id, room_type = _room_target(library, candidate.case_id, "1.0.0")
    corrections = _write_corrections(
        tmp_path / "corrections.json",
        candidate,
        [_correction("room_type", room_id, room_type, "storage")],
    )
    apply_architect_corrections(
        library_root=library,
        corrections_path=corrections,
        case_id=candidate.case_id,
        from_version="1.0.0",
        new_version="1.1.0",
        creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
    )
    with pytest.raises(SpdInputError, match="stale"):
        apply_architect_decision(
            library_root=library,
            decision_path=decision,
            case_id=candidate.case_id,
            from_version="1.1.0",
            new_version="1.2.0",
            creation_metadata=metadata("2026-07-17T10:00:00+03:00"),
        )


def test_eligible_villa_approval_via_decision_document(candidate_library, tmp_path, capsys):
    from saudi_plot_design.cli import main

    library, candidate = candidate_library
    decision = _write_decision(tmp_path / "decision.json", candidate, "approved_template")
    result = main(
        [
            "library",
            "apply-architect-decision",
            "--library-root",
            str(library),
            "--case-id",
            candidate.case_id,
            "--from-version",
            "1.0.0",
            "--new-version",
            "1.1.0",
            "--decision-file",
            str(decision),
            "--created-at",
            "2026-07-17T09:00:00+03:00",
            "--created-by",
            "test",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["active_template"] is True
    index = _read(library / "active_template_index.json")
    assert [(entry["case_id"], entry["case_version"]) for entry in index["entries"]] == [
        (candidate.case_id, "1.1.0")
    ]


def test_ineligible_office_approval_is_rejected(tmp_path):
    from m7_library_fixture import build_office_stress_artifacts

    _, artifacts, _ = build_office_stress_artifacts(tmp_path / "office")
    library = tmp_path / "library"
    office, _ = import_m6a_artifacts(
        library_root=library,
        artifact_root=artifacts,
        case_version="1.0.0",
        case_role=CaseRole.INGESTION_STRESS_TEST,
        creation_metadata=metadata("2026-07-17T08:00:00+03:00"),
        template_use_permitted=True,
        shareable_outputs_permitted=True,
        rights_basis="ingestion stress test only",
    )
    decision = _write_decision(tmp_path / "decision.json", office, "approved_template")
    with pytest.raises(SpdInputError, match="prohibited"):
        apply_architect_decision(
            library_root=library,
            decision_path=decision,
            case_id=office.case_id,
            from_version="1.0.0",
            new_version="1.1.0",
            creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
        )
    index = _read(library / "active_template_index.json")
    assert index["entries"] == []


def test_missing_template_use_permission_is_rejected(tmp_path):
    _, artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    library = tmp_path / "library"
    candidate, _ = import_m6a_artifacts(
        library_root=library,
        artifact_root=artifacts,
        case_version="1.0.0",
        case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
        creation_metadata=metadata("2026-07-17T08:00:00+03:00"),
        template_use_permitted=False,
        shareable_outputs_permitted=True,
        rights_basis="ingestion only; template use not granted",
        synthetic_test_fixture=True,
    )
    decision = _write_decision(tmp_path / "decision.json", candidate, "approved_template")
    with pytest.raises(SpdInputError, match="template_use_permission_missing"):
        apply_architect_decision(
            library_root=library,
            decision_path=decision,
            case_id=candidate.case_id,
            from_version="1.0.0",
            new_version="1.1.0",
            creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
        )


def test_decision_without_explicit_template_use_flag_is_rejected(candidate_library, tmp_path):
    library, candidate = candidate_library
    decision = _write_decision(
        tmp_path / "decision.json",
        candidate,
        "approved_template",
        template_use_approved=False,
    )
    with pytest.raises(SpdInputError, match="template_use_not_explicitly_approved"):
        apply_architect_decision(
            library_root=library,
            decision_path=decision,
            case_id=candidate.case_id,
            from_version="1.0.0",
            new_version="1.1.0",
            creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
        )


def test_decision_is_never_inferred_from_labels(candidate_library, tmp_path):
    library, candidate = candidate_library
    # A decision file whose decision field is a metadata-style label must be
    # rejected by schema, not interpreted.
    decision = _write_decision(tmp_path / "APPROVED-final.json", candidate, "requires_revision")
    payload = _read(decision)
    payload["decision"] = "approved_by_folder_name"
    decision.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(SpdInputError, match="failed schema validation"):
        apply_architect_decision(
            library_root=library,
            decision_path=decision,
            case_id=candidate.case_id,
            from_version="1.0.0",
            new_version="1.1.0",
            creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
        )


def test_decision_dry_run_writes_nothing(candidate_library, tmp_path):
    library, candidate = candidate_library
    decision = _write_decision(tmp_path / "decision.json", candidate, "approved_template")
    package, created = apply_architect_decision(
        library_root=library,
        decision_path=decision,
        case_id=candidate.case_id,
        from_version="1.0.0",
        new_version="1.1.0",
        creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
        dry_run=True,
    )
    assert created is True
    assert not (library / "project_packages" / candidate.case_id / "1.1.0").exists()
    index = _read(library / "active_template_index.json")
    assert index["entries"] == []


def test_test_office_remains_permanently_excluded(reference):
    library, _, _, _ = reference
    index = _read(library / "active_template_index.json")
    assert all(entry["case_id"] != "TEST-OFFICE-001" for entry in index["entries"])


def test_show_review_status_cli(candidate_library, tmp_path, capsys):
    from saudi_plot_design.cli import main

    library, candidate = candidate_library
    room_id, room_type = _room_target(library, candidate.case_id, "1.0.0")
    corrections = _write_corrections(
        tmp_path / "corrections.json",
        candidate,
        [_correction("room_type", room_id, room_type, "storage")],
    )
    apply_architect_corrections(
        library_root=library,
        corrections_path=corrections,
        case_id=candidate.case_id,
        from_version="1.0.0",
        new_version="1.1.0",
        creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
    )
    result = main(
        [
            "library",
            "show-review-status",
            "--library-root",
            str(library),
            "--case-id",
            candidate.case_id,
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["case_version"] == "1.1.0"
    assert payload["lifecycle_state"] == "corrected"
    assert payload["review_state"] == "requires_review"
    assert payload["corrections_recorded"] == 1
    assert payload["synthetic_test_fixture"] is True
    assert payload["active_template"] is False
    assert payload["is_current"] is True


# Codex review-gate fixes ---------------------------------------------------


def test_second_correction_chains_from_effective_value(candidate_library, tmp_path):
    library, candidate = candidate_library
    room_id, original_type = _room_target(library, candidate.case_id, "1.0.0")
    first_doc = _write_corrections(
        tmp_path / "first.json",
        candidate,
        [_correction("room_type", room_id, original_type, f"{original_type}_corrected")],
    )
    corrected, _ = apply_architect_corrections(
        library_root=library,
        corrections_path=first_doc,
        case_id=candidate.case_id,
        from_version="1.0.0",
        new_version="1.1.0",
        creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
    )
    # A later correction citing the obsolete ORIGINAL value must be rejected;
    # the effective value was established by the recorded correction.
    stale_doc = _write_corrections(
        tmp_path / "stale.json",
        corrected,
        [_correction("room_type", room_id, original_type, f"{original_type}_again")],
    )
    with pytest.raises(SpdInputError, match="old_value does not match"):
        apply_architect_corrections(
            library_root=library,
            corrections_path=stale_doc,
            case_id=candidate.case_id,
            from_version="1.1.0",
            new_version="1.2.0",
            creation_metadata=metadata("2026-07-17T09:05:00+03:00"),
        )
    chained_doc = _write_corrections(
        tmp_path / "chained.json",
        corrected,
        [_correction("room_type", room_id, f"{original_type}_corrected", f"{original_type}_again")],
    )
    apply_architect_corrections(
        library_root=library,
        corrections_path=chained_doc,
        case_id=candidate.case_id,
        from_version="1.1.0",
        new_version="1.2.0",
        creation_metadata=metadata("2026-07-17T09:05:00+03:00"),
    )
    _, _, features = load_case_version(library, candidate.case_id, "1.2.0")
    history = [
        record["new_value"]
        for record in feature_map(features)["corrections.records"]
        if record["correction_type"] == "room_type" and record["target_id"] == room_id
    ]
    assert history == [f"{original_type}_corrected", f"{original_type}_again"]
    # Originals stay verbatim even after two correction rounds.
    room = next(
        room
        for room in feature_map(features)["room_geometry.rooms"]
        if str(room["room_id"]) == room_id
    )
    assert room["room_type"] == original_type


def test_unmanifested_files_fail_package_validation(reference, tmp_path):
    library, context, _, _ = reference
    package_dir = tmp_path / "pkg"
    prepare_review_package(
        library, package_dir, case_id=context["approved"].case_id, case_version="1.1.0"
    )
    (package_dir / "smuggled.txt").write_bytes(b"foreign content")
    (package_dir / "nested").mkdir()
    (package_dir / "nested" / "extra.json").write_bytes(b"{}")
    errors = validate_review_package(package_dir)
    assert any("unmanifested file present in package: smuggled.txt" in error for error in errors)
    assert any(
        "unmanifested file present in package: nested/extra.json" in error for error in errors
    )


def test_prepare_review_refuses_directory_with_foreign_files(reference, tmp_path):
    library, context, _, _ = reference
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "unrelated_notes.txt").write_bytes(b"do not smuggle me")
    with pytest.raises(SpdInputError, match="foreign files"):
        prepare_review_package(
            library, out_dir, case_id=context["approved"].case_id, case_version="1.1.0"
        )


def test_review_package_of_corrected_version_shows_effective_values(candidate_library, tmp_path):
    library, candidate = candidate_library
    room_id, original_type = _room_target(library, candidate.case_id, "1.0.0")
    door_id, original_entrance = _entrance_target(library, candidate.case_id, "1.0.0")
    first_doc = _write_corrections(
        tmp_path / "first.json",
        candidate,
        [
            _correction("room_type", room_id, original_type, f"{original_type}_corrected"),
            _correction(
                "entrance_classification",
                door_id,
                original_entrance,
                f"{original_entrance}_corrected",
            ),
        ],
    )
    corrected, _ = apply_architect_corrections(
        library_root=library,
        corrections_path=first_doc,
        case_id=candidate.case_id,
        from_version="1.0.0",
        new_version="1.1.0",
        creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
    )
    second_doc = _write_corrections(
        tmp_path / "second.json",
        corrected,
        [_correction("room_type", room_id, f"{original_type}_corrected", f"{original_type}_final")],
    )
    apply_architect_corrections(
        library_root=library,
        corrections_path=second_doc,
        case_id=candidate.case_id,
        from_version="1.1.0",
        new_version="1.2.0",
        creation_metadata=metadata("2026-07-17T09:05:00+03:00"),
    )
    package_dir = tmp_path / "re-review"
    prepare_review_package(library, package_dir, case_id=candidate.case_id, case_version="1.2.0")
    room_rows = {row["room_id"]: row for row in _csv_rows(package_dir / "rooms_review.csv")}
    # Original values stay verbatim; the latest effective correction is shown.
    assert room_rows[room_id]["room_type"] == original_type
    assert room_rows[room_id]["corrected_room_type"] == f"{original_type}_final"
    entrance_rows = {row["door_id"]: row for row in _csv_rows(package_dir / "entrances_review.csv")}
    assert entrance_rows[door_id]["entrance_type"] == original_entrance
    assert entrance_rows[door_id]["corrected_entrance_type"] == f"{original_entrance}_corrected"
    summary = (package_dir / "intake_summary.md").read_text(encoding="utf-8")
    assert "## Recorded architect corrections" in summary
    assert f"`room_type:{room_id}`: {original_type} -> {original_type}_corrected" in summary
    assert f"`room_type:{room_id}`: {original_type}_corrected -> {original_type}_final" in summary
    assert (
        f"`entrance_classification:{door_id}`: {original_entrance} -> "
        f"{original_entrance}_corrected" in summary
    )
    # The re-review package still validates and regenerates byte-identically.
    assert validate_review_package(package_dir) == ()
    again = tmp_path / "re-review-again"
    prepare_review_package(library, again, case_id=candidate.case_id, case_version="1.2.0")
    for name in REVIEW_PACKAGE_FILES:
        assert (again / name).read_bytes() == (package_dir / name).read_bytes(), name


def test_correction_values_cannot_inject_spreadsheet_formulas(candidate_library, tmp_path):
    library, candidate = candidate_library
    room_id, original_type = _room_target(library, candidate.case_id, "1.0.0")
    door_id, original_entrance = _entrance_target(library, candidate.case_id, "1.0.0")
    # Values with path-like fragments or escaped control characters are
    # already rejected by the privacy gate before storage; these two isolate
    # the spreadsheet-formula concern for values that CAN be stored.
    payloads = {
        "room_type": '=HYPERLINK("http://attacker.example","open")',
        "entrance_classification": "@SUM(1,2)",
    }
    document = _write_corrections(
        tmp_path / "corrections.json",
        candidate,
        [
            _correction("room_type", room_id, original_type, payloads["room_type"]),
            _correction(
                "entrance_classification",
                door_id,
                original_entrance,
                payloads["entrance_classification"],
            ),
        ],
    )
    apply_architect_corrections(
        library_root=library,
        corrections_path=document,
        case_id=candidate.case_id,
        from_version="1.0.0",
        new_version="1.1.0",
        creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
    )
    package_dir = tmp_path / "package"
    prepare_review_package(library, package_dir, case_id=candidate.case_id, case_version="1.1.0")
    room_rows = {row["room_id"]: row for row in _csv_rows(package_dir / "rooms_review.csv")}
    entrance_rows = {row["door_id"]: row for row in _csv_rows(package_dir / "entrances_review.csv")}
    # The rendered cell is neutralized; a spreadsheet shows text, not a formula.
    assert room_rows[room_id]["corrected_room_type"] == "'" + payloads["room_type"]
    assert (
        entrance_rows[door_id]["corrected_entrance_type"]
        == "'" + payloads["entrance_classification"]
    )
    # The immutable record keeps the exact submitted value.
    _, _, features = load_case_version(library, candidate.case_id, "1.1.0")
    recorded = {
        (record["correction_type"], record["target_id"]): record["new_value"]
        for record in feature_map(features)["corrections.records"]
    }
    assert recorded[("room_type", room_id)] == payloads["room_type"]
    assert recorded[("entrance_classification", door_id)] == payloads["entrance_classification"]
    # Plain negative numbers are not mangled anywhere in the rendered CSVs;
    # control-prefixed and sign-prefixed payloads are neutralized.
    assert _spreadsheet_safe("-2.5") == "-2.5"
    assert _spreadsheet_safe("-2+cmd") == "'-2+cmd"
    assert _spreadsheet_safe("\t=1+2") == "'\t=1+2"
    assert _spreadsheet_safe("\r=1+2") == "'\r=1+2"
    assert _spreadsheet_safe("+2+cmd") == "'+2+cmd"
    # Regeneration stays byte-identical with neutralization applied.
    again = tmp_path / "package-again"
    prepare_review_package(library, again, case_id=candidate.case_id, case_version="1.1.0")
    for name in REVIEW_PACKAGE_FILES:
        assert (again / name).read_bytes() == (package_dir / name).read_bytes(), name


def test_unsupported_decision_schema_version_is_rejected(candidate_library, tmp_path):
    library, candidate = candidate_library
    decision = _write_decision(
        tmp_path / "decision.json",
        candidate,
        "architect_reviewed",
        decision_schema_version=99,
    )
    with pytest.raises(SpdInputError, match="unsupported decision schema version 99"):
        apply_architect_decision(
            library_root=library,
            decision_path=decision,
            case_id=candidate.case_id,
            from_version="1.0.0",
            new_version="1.1.0",
            creation_metadata=metadata("2026-07-17T09:00:00+03:00"),
        )
