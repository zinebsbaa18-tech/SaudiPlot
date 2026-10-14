"""Deterministic, evidence-only reusable feature extraction for M7.1."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from saudi_plot_design.cases.models import ArchitecturalDesignCase
from saudi_plot_design.library.models import (
    FeatureStatus,
    FeatureValue,
    QualitySummary,
    TemplateFeaturePackage,
)
from saudi_plot_design.quality.models import (
    ArchitecturalQualityAssessment,
    FindingSeverity,
    FindingStatus,
)

_ZERO_HASH = "0" * 64
FEATURE_GROUPS = (
    "site_and_massing",
    "program",
    "room_geometry",
    "zoning",
    "topology",
    "entrances",
    "facade_and_openings",
    "quality",
)


def quality_summary(
    assessment: ArchitecturalQualityAssessment | None,
) -> QualitySummary:
    if assessment is None:
        return QualitySummary(
            assessment_version="not_evaluated",
            raw_score=None,
            effective_score=None,
            evidence_coverage=None,
            score_status="not_evaluated_for_ingested_case",
            category_scores={},
            blocking_finding_ids=(),
            major_finding_ids=(),
            limitations=(
                "M6A descriptive metrics are not an M6 architectural-quality assessment.",
                "No professional, regulatory, cultural, or template-suitability claim is made.",
            ),
        )
    active = {FindingStatus.WARNING, FindingStatus.FAIL}
    return QualitySummary(
        assessment_version=assessment.assessment_version,
        raw_score=assessment.raw_weighted_score,
        effective_score=assessment.overall_score,
        evidence_coverage=assessment.evidence_coverage,
        score_status=assessment.score_status.value,
        category_scores={
            category.value: score.evaluated_score
            for category, score in assessment.category_scores.items()
        },
        blocking_finding_ids=tuple(
            finding.rule_id
            for finding in assessment.findings
            if finding.severity is FindingSeverity.BLOCKING and finding.status in active
        ),
        major_finding_ids=tuple(
            finding.rule_id
            for finding in assessment.findings
            if finding.severity is FindingSeverity.MAJOR and finding.status in active
        ),
        limitations=assessment.limitations,
    )


def extract_case_features(
    case: ArchitecturalDesignCase,
    *,
    case_version: str,
    canonical_case_fingerprint: str,
    assessment: ArchitecturalQualityAssessment | None = None,
    provenance_type: str = "m6a_canonical_case",
) -> TemplateFeaturePackage:
    """Extract only values evidenced by the canonical case and optional M6 report."""
    features: list[FeatureValue] = []

    def add(
        feature_id: str,
        group: str,
        value,
        unit: str,
        *,
        status: FeatureStatus = FeatureStatus.EXTRACTED,
        evidence: str = "m6a_canonical_case",
        review: str = "requires_review",
    ) -> None:
        features.append(
            FeatureValue(
                feature_id=feature_id,
                group=group,
                value=value,
                unit=unit,
                status=status,
                evidence_source=evidence,
                review_status=review,
            )
        )

    missing_site = (
        ("site.plot_shape", "shape"),
        ("site.plot_width", "m"),
        ("site.plot_depth", "m"),
        ("site.plot_area", "m2"),
        ("site.street_edge_count", "count"),
        ("site.street_widths", "m"),
        ("site.setbacks", "m"),
        ("site.buildable_envelope", "m"),
        ("massing.footprint_area", "m2"),
    )
    for feature_id, unit in missing_site:
        add(
            feature_id,
            "site_and_massing",
            None,
            unit,
            status=FeatureStatus.SOURCE_MISSING,
            evidence="m6a_does_not_extract_site_or_space_footprints",
        )
    add("massing.floor_count", "site_and_massing", case.metadata.number_of_floors, "count")
    total_area = (
        round(case.metrics.net_room_area_m2 + case.metrics.circulation_area_m2, 3)
        if case.metrics.area_metrics_complete
        else None
    )
    add(
        "massing.total_concept_area",
        "site_and_massing",
        total_area,
        "m2",
        status=(
            FeatureStatus.EXTRACTED if total_area is not None else FeatureStatus.SOURCE_MISSING
        ),
        evidence="m6a_source_space_quantities",
    )

    type_counts = Counter(space.space_type.value for space in case.spaces)
    service_types = {"kitchen", "maid_room", "laundry", "storage"}
    circulation_types = {"corridor", "stair", "elevator"}
    add("program.room_type_counts", "program", dict(sorted(type_counts.items())), "count")
    add("program.bedroom_count", "program", case.metrics.bedroom_count, "count")
    add("program.bathroom_count", "program", case.metrics.bathroom_count, "count")
    add("program.majlis_present", "program", bool(type_counts["mens_majlis"]), "boolean")
    add("program.family_living_present", "program", bool(type_counts["living"]), "boolean")
    add("program.kitchen_present", "program", bool(type_counts["kitchen"]), "boolean")
    add("program.maid_room_present", "program", bool(type_counts["maid_room"]), "boolean")
    add(
        "program.service_space_ids",
        "program",
        sorted(
            space.ifc_global_id for space in case.spaces if space.space_type.value in service_types
        ),
        "id_list",
    )
    add(
        "program.circulation_space_ids",
        "program",
        sorted(
            space.ifc_global_id
            for space in case.spaces
            if space.space_type.value in circulation_types
        ),
        "id_list",
    )
    add(
        "program.area_ratios",
        "program",
        dict(sorted(case.metrics.zone_area_ratios.items())),
        "ratio",
        status=(
            FeatureStatus.EXTRACTED
            if case.metrics.area_metrics_complete
            else FeatureStatus.REQUIRES_REVIEW
        ),
    )

    wall_by_id = {wall.ifc_global_id: wall for wall in case.walls}
    external_opening_spaces = {
        space_id
        for opening in (*case.doors, *case.windows)
        if opening.is_external
        for space_id in opening.connects_space_ids
    }
    room_records = []
    for space in sorted(case.spaces, key=lambda item: item.ifc_global_id):
        external_contact = any(
            wall_by_id[wall_id].is_external
            for wall_id in space.boundary_wall_ids
            if wall_id in wall_by_id
        )
        room_records.append(
            {
                "room_id": space.ifc_global_id,
                "room_type": space.space_type.value,
                "area_m2": space.area_m2,
                "clear_width_m": None,
                "clear_depth_m": None,
                "aspect_ratio": None,
                "perimeter_m": None,
                "external_wall_contact": external_contact,
                "external_opening": space.ifc_global_id in external_opening_spaces,
            }
        )
    add(
        "room_geometry.rooms",
        "room_geometry",
        room_records,
        "mixed",
        # Never "extracted": clear width/depth, aspect ratio, and perimeter
        # are unconditionally unavailable without M6A footprints, so the
        # record is always incomplete even when every area is present.
        status=FeatureStatus.REQUIRES_REVIEW,
        evidence="m6a_space_quantities_and_boundary_relationships_no_footprints",
    )

    assignments = [
        {
            "room_id": space.ifc_global_id,
            "zone": space.zone.value,
            "confidence": space.zone.confidence,
            "reviewer_status": space.zone.reviewer_status,
        }
        for space in sorted(case.spaces, key=lambda item: item.ifc_global_id)
    ]
    add("zoning.room_assignments", "zoning", assignments, "classification")
    add(
        "zoning.zone_area_ratios",
        "zoning",
        dict(sorted(case.metrics.zone_area_ratios.items())),
        "ratio",
        status=(
            FeatureStatus.EXTRACTED
            if case.metrics.area_metrics_complete
            else FeatureStatus.REQUIRES_REVIEW
        ),
    )
    add(
        "zoning.transition_matrix",
        "zoning",
        [
            {"from_zone": edge.a, "to_zone": edge.b, "relationship_count": 1}
            for edge in sorted(case.graphs.zone_adjacency, key=lambda edge: (edge.a, edge.b))
        ],
        "count",
        evidence="m6a_unique_zone_adjacency_pairs",
    )

    add(
        "topology.room_adjacency",
        "topology",
        [edge.model_dump(mode="json") for edge in case.graphs.room_adjacency],
        "edge_list",
    )
    add(
        "topology.door_connectivity",
        "topology",
        [edge.model_dump(mode="json") for edge in case.graphs.circulation],
        "edge_list",
    )
    add(
        "topology.circulation_summary",
        "topology",
        {
            "edge_count": len(case.graphs.circulation),
            "circulation_area_m2": case.metrics.circulation_area_m2,
            "circulation_percent": case.metrics.circulation_percent,
        },
        "mixed",
    )
    add(
        "topology.entrance_to_room_routes",
        "topology",
        {key: list(value) for key, value in sorted(case.graphs.entrance_paths.items())},
        "route",
    )
    add("topology.guest_route", "topology", list(case.graphs.guest_path), "room_id_list")
    add("topology.family_route", "topology", list(case.graphs.family_path), "room_id_list")
    add("topology.service_route", "topology", list(case.graphs.service_path), "room_id_list")
    add(
        "topology.wet_area_groups",
        "topology",
        [list(group) for group in case.graphs.wet_groups],
        "room_id_groups",
    )

    entrance_inventory = [
        {
            "door_id": entrance.door_id,
            "entrance_type": entrance.entrance_type.value,
            "confidence": entrance.entrance_type.confidence,
            "method": entrance.entrance_type.method,
            "reviewer_status": entrance.entrance_type.reviewer_status,
            "actual_door_evidence": True,
            "into_space_id": entrance.into_space_id,
        }
        for entrance in sorted(case.entrances, key=lambda item: item.door_id)
    ]
    add("entrances.inventory", "entrances", entrance_inventory, "entrance_list")
    for entrance_type, feature_id in (
        ("main_family_entrance", "entrances.family"),
        ("mens_majlis_entrance", "entrances.guest_majlis"),
        ("service_entrance", "entrances.service"),
    ):
        add(
            feature_id,
            "entrances",
            [item for item in entrance_inventory if item["entrance_type"] == entrance_type],
            "entrance_list",
        )
    add(
        "entrances.secondary",
        "entrances",
        [
            item
            for item in entrance_inventory
            if item["entrance_type"]
            not in {"main_family_entrance", "mens_majlis_entrance", "service_entrance"}
        ],
        "entrance_list",
    )

    opening_by_id = {opening.ifc_global_id: opening for opening in (*case.doors, *case.windows)}
    facade_inventory = [
        opening_by_id[opening_id].model_dump(mode="json")
        for opening_id in sorted(case.facade_openings)
        if opening_id in opening_by_id
    ]
    level_counts = Counter(opening["level_id"] for opening in facade_inventory)
    add(
        "facade.opening_inventory",
        "facade_and_openings",
        facade_inventory,
        "opening_list",
    )
    add(
        "facade.opening_counts_by_level",
        "facade_and_openings",
        dict(sorted(level_counts.items())),
        "count",
    )
    add(
        "facade.opening_counts_by_facade",
        "facade_and_openings",
        None,
        "count",
        status=FeatureStatus.SOURCE_MISSING,
        evidence="m6a_has_external_opening_inventory_but_no_facade_orientation",
    )
    add(
        "facade.window_to_room_relationships",
        "facade_and_openings",
        {
            window.ifc_global_id: list(window.connects_space_ids)
            for window in sorted(case.windows, key=lambda item: item.ifc_global_id)
        },
        "relationship",
    )
    add(
        "facade.front_elevation_proportions",
        "facade_and_openings",
        None,
        "ratio",
        status=FeatureStatus.SOURCE_MISSING,
        evidence="m6a_semantic_ifc_reader_does_not_derive_elevation_geometry",
    )
    add(
        "facade.architectural_character",
        "facade_and_openings",
        case.metadata.architectural_character,
        "classification",
        evidence="declared_case_metadata",
    )

    summary = quality_summary(assessment)
    add(
        "quality.assessment",
        "quality",
        summary.model_dump(mode="json"),
        "assessment",
        status=(
            FeatureStatus.EXTRACTED if assessment is not None else FeatureStatus.SOURCE_MISSING
        ),
        evidence=("m6_architectural_quality_assessment" if assessment else "not_evaluated"),
    )

    ordered = tuple(sorted(features, key=lambda feature: feature.feature_id))
    package = TemplateFeaturePackage(
        case_id=case.case_id,
        case_version=case_version,
        canonical_case_fingerprint=canonical_case_fingerprint,
        provenance_type=provenance_type,
        features=ordered,
        limitations=(
            "No missing geometry, dimensions, routes, or facade orientation are inferred.",
            "M6A has no space footprints, so clear dimensions, perimeters, aspect ratios, and footprint area remain unavailable.",
            "Feature extraction performs no embedding, similarity ranking, learned weighting, retrieval, or adaptation.",
        ),
        feature_fingerprint=_ZERO_HASH,
    )
    payload = package.model_dump(mode="json", exclude={"case_version", "feature_fingerprint"})
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    return package.model_copy(update={"feature_fingerprint": fingerprint})


__all__ = ["FEATURE_GROUPS", "extract_case_features", "quality_summary"]
