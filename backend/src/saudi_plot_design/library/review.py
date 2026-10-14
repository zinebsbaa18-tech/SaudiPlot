"""M7.2 deterministic architect-review package generation and validation.

The package is rendered ONLY from a stored immutable M7.1 case version
(project package, source bundle, feature package). It performs no parsing,
retrieval, ranking, or adaptation, copies no source files, and derives every
timestamp from the version's controlled creation metadata so regeneration is
byte-identical.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path

from pydantic import ValidationError

from saudi_plot_design.library.fingerprints import (
    calculate_review_package_root_fingerprint,
)
from saudi_plot_design.library.models import (
    REVIEW_PACKAGE_SCHEMA_VERSION,
    SYNTHETIC_FIXTURE_DISCLAIMER,
    ArtifactRecord,
    CorrectionType,
    ProjectCasePackage,
    ReviewPackageManifest,
    SourceBundleManifest,
    TemplateFeaturePackage,
)
from saudi_plot_design.library.storage import json_bytes, load_case_version
from saudi_plot_design.library.validation import (
    active_template_ineligibility_reasons,
    validate_project_package,
)
from saudi_plot_design.model import SpdInputError

# Single home for the overlay feature id; corrections.py imports it from here.
CORRECTIONS_FEATURE_ID = "corrections.records"
REVIEW_PACKAGE_FILES = (
    "intake_summary.md",
    "source_bundle_manifest.json",
    "residential_program_review.csv",
    "rooms_review.csv",
    "entrances_review.csv",
    "routes_review.csv",
    "adjacency_review.csv",
    "wet_areas_review.csv",
    "facade_openings_review.csv",
    "quality_findings_review.csv",
    "architect_corrections_template.json",
    "architect_review_decision_template.json",
    "intake_validation_report.json",
    "review_package_manifest.json",
)
_MANIFEST_NAME = "review_package_manifest.json"


def prepare_review_package(
    library_root: str | Path,
    out_dir: str | Path,
    *,
    case_id: str,
    case_version: str,
    dry_run: bool = False,
) -> ReviewPackageManifest:
    """Render the deterministic review package; idempotent on identical bytes."""
    out_dir = Path(out_dir)
    if "private_cases" in {part.lower() for part in out_dir.resolve(strict=False).parts}:
        raise SpdInputError("review package output must not be inside private_cases")
    package, bundle, features = load_case_version(library_root, case_id, case_version)
    files = _render_files(package, bundle, features)
    manifest = _build_manifest(package, files)
    files[_MANIFEST_NAME] = json_bytes(manifest.model_dump(mode="json"))

    # A handoff directory holding files the manifest will not record would
    # smuggle unmanifested content past the integrity check.
    foreign = sorted(
        path.relative_to(out_dir).as_posix()
        for path in (out_dir.rglob("*") if out_dir.is_dir() else ())
        if path.is_file() and path.relative_to(out_dir).as_posix() not in files
    )
    if foreign:
        raise SpdInputError(
            "review package directory contains foreign files: " + ", ".join(foreign)
        )
    conflicts = [
        name
        for name, content in files.items()
        if (out_dir / name).is_file() and (out_dir / name).read_bytes() != content
    ]
    if conflicts:
        raise SpdInputError(
            "review package already exists with different content: " + ", ".join(sorted(conflicts))
        )
    if dry_run:
        return manifest
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (out_dir / name).write_bytes(content)
    return manifest


def validate_review_package(package_dir: str | Path) -> tuple[str, ...]:
    """Machine-readable integrity errors for a rendered review package."""
    package_dir = Path(package_dir)
    errors: list[str] = []
    manifest_path = package_dir / _MANIFEST_NAME
    if not manifest_path.is_file():
        return ("missing review_package_manifest.json",)
    try:
        manifest = ReviewPackageManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except (ValidationError, json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        return (f"invalid review_package_manifest.json: {exc}",)
    if manifest.review_package_schema_version != REVIEW_PACKAGE_SCHEMA_VERSION:
        return (
            "invalid review_package_manifest.json: unsupported schema version "
            f"{manifest.review_package_schema_version}",
        )
    if calculate_review_package_root_fingerprint(manifest) != manifest.root_fingerprint:
        return (
            "invalid review_package_manifest.json: root fingerprint does not match "
            "the manifest metadata",
        )
    recorded = {record.relative_path for record in manifest.artifacts}
    expected = set(REVIEW_PACKAGE_FILES) - {_MANIFEST_NAME}
    for name in sorted(expected - recorded):
        errors.append(f"manifest does not record required file: {name}")
    for name in sorted(recorded - expected):
        errors.append(f"manifest records unexpected file: {name}")
    for record in manifest.artifacts:
        path = package_dir / record.relative_path
        if not path.is_file():
            errors.append(f"missing artifact: {record.relative_path}")
            continue
        if path.stat().st_size != record.size_bytes:
            errors.append(f"size mismatch: {record.relative_path}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != record.sha256:
            errors.append(f"hash mismatch: {record.relative_path}")
    # Files on disk that the manifest does not record defeat the integrity
    # guarantee at the handoff boundary; every regular file must be recorded.
    on_disk = {
        path.relative_to(package_dir).as_posix()
        for path in package_dir.rglob("*")
        if path.is_file()
    }
    for name in sorted(on_disk - recorded - {_MANIFEST_NAME}):
        errors.append(f"unmanifested file present in package: {name}")
    return tuple(errors)


def feature_map(features: TemplateFeaturePackage | None) -> dict[str, object]:
    if features is None:
        return {}
    return {feature.feature_id: feature.value for feature in features.features}


def _recorded_corrections(values: dict[str, object]) -> tuple[dict, ...]:
    return tuple(
        record for record in (values.get(CORRECTIONS_FEATURE_ID) or ()) if isinstance(record, dict)
    )


def _effective_corrections(values: dict[str, object]) -> dict[tuple[str, str], dict]:
    """Latest recorded correction per (type, target); append order, newest wins."""
    effective: dict[tuple[str, str], dict] = {}
    for record in _recorded_corrections(values):
        key = (str(record.get("correction_type")), str(record.get("target_id")))
        effective[key] = record
    return effective


def _corrected_cell(
    effective: dict[tuple[str, str], dict], correction_type: str, target_id: object
) -> str:
    record = effective.get((correction_type, str(target_id)))
    return "" if record is None else _cell(record.get("new_value"))


def correction_targets(
    package: ProjectCasePackage, features: TemplateFeaturePackage | None
) -> dict[str, tuple[str, ...]]:
    """Real canonical IDs an architect correction may reference."""
    values = feature_map(features)
    rooms = tuple(sorted(str(room["room_id"]) for room in values.get("room_geometry.rooms") or ()))
    entrances = tuple(
        sorted(str(item["door_id"]) for item in values.get("entrances.inventory") or ())
    )
    openings = tuple(
        sorted(
            str(item.get("ifc_global_id"))
            for item in values.get("facade.opening_inventory") or ()
            if item.get("ifc_global_id")
        )
    )
    adjacency = tuple(
        sorted(f"{edge['a']}|{edge['b']}" for edge in values.get("topology.room_adjacency") or ())
    )
    routes = ["family_route", "guest_route", "service_route"]
    routes.extend(
        f"entrance_route:{key}"
        for key in sorted(values.get("topology.entrance_to_room_routes") or {})
    )
    limitations = tuple(sorted(package.provenance.limitations))
    if features is not None:
        limitations = tuple(sorted({*limitations, *features.limitations}))
    return {
        "rooms": rooms,
        "entrances": entrances,
        "openings": openings,
        "adjacency_pairs": adjacency,
        "routes": tuple(routes),
        "limitations": limitations,
        "case": ("case",),
    }


def _render_files(
    package: ProjectCasePackage,
    bundle: SourceBundleManifest,
    features: TemplateFeaturePackage | None,
) -> dict[str, bytes]:
    values = feature_map(features)
    reasons = active_template_ineligibility_reasons(package, bundle, features)
    findings = validate_project_package(package, bundle, features)
    files: dict[str, bytes] = {}
    files["intake_summary.md"] = _text(_intake_summary(package, bundle, features, reasons))
    files["source_bundle_manifest.json"] = json_bytes(bundle.model_dump(mode="json"))
    files["residential_program_review.csv"] = _program_csv(values)
    files["rooms_review.csv"] = _rooms_csv(values)
    files["entrances_review.csv"] = _entrances_csv(values)
    files["routes_review.csv"] = _routes_csv(values)
    files["adjacency_review.csv"] = _adjacency_csv(values)
    files["wet_areas_review.csv"] = _wet_areas_csv(values)
    files["facade_openings_review.csv"] = _facade_csv(values)
    files["quality_findings_review.csv"] = _quality_csv(package, values)
    files["architect_corrections_template.json"] = json_bytes(
        _corrections_template(package, features)
    )
    files["architect_review_decision_template.json"] = json_bytes(_decision_template(package))
    files["intake_validation_report.json"] = json_bytes(
        {
            "case_id": package.case_id,
            "case_version": package.case_version,
            "template_eligible": package.template_eligible,
            "template_ineligibility_reasons": list(package.template_ineligibility_reasons),
            "active_template_ineligibility_reasons": list(reasons),
            "source_validation_summary": package.validation_summary.model_dump(mode="json"),
            "library_validation_findings": [
                finding.model_dump(mode="json") for finding in findings
            ],
        }
    )
    return files


def _build_manifest(package: ProjectCasePackage, files: dict[str, bytes]) -> ReviewPackageManifest:
    records = tuple(
        ArtifactRecord(
            relative_path=name,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        for name, content in sorted(files.items())
        if name != _MANIFEST_NAME
    )
    manifest = ReviewPackageManifest(
        case_id=package.case_id,
        case_version=package.case_version,
        generated_at=package.creation_metadata.created_at,
        review_binding_fingerprint=package.review_binding_fingerprint,
        artifacts=records,
        root_fingerprint="0" * 64,
    )
    return manifest.model_copy(
        update={"root_fingerprint": calculate_review_package_root_fingerprint(manifest)}
    )


def _intake_summary(
    package: ProjectCasePackage,
    bundle: SourceBundleManifest,
    features: TemplateFeaturePackage | None,
    reasons: tuple[str, ...],
) -> str:
    values = feature_map(features)
    lines = ["# Architect Intake Summary", ""]
    if package.provenance.synthetic_test_fixture:
        lines.extend([f"**{SYNTHETIC_FIXTURE_DISCLAIMER}**", ""])
    lines.extend(
        [
            "This package supports human architect review only. It performs no template",
            "retrieval, ranking, similarity matching, adaptation, or design generation.",
            "",
            "## Case identity",
            "",
            f"- Case: `{package.case_id}`",
            f"- Version: `{package.case_version}`",
            f"- Role: `{package.case_role.value}`",
            f"- Lifecycle: `{package.lifecycle_state.value}`",
            f"- Review state: `{package.review_state.value}`",
            f"- Project type: `{package.project_type}`",
            f"- Country: `{package.country}`",
            f"- City: `{package.city or 'not recorded'}`",
            f"- Architectural character: `{package.architectural_character or 'not recorded'}`",
            f"- Provenance: `{package.provenance.provenance_type}`",
            "",
            "## Fingerprints",
            "",
            f"- Source bundle: `{package.source_bundle_fingerprint}`",
            f"- Canonical case: `{package.canonical_case_fingerprint or 'not available'}`",
            f"- Review binding: `{package.review_binding_fingerprint}`",
            "",
            "## Source assets",
            "",
        ]
    )
    for asset in bundle.assets:
        lines.append(
            f"- `{asset.asset_id}`: format `{asset.format.value}`, parser status "
            f"`{asset.parser_status.value}`, rights `{asset.usage_rights_status}`, "
            f"confidentiality `{asset.confidentiality_status}`"
        )
    lines.extend(["", "## Plot and floors", ""])
    for label, feature_id in (
        ("Floor count", "massing.floor_count"),
        ("Total concept area (m2)", "massing.total_concept_area"),
        ("Plot width (m)", "site.plot_width"),
        ("Plot depth (m)", "site.plot_depth"),
        ("Plot area (m2)", "site.plot_area"),
    ):
        value = values.get(feature_id)
        lines.append(f"- {label}: {value if value is not None else 'not available in source'}")
    program = values.get("program.room_type_counts") or {}
    lines.extend(
        [
            "",
            "## Residential program",
            "",
            f"- Bedrooms: {values.get('program.bedroom_count', 'not available')}",
            f"- Bathrooms: {values.get('program.bathroom_count', 'not available')}",
            f"- Majlis present: {values.get('program.majlis_present', 'not available')}",
            f"- Family living present: "
            f"{values.get('program.family_living_present', 'not available')}",
            f"- Room types: {json.dumps(program, sort_keys=True, ensure_ascii=False)}",
            "",
            "## Template eligibility",
            "",
            f"- Eligible: {str(package.template_eligible).lower()}",
        ]
    )
    for reason in package.template_ineligibility_reasons:
        lines.append(f"- Ineligibility reason: `{reason}`")
    for reason in reasons:
        lines.append(f"- Active-template gate reason: `{reason}`")
    lines.extend(["", "## Limitations", ""])
    for limitation in package.provenance.limitations:
        lines.append(f"- {limitation}")
    if features is not None:
        for limitation in features.limitations:
            lines.append(f"- {limitation}")
    # Recorded corrections must be visible at re-review: originals stay
    # verbatim in the tables, so the audit history is the record of change.
    records = _recorded_corrections(values)
    if records:
        lines.extend(["", "## Recorded architect corrections", ""])
        for record in records:
            lines.append(
                f"- {record.get('review_date', '')} "
                f"`{record.get('correction_type', '')}:{record.get('target_id', '')}`: "
                f"{_cell(record.get('old_value'))} -> {_cell(record.get('new_value'))} "
                f"({record.get('reviewer_id', '')}: {record.get('reason', '')})"
            )
    lines.append("")
    return "\n".join(lines)


def _program_csv(values: dict[str, object]) -> bytes:
    rows = []
    for item, feature_id in (
        ("bedroom_count", "program.bedroom_count"),
        ("bathroom_count", "program.bathroom_count"),
        ("majlis_present", "program.majlis_present"),
        ("family_living_present", "program.family_living_present"),
        ("kitchen_present", "program.kitchen_present"),
        ("maid_room_present", "program.maid_room_present"),
        ("room_type_counts", "program.room_type_counts"),
        ("service_space_ids", "program.service_space_ids"),
        ("circulation_space_ids", "program.circulation_space_ids"),
        ("zone_area_ratios", "zoning.zone_area_ratios"),
    ):
        value = values.get(feature_id)
        rows.append(
            {
                "item": item,
                "value": _cell(value),
                "status": "extracted" if feature_id in values else "not_available",
                "architect_correction": "",
                "architect_notes": "",
            }
        )
    return _csv(rows, ("item", "value", "status", "architect_correction", "architect_notes"))


def _rooms_csv(values: dict[str, object]) -> bytes:
    zone_by_room = {
        str(item["room_id"]): item for item in values.get("zoning.room_assignments") or ()
    }
    effective = _effective_corrections(values)
    rows = []
    for room in values.get("room_geometry.rooms") or ():
        assignment = zone_by_room.get(str(room["room_id"]), {})
        rows.append(
            {
                "room_id": room["room_id"],
                "room_type": room["room_type"],
                "zone": assignment.get("zone", "unknown"),
                "zone_confidence": _cell(assignment.get("confidence", "")),
                "reviewer_status": assignment.get("reviewer_status", "unknown"),
                "area_m2": _cell(room["area_m2"]),
                "external_wall_contact": _cell(room["external_wall_contact"]),
                "external_opening": _cell(room["external_opening"]),
                # Originals stay verbatim above; the recorded effective
                # corrections are surfaced so re-review sees what changed.
                "corrected_room_name": _corrected_cell(effective, "room_name", room["room_id"]),
                "corrected_room_type": _corrected_cell(effective, "room_type", room["room_id"]),
                "corrected_zone": _corrected_cell(effective, "zone", room["room_id"]),
                "architect_notes": "",
            }
        )
    rows.sort(key=lambda row: str(row["room_id"]))
    return _csv(
        rows,
        (
            "room_id",
            "room_type",
            "zone",
            "zone_confidence",
            "reviewer_status",
            "area_m2",
            "external_wall_contact",
            "external_opening",
            "corrected_room_name",
            "corrected_room_type",
            "corrected_zone",
            "architect_notes",
        ),
    )


def _entrances_csv(values: dict[str, object]) -> bytes:
    effective = _effective_corrections(values)
    rows = [
        {
            "door_id": item["door_id"],
            "entrance_type": item["entrance_type"],
            "confidence": _cell(item.get("confidence", "")),
            "method": item.get("method", ""),
            "reviewer_status": item.get("reviewer_status", ""),
            "actual_door_evidence": _cell(item.get("actual_door_evidence", "")),
            "into_space_id": item.get("into_space_id", ""),
            "corrected_entrance_type": _corrected_cell(
                effective, "entrance_classification", item["door_id"]
            ),
            "architect_notes": "",
        }
        for item in values.get("entrances.inventory") or ()
    ]
    rows.sort(key=lambda row: str(row["door_id"]))
    return _csv(
        rows,
        (
            "door_id",
            "entrance_type",
            "confidence",
            "method",
            "reviewer_status",
            "actual_door_evidence",
            "into_space_id",
            "corrected_entrance_type",
            "architect_notes",
        ),
    )


def _routes_csv(values: dict[str, object]) -> bytes:
    effective = _effective_corrections(values)
    rows = []
    for route_key, feature_id in (
        ("guest_route", "topology.guest_route"),
        ("family_route", "topology.family_route"),
        ("service_route", "topology.service_route"),
    ):
        sequence = values.get(feature_id)
        rows.append(
            {
                "route_id": route_key,
                "sequence": _cell(sequence),
                "status": "extracted" if sequence else "not_available",
                "architect_correction": _corrected_cell(
                    effective, "route_interpretation", route_key
                ),
                "architect_notes": "",
            }
        )
    for key, sequence in sorted((values.get("topology.entrance_to_room_routes") or {}).items()):
        rows.append(
            {
                "route_id": f"entrance_route:{key}",
                "sequence": _cell(sequence),
                "status": "extracted",
                "architect_correction": _corrected_cell(
                    effective, "route_interpretation", f"entrance_route:{key}"
                ),
                "architect_notes": "",
            }
        )
    return _csv(rows, ("route_id", "sequence", "status", "architect_correction", "architect_notes"))


def _adjacency_csv(values: dict[str, object]) -> bytes:
    effective = _effective_corrections(values)
    rows = []
    for edge in values.get("topology.room_adjacency") or ():
        pair_id = f"{edge['a']}|{edge['b']}"
        rows.append(
            {
                "relationship": "room_adjacency",
                "pair_id": pair_id,
                "detail": _cell(edge),
                "architect_correction": _corrected_cell(
                    effective, "adjacency_relationship", pair_id
                ),
                "architect_notes": "",
            }
        )
    for edge in values.get("topology.door_connectivity") or ():
        pair = f"{edge.get('a', '')}|{edge.get('b', '')}"
        rows.append(
            {
                "relationship": "door_connectivity",
                "pair_id": pair,
                "detail": _cell(edge),
                "architect_correction": "",
                "architect_notes": "",
            }
        )
    rows.sort(key=lambda row: (row["relationship"], row["pair_id"], row["detail"]))
    return _csv(
        rows,
        ("relationship", "pair_id", "detail", "architect_correction", "architect_notes"),
    )


def _wet_areas_csv(values: dict[str, object]) -> bytes:
    groups = values.get("topology.wet_area_groups") or ()
    rows = [
        {
            "group_index": index,
            "room_ids": _cell(group),
            "architect_correction": "",
            "architect_notes": "",
        }
        for index, group in enumerate(groups)
    ]
    return _csv(rows, ("group_index", "room_ids", "architect_correction", "architect_notes"))


def _facade_csv(values: dict[str, object]) -> bytes:
    rows = []
    for opening in values.get("facade.opening_inventory") or ():
        rows.append(
            {
                "opening_id": opening.get("ifc_global_id", ""),
                "level_id": opening.get("level_id", ""),
                "is_external": _cell(opening.get("is_external", "")),
                "connects_space_ids": _cell(opening.get("connects_space_ids", "")),
                "detail": _cell(opening),
                "architect_notes": "",
            }
        )
    rows.sort(key=lambda row: str(row["opening_id"]))
    return _csv(
        rows,
        (
            "opening_id",
            "level_id",
            "is_external",
            "connects_space_ids",
            "detail",
            "architect_notes",
        ),
    )


def _quality_csv(package: ProjectCasePackage, values: dict[str, object]) -> bytes:
    quality = values.get("quality.assessment") or {}
    rows = [
        {
            "finding": "assessment_version",
            "value": _cell(quality.get("assessment_version", "not_evaluated")),
            "architect_notes": "",
        },
        {
            "finding": "score_status",
            "value": _cell(quality.get("score_status", "not_evaluated")),
            "architect_notes": "",
        },
    ]
    for rule_id in quality.get("blocking_finding_ids") or ():
        rows.append({"finding": "blocking", "value": rule_id, "architect_notes": ""})
    for rule_id in quality.get("major_finding_ids") or ():
        rows.append({"finding": "major", "value": rule_id, "architect_notes": ""})
    for check_id in package.validation_summary.failed_check_ids:
        rows.append(
            {"finding": "source_validation_failure", "value": check_id, "architect_notes": ""}
        )
    return _csv(rows, ("finding", "value", "architect_notes"))


def _corrections_template(
    package: ProjectCasePackage, features: TemplateFeaturePackage | None
) -> dict:
    targets = correction_targets(package, features)
    template = {
        "corrections_schema_version": 1,
        "case_id": package.case_id,
        "case_version": package.case_version,
        "review_binding_fingerprint": package.review_binding_fingerprint,
        "instructions": (
            "Fill `corrections` with entries following `correction_fields`. Every "
            "correction must reference a real canonical ID from `valid_targets`. "
            "Original extracted values are never modified; corrections create a "
            "new immutable case version and invalidate prior approvals."
        ),
        "correction_types": sorted(item.value for item in CorrectionType),
        "correction_fields": {
            "correction_type": "one of correction_types",
            "target_id": "a canonical ID from valid_targets",
            "old_value": "the currently recorded value",
            "new_value": "the corrected value",
            "reviewer_id": "non-blank reviewer identity",
            "review_date": "ISO date (YYYY-MM-DD)",
            "reason": "non-blank reason",
            "source_evidence": "non-blank evidence reference",
        },
        "valid_targets": {key: list(value) for key, value in sorted(targets.items())},
        "corrections": [],
        "notes": "",
    }
    if package.provenance.synthetic_test_fixture:
        template["synthetic_test_fixture_disclaimer"] = SYNTHETIC_FIXTURE_DISCLAIMER
    return template


def _decision_template(package: ProjectCasePackage) -> dict:
    template = {
        "decision_schema_version": 1,
        "case_id": package.case_id,
        "case_version": package.case_version,
        "decision": "<requires_revision|architect_reviewed|rejected|approved_template>",
        "reviewer_id": "",
        "review_date": "",
        "bound_fingerprint": package.review_binding_fingerprint,
        "template_use_approved": False,
        "rationale": "",
        "instructions": (
            "approved_template requires an eligible Saudi residential villa, passing "
            "validation, explicit template-use permission, a complete feature package, "
            "and the exact bound_fingerprint above. Decisions are never inferred from "
            "filenames, folder names, metadata labels, or scores."
        ),
    }
    if package.provenance.synthetic_test_fixture:
        template["synthetic_test_fixture_disclaimer"] = SYNTHETIC_FIXTURE_DISCLAIMER
    return template


# Spreadsheet-formula injection guard: any cell string a spreadsheet could
# execute is neutralized with a leading apostrophe at the CSV boundary only;
# the immutable JSON records keep the exact value.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_PLAIN_NUMBER = re.compile(r"^-?\d+(\.\d+)?([eE][+-]?\d+)?$")


def _spreadsheet_safe(value):
    if (
        isinstance(value, str)
        and value.startswith(_FORMULA_PREFIXES)
        and not _PLAIN_NUMBER.match(value)
    ):
        return "'" + value
    return value


def _csv(rows: list[dict], header: tuple[str, ...]) -> bytes:
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(header), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _spreadsheet_safe(row.get(key, "")) for key in header})
    return stream.getvalue().encode("utf-8")


def _cell(value) -> str:
    if value is None:
        return "not_available"
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _text(content: str) -> bytes:
    return content.encode("utf-8")


__all__ = [
    "CORRECTIONS_FEATURE_ID",
    "REVIEW_PACKAGE_FILES",
    "correction_targets",
    "feature_map",
    "prepare_review_package",
    "validate_review_package",
]
