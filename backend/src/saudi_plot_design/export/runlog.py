"""run.json audit artifact + typed export manifest + file hashing (M5).

Serialization is deterministic except for the explicitly documented
``run_id`` and ``generation_timestamp`` fields, which callers inject (tests
pass fixed values for golden comparisons).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from saudi_plot_design import __version__
from saudi_plot_design.output import DISCLAIMER

GENERATOR_VERSION = __version__


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ExportManifest(BaseModel):
    """Proves which exact plot, concept, and facade produced the files."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    disclaimer: str = DISCLAIMER
    # Paths are relative to the directory containing this manifest
    # (deterministic + portable).
    pdf_path: str
    dxf_path: str
    quality_report_path: str
    quality_summary_path: str
    quality_overlay_path: str
    run_json_path: str
    file_sizes_bytes: dict[str, int]
    file_sha256: dict[str, str]
    generation_version: str = GENERATOR_VERSION
    plot_fingerprint: str
    concept_fingerprint: str
    facade_concept_id: str
    validation_status: str  # "all_gates_passed"
    quality_assessment_version: str
    quality_criteria_profile_id: str
    quality_criteria_profile_version: str
    quality_raw_weighted_score: float | None
    quality_evidence_coverage: float
    quality_coverage_adjusted_score: float | None
    quality_overall_score: float | None
    quality_score_status: str
    quality_status_constraints: tuple[str, ...]
    quality_blocking_findings: int
    quality_major_findings: int
    layout_mode: str | None = None
    layout_engine_version: str | None = None
    layout_selected_candidate_id: str | None = None
    layout_candidates_generated: int | None = None
    layout_candidates_valid: int | None = None
    layout_candidates_rejected: int | None = None
    layout_optimization_report_path: str | None = None
    layout_candidate_comparison_path: str | None = None
    layout_optimization_overlay_path: str | None = None
    sheet_set_mode: str | None = None
    sheet_graphic_profile_id: str | None = None
    sheet_source_candidate_id: str | None = None
    sheet_source_geometry_fingerprint: str | None = None
    sheet_concept_pdf_path: str | None = None
    sheet_review_pdf_path: str | None = None
    architectural_sheet_index_path: str | None = None
    architectural_sheet_manifest_path: str | None = None
    annotation_collision_report_path: str | None = None
    architectural_sheet_svg_paths: tuple[str, ...] = ()
    architectural_sheet_numbers: tuple[str, ...] = ()
    architectural_sheet_validation_status: str | None = None
    architectural_sheet_unresolved_collisions: int | None = None
    disclaimer_status: str  # "unconditional_demo_disclaimer_embedded"


