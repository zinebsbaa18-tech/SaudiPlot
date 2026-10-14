"""Deterministic JSON and CSV reporting for M6.2 layout optimization."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from saudi_plot_design.layout.models import LayoutCandidate, LayoutOptimizationResult
from saudi_plot_design.model import Concept, EXTERIOR
from saudi_plot_design.quality.models import FindingSeverity, FindingStatus, QualityCategory
from saudi_plot_design.route_semantics import concept_route_audit


def optimization_report_payload(result: LayoutOptimizationResult) -> dict:
    baseline = result.baseline_candidate
    selected = result.selected_candidate
    assert baseline.concept is not None and baseline.quality_assessment is not None
    assert selected.concept is not None and selected.quality_assessment is not None
    return {
        "schema_version": result.schema_version,
        "engine_version": result.engine_version,
        "disclaimer": result.disclaimer,
        "heuristic_notice": result.heuristic_notice,
        "search_config": result.config.model_dump(mode="json"),
        "candidate_counts": {
            "generated": result.generated_candidate_count,
            "valid": result.valid_candidate_count,
            "rejected_or_duplicate": result.rejected_candidate_count,
        },
        "ranking_rules": list(result.ranking_rules),
        "regression_policy": list(result.regression_policy),
        "baseline_candidate": _candidate_summary(baseline),
        "selected_candidate": _candidate_summary(selected),
        "candidates": [_candidate_summary(candidate) for candidate in result.candidates],
        "rejected_candidate_summary": [
            {
                "candidate_id": candidate.candidate_id,
                "transformations": list(candidate.transformation_ids),
                "code": candidate.rejection.code if candidate.rejection else "duplicate_geometry",
                "explanation": (
                    candidate.rejection.explanation
                    if candidate.rejection
                    else f"duplicates {candidate.duplicate_of_candidate_id}"
                ),
            }
            for candidate in result.candidates
            if not candidate.is_valid
        ],
        "selected_transformation_audit": [
            audit.model_dump(mode="json") for audit in selected.transformation_audit
        ],
        "quality_comparison": {
            "baseline": baseline.quality_assessment.model_dump(mode="json"),
            "selected": selected.quality_assessment.model_dump(mode="json"),
            "findings": [item.model_dump(mode="json") for item in result.finding_comparison],
        },
        "layout_comparison": _layout_comparison(baseline.concept, selected.concept),
        "limitations": list(result.limitations),
    }


def render_candidate_comparison_csv(result: LayoutOptimizationResult) -> str:
    columns = (
        "candidate_id",
        "parent_id",
        "transformations",
        "status",
        "rejection_reason",
        "raw_score",
        "effective_score",
        "quality_status",
        "room_usability",
        "privacy_zoning",
        "saudi_villa_functional",
        "circulation",
        "blocking_findings",
        "major_findings",
        "external_route_penalty",
        "disallowed_external_routes",
        "external_guest_wc_detours",
        "unknown_entrances_used_as_dedicated",
        "geometry_fingerprint",
        "selected",
        "disclaimer",
        "heuristic_notice",
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for candidate in result.candidates:
        assessment = candidate.quality_assessment
        writer.writerow(
            {
                "candidate_id": candidate.candidate_id,
                "parent_id": candidate.parent_candidate_id or "",
                "transformations": "|".join(candidate.transformation_ids),
                "status": "valid" if candidate.is_valid else "rejected",
                "rejection_reason": (
                    candidate.rejection.explanation if candidate.rejection else ""
                ),
                "raw_score": _score(assessment.raw_weighted_score if assessment else None),
                "effective_score": _score(assessment.overall_score if assessment else None),
                "quality_status": assessment.score_status.value if assessment else "",
                "room_usability": _category(assessment, QualityCategory.ROOM_USABILITY),
                "privacy_zoning": _category(assessment, QualityCategory.PRIVACY_ZONING),
                "saudi_villa_functional": _category(
                    assessment, QualityCategory.SAUDI_VILLA_FUNCTIONAL
                ),
                "circulation": _category(assessment, QualityCategory.CIRCULATION),
                "blocking_findings": _finding_count(assessment, FindingSeverity.BLOCKING),
                "major_findings": _finding_count(assessment, FindingSeverity.MAJOR),
                "external_route_penalty": (
                    candidate.route_penalties.total_penalty if candidate.route_penalties else ""
                ),
                "disallowed_external_routes": (
                    candidate.route_penalties.disallowed_external_routes
                    if candidate.route_penalties
                    else ""
                ),
                "external_guest_wc_detours": (
                    candidate.route_penalties.external_guest_wc_detours
                    if candidate.route_penalties
                    else ""
                ),
                "unknown_entrances_used_as_dedicated": (
                    candidate.route_penalties.unknown_entrances_used_as_dedicated
                    if candidate.route_penalties
                    else ""
                ),
                "geometry_fingerprint": candidate.geometry_fingerprint or "",
                "selected": str(candidate.candidate_id == result.selected_candidate_id).lower(),
                "disclaimer": result.disclaimer,
                "heuristic_notice": result.heuristic_notice,
            }
        )
    return stream.getvalue()


def write_optimization_report(path: str | Path, result: LayoutOptimizationResult) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(optimization_report_payload(result), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def write_candidate_comparison_csv(path: str | Path, result: LayoutOptimizationResult) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_candidate_comparison_csv(result), encoding="utf-8", newline="\n")
    return path


def _candidate_summary(candidate: LayoutCandidate) -> dict:
    assessment = candidate.quality_assessment
    return {
        "candidate_id": candidate.candidate_id,
        "parent_candidate_id": candidate.parent_candidate_id,
        "transformation_ids": list(candidate.transformation_ids),
        "geometry_fingerprint": candidate.geometry_fingerprint,
        "is_valid": candidate.is_valid,
        "eligible_for_selection": candidate.eligible_for_selection,
        "duplicate_of_candidate_id": candidate.duplicate_of_candidate_id,
        "validation": (
            candidate.validation.model_dump(mode="json") if candidate.validation else None
        ),
        "rejection": candidate.rejection.model_dump(mode="json") if candidate.rejection else None,
        "selection_rank": list(candidate.selection_rank) if candidate.selection_rank else None,
        "finding_regressions": [
            regression.model_dump(mode="json") for regression in candidate.finding_regressions
        ],
        "route_penalties": (
            candidate.route_penalties.model_dump(mode="json") if candidate.route_penalties else None
        ),
        "quality": _quality_summary(assessment),
    }


def _quality_summary(assessment) -> dict | None:
    if assessment is None:
        return None
    return {
        "raw_weighted_score": assessment.raw_weighted_score,
        "effective_overall_score": assessment.overall_score,
        "status": assessment.score_status.value,
        "category_scores": {
            category.value: score.evaluated_score
            for category, score in assessment.category_scores.items()
        },
        "blocking_findings": _finding_ids(assessment, FindingSeverity.BLOCKING),
        "major_findings": _finding_ids(assessment, FindingSeverity.MAJOR),
        "plan_metrics": assessment.plan_metrics.model_dump(mode="json"),
    }


def _layout_comparison(baseline: Concept, selected: Concept) -> dict:
    before_rooms = {room.id: room for room in baseline.rooms}
    after_rooms = {room.id: room for room in selected.rooms}
    return {
        "rooms": [
            {
                "room_id": room_id,
                "baseline": {
                    "width_m": before_rooms[room_id].width_m,
                    "length_m": before_rooms[room_id].length_m,
                    "area_m2": before_rooms[room_id].area_m2,
                },
                "selected": {
                    "width_m": after_rooms[room_id].width_m,
                    "length_m": after_rooms[room_id].length_m,
                    "area_m2": after_rooms[room_id].area_m2,
                },
            }
            for room_id in sorted(before_rooms)
        ],
        "wall_adjacencies": {
            "baseline": _wall_adjacencies(baseline),
            "selected": _wall_adjacencies(selected),
        },
        "entrance_and_route_semantics": {
            "baseline": concept_route_audit(baseline).model_dump(mode="json"),
            "selected": concept_route_audit(selected).model_dump(mode="json"),
        },
        "zone_transitions": {
            "baseline": _zone_transitions(baseline),
            "selected": _zone_transitions(selected),
        },
    }


def _wall_adjacencies(concept: Concept) -> list[list[str]]:
    return [
        list(sorted(wall.room_ids))
        for wall in sorted(concept.walls, key=lambda item: item.id)
        if not wall.is_external and len(wall.room_ids) == 2
    ]


def _zone_transitions(concept: Concept) -> list[dict]:
    rooms = {room.id: room for room in concept.rooms}
    transitions = []
    for door in sorted(concept.doors, key=lambda item: item.id):
        from_zone = "exterior" if door.from_space == EXTERIOR else rooms[door.from_space].zone.value
        to_zone = "exterior" if door.to_space == EXTERIOR else rooms[door.to_space].zone.value
        transitions.append(
            {
                "door_id": door.id,
                "from_space": door.from_space,
                "from_zone": from_zone,
                "to_space": door.to_space,
                "to_zone": to_zone,
            }
        )
    return transitions


def _finding_ids(assessment, severity: FindingSeverity) -> list[str]:
    return [
        finding.rule_id
        for finding in assessment.findings
        if finding.severity is severity
        and finding.status in {FindingStatus.WARNING, FindingStatus.FAIL}
    ]


def _finding_count(assessment, severity: FindingSeverity) -> int | str:
    return "" if assessment is None else len(_finding_ids(assessment, severity))


def _category(assessment, category: QualityCategory) -> str:
    if assessment is None:
        return ""
    return _score(assessment.category_scores[category].evaluated_score)


def _score(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


__all__ = [
    "optimization_report_payload",
    "render_candidate_comparison_csv",
    "write_candidate_comparison_csv",
    "write_optimization_report",
]