def build_run_json(
    *,
    run_id: str,
    generation_timestamp: str,
    plot,
    envelope,
    rules,
    concept,
    match,
    style_selection,
    pack_ref,
    pack_data,
    selection,
    facade,
    source_inputs: list[str],
    output_files: dict[str, str],
    output_hashes: dict[str, str],
    quality_assessment,
    optimization_result=None,
    sheet_export=None,
) -> dict:
    payload = {
        "schema_version": 1,
        "disclaimer": DISCLAIMER,
        "run_id": run_id,
        "generation_timestamp": generation_timestamp,
        "generator_version": GENERATOR_VERSION,
        "project_id": plot.plot_id,
        "plot_id": plot.plot_id,
        "plot_fingerprint": plot.fingerprint,
        "concept_id": concept.concept_id,
        "concept_fingerprint": concept.fingerprint,
        "facade_concept_id": facade.facade_concept_id,
        "selected_boundary_id": selection.selected_plot_boundary_id,
        "selected_wall_ids": list(selection.selected_building_wall_ids),
        "dataset_id": match.dataset_id,
        "dataset_version": match.dataset_version,
        "style_pack_id": pack_ref.style_pack_id,
        "style_pack_version": pack_ref.version,
        # Complete provenance of every governed dataset consumed by this run
        # (GEOSPATIAL_DATA_PROVENANCE.md rule 3).
        "governed_data_provenance": {
            "character_dataset": {
                "dataset_id": match.dataset_id,
                "version": match.dataset_version,
                "source_status": match.source_status,
                "demo_statement": match.demo_statement,
            },
            # Serialized from the CONSUMED pack data, not the reference: the
            # gate binds pack_data to pack_ref by id+version only, so the
            # provenance must come from what generation actually used.
            "style_pack": {
                "id": pack_data.core.style_pack_id,
                "version": pack_data.core.version,
                # Arabic stored in logical Unicode code-point order (never
                # visually reversed), from the consumed pack data.
                "name_ar": pack_data.core.name_ar,
                "name_en": pack_data.core.name_en,
                "status": pack_data.core.status,
                "source_metadata": pack_data.source_metadata.model_dump(mode="json"),
                "limitations": list(pack_data.source_metadata.limitations),
            },
            "setback_rules": {
                "id": rules.id,
                "provenance": rules.provenance,
                "statement": rules.statement,
            },
        },
        "confirmations": {
            "style_selection_method": style_selection.selection_method.value,
            "style_user_confirmed": style_selection.user_confirmed,
            "style_override_reason": style_selection.override_reason,
            "facade_user_confirmed": selection.user_confirmed,
        },
        "validation_summaries": {
            "concept": {
                "passed": concept.validation.passed if concept.validation else False,
                "checks": len(concept.validation.checks) if concept.validation else 0,
            },
            "facade": {
                "passed": facade.validation.passed if facade.validation else False,
                "checks": len(facade.validation.checks) if facade.validation else 0,
            },
            "character_match": {
                "method": match.match_method.value,
                "confidence_level": match.confidence_level,
                "confidence_value": match.confidence_value,
                "selected_zone_id": match.selected_zone_id,
            },
        },
        "setback_rules": {
            "id": rules.id,
            "provenance": rules.provenance,
            "front_m": rules.front_m,
            "side_m": rules.side_m,
            "rear_m": rules.rear_m,
        },
        "envelope": {
            "width_m": envelope.width_m,
            "depth_m": envelope.depth_m,
            "area_m2": envelope.area_m2,
        },
        "source_inputs": source_inputs,
        "architectural_quality": {
            "assessment_version": quality_assessment.assessment_version,
            "disclaimer": quality_assessment.disclaimer,
            "criteria_profile": {
                "id": quality_assessment.criteria_profile.profile_id,
                "version": quality_assessment.criteria_profile.profile_version,
                "provenance": quality_assessment.criteria_profile.provenance.model_dump(
                    mode="json"
                ),
            },
            "raw_weighted_score": quality_assessment.raw_weighted_score,
            "evidence_coverage": quality_assessment.evidence_coverage,
            "coverage_adjusted_score": quality_assessment.coverage_adjusted_score,
            "overall_score": quality_assessment.overall_score,
            "score_status": quality_assessment.score_status.value,
            "status_constraints": [
                constraint.model_dump(mode="json")
                for constraint in quality_assessment.status_constraints
            ],
            "category_floor_failures": [
                failure.model_dump(mode="json")
                for failure in quality_assessment.category_floor_failures
            ],
            "evaluation_confidence": quality_assessment.evaluation_confidence,
            "category_scores": {
                category.value: result.model_dump(mode="json")
                for category, result in quality_assessment.category_scores.items()
            },
            "checks": {
                "evaluated": quality_assessment.evaluated_checks,
                "passed": quality_assessment.passed_checks,
                "warnings": quality_assessment.warning_checks,
                "failed": quality_assessment.failed_checks,
                "not_evaluable": quality_assessment.not_evaluable_checks,
            },
            "blocking_finding_ids": [
                finding.rule_id
                for finding in quality_assessment.findings
                if finding.severity.value == "blocking"
                and finding.status.value in {"warning", "fail"}
            ],
            "major_finding_ids": [
                finding.rule_id
                for finding in quality_assessment.findings
                if finding.severity.value == "major" and finding.status.value in {"warning", "fail"}
            ],
            "artifacts": {
                name: path
                for name, path in output_files.items()
                if name.startswith("architectural_quality_")
            },
            "limitations": list(quality_assessment.limitations),
        },
        "output_files": output_files,
        "output_sha256": output_hashes,
        "assumptions": list(facade.assumptions),
        "warnings": list(facade.warnings) + list(selection.warnings),
    }
    if optimization_result is not None:
        baseline = optimization_result.baseline_candidate.quality_assessment
        selected = optimization_result.selected_candidate.quality_assessment
        payload["layout_optimization"] = {
            "schema_version": optimization_result.schema_version,
            "engine_version": optimization_result.engine_version,
            "mode": "optimized",
            "heuristic_notice": optimization_result.heuristic_notice,
            "selected_candidate_id": optimization_result.selected_candidate_id,
            "candidate_counts": {
                "generated": optimization_result.generated_candidate_count,
                "valid": optimization_result.valid_candidate_count,
                "rejected_or_duplicate": optimization_result.rejected_candidate_count,
            },
            "selected_transformation_ids": list(
                optimization_result.selected_candidate.transformation_ids
            ),
            "baseline_effective_score": baseline.overall_score,
            "selected_effective_score": selected.overall_score,
            "findings_improved": [
                item.rule_id
                for item in optimization_result.finding_comparison
                if item.change == "improved"
            ],
            "findings_worsened": [
                item.rule_id
                for item in optimization_result.finding_comparison
                if item.change == "worsened"
            ],
            "artifacts": {
                name: path for name, path in output_files.items() if name.startswith("layout_")
            },
            "limitations": list(optimization_result.limitations),
        }
    if sheet_export is not None:
        from saudi_plot_design.layout.geometry import geometry_fingerprint

        payload["architectural_sheets"] = {
            "schema_version": 1,
            "sheet_set_mode": sheet_export.mode,
            "graphic_profile_id": sheet_export.profile_id,
            "source_candidate_id": (
                optimization_result.selected_candidate_id
                if optimization_result is not None
                else "baseline"
            ),
            "source_geometry_fingerprint": geometry_fingerprint(concept),
            "sheet_numbers": list(sheet_export.sheet_numbers),
            "concept_pdf_path": sheet_export.concept_pdf_path,
            "review_pdf_path": sheet_export.review_pdf_path,
            "sheet_index_path": sheet_export.sheet_index_path,
            "sheet_manifest_path": sheet_export.sheet_manifest_path,
            "annotation_collision_report_path": sheet_export.collision_report_path,
            "svg_paths": list(sheet_export.svg_paths),
            "validation_status": sheet_export.validation_status,
            "annotation_collision_count": sheet_export.collision_count,
            "unresolved_annotation_collision_count": sheet_export.unresolved_collision_count,
            "artifacts": {
                name: path
                for name, path in output_files.items()
                if name in sheet_export.output_paths
            },
            "limitations": [
                "Concept sheets are not construction documents, permit drawings, or professional approval.",
                "Door swings and concept furniture are schematic presentation conventions only.",
            ],
        }
    return payload


def write_json(path: str | Path, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
