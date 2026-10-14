"""Focused M6.1 architectural-quality diagnostics and integration tests."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest
from pydantic import ValidationError

from saudi_plot_design.elevation.facade_selection import select_primary_facade
from saudi_plot_design.elevation.front import generate_front_facade
from saudi_plot_design.export.pipeline import export_project
from saudi_plot_design.export.runlog import sha256_file
from saudi_plot_design.model import Door, Rect
from saudi_plot_design.output import DISCLAIMER
from saudi_plot_design.quality.criteria import load_criteria_profile
from saudi_plot_design.quality.evaluator import _score, evaluate_architectural_quality
from saudi_plot_design.quality.models import (
    ArchitecturalQualityAssessment,
    CoverageStatus,
    CriteriaProfile,
    FindingSeverity,
    FindingStatus,
    QualityCategory,
    QualityFinding,
    ScoreStatus,
)
from saudi_plot_design.quality.overlay import render_quality_overlay_svg
from saudi_plot_design.quality.reporting import (
    render_quality_summary_markdown,
    write_quality_report,
)
from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
from tests.conftest import reference_pipeline


@pytest.fixture(scope="module")
def state():
    result = reference_pipeline()
    result["rules"] = load_default_setback_rules()
    result["envelope"] = compute_envelope(result["plot"], result["rules"])
    result["selection"] = select_primary_facade(
        result["plot"], result["concept"], 0, user_confirmed=True
    )
    result["facade"] = generate_front_facade(
        result["plot"],
        result["concept"],
        result["selection"],
        result["match"],
        result["style_selection"],
        result["pack_ref"],
        result["pack_data"],
    )
    result["assessment"] = evaluate_architectural_quality(result["concept"], result["envelope"])
    return result


def finding(assessment, rule_id):
    return next(item for item in assessment.findings if item.rule_id == rule_id)


def replace_room(concept, room_id, **updates):
    rooms = tuple(
        room.model_copy(update=updates) if room.id == room_id else room for room in concept.rooms
    )
    return concept.model_copy(update={"rooms": rooms})


def assess(state, concept):
    return evaluate_architectural_quality(concept, state["envelope"])


def supported_pass_findings(assessment, **status_overrides):
    """Return synthetic evidence where every supported check passes unless overridden."""

    return tuple(
        item.model_copy(
            update={
                "status": status_overrides.get(item.rule_id, FindingStatus.PASS),
                "confidence": 1.0,
            }
        )
        if item.status is not FindingStatus.NOT_EVALUABLE
        else item
        for item in assessment.findings
    )


class TestCriteria:
    def test_category_weights_and_rule_contributions_validate(self):
        profile = load_criteria_profile()
        assert sum(profile.category_weights.values()) == pytest.approx(100.0)
        for category in QualityCategory:
            assert sum(
                rule.contribution_percent for rule in profile.rules if rule.category is category
            ) == pytest.approx(100.0)

    def test_invalid_weight_sum_rejected(self):
        payload = load_criteria_profile().model_dump(mode="json")
        payload["category_weights"]["geometric_validity"] = 17.0
        with pytest.raises(ValidationError, match="sum to 100"):
            CriteriaProfile.model_validate(payload)

    def test_non_demo_provenance_rejected(self):
        payload = load_criteria_profile().model_dump(mode="json")
        payload["provenance"]["level"] = "verified"
        with pytest.raises(ValidationError):
            CriteriaProfile.model_validate(payload)

    def test_rule_order_is_stable(self):
        profile = load_criteria_profile()
        categories = tuple(QualityCategory)
        assert list(profile.rules) == sorted(
            profile.rules,
            key=lambda rule: (categories.index(rule.category), rule.rule_id),
        )
        assert profile.rules[0].rule_id == "GEO-001"
        assert profile.rules[-1].rule_id == "SAU-006"

    def test_units_thresholds_and_room_criteria_are_explicit(self):
        profile = load_criteria_profile()
        assert profile.units["length"] == "meters"
        assert profile.units["score"] == "0_to_100_internal_indicator"
        assert profile.room_type_criteria["bedroom"].min_area_m2 > 0
        assert (
            profile.thresholds["max_circulation_ratio"]
            > profile.thresholds["preferred_circulation_ratio"]
        )

    def test_advisory_penalties_are_smaller_than_major_penalties(self):
        scoring = load_criteria_profile().scoring
        assert (
            scoring.warning_factors[FindingSeverity.ADVISORY]
            > scoring.warning_factors[FindingSeverity.MAJOR]
        )
        assert (
            scoring.fail_factors[FindingSeverity.ADVISORY]
            > scoring.fail_factors[FindingSeverity.MAJOR]
        )

    def test_geometry_and_program_do_not_outweigh_critical_architecture(self):
        weights = load_criteria_profile().category_weights
        assert weights[QualityCategory.GEOMETRIC_VALIDITY] == 15.0
        assert weights[QualityCategory.PROGRAM_COMPLETENESS] == 10.0
        assert (
            sum(
                weights[category]
                for category in (
                    QualityCategory.ROOM_USABILITY,
                    QualityCategory.PRIVACY_ZONING,
                    QualityCategory.CIRCULATION,
                    QualityCategory.SAUDI_VILLA_FUNCTIONAL,
                )
            )
            == 51.0
        )


class TestAssessmentCore:
    def test_reference_assessment_is_deterministic(self, state):
        first = state["assessment"]
        second = evaluate_architectural_quality(state["concept"], state["envelope"])
        assert first == second
        assert first.model_dump_json() == second.model_dump_json()

    def test_reference_plan_is_rated_without_blocking_failures(self, state):
        assessment = state["assessment"]
        assert assessment.overall_score is not None
        assert assessment.evaluation_confidence > 0.9
        assert not [
            item
            for item in assessment.findings
            if item.severity is FindingSeverity.BLOCKING and item.status is FindingStatus.FAIL
        ]

    def test_required_assessment_and_finding_fields_exist(self, state):
        required = {
            "assessment_version",
            "raw_weighted_score",
            "evidence_coverage",
            "coverage_adjusted_score",
            "overall_score",
            "score_status",
            "status_constraints",
            "category_floor_failures",
            "category_scores",
            "evaluated_checks",
            "passed_checks",
            "warning_checks",
            "failed_checks",
            "not_evaluable_checks",
            "findings",
            "room_assessments",
            "plan_metrics",
            "criteria_profile",
            "limitations",
        }
        assert required <= set(ArchitecturalQualityAssessment.model_fields)
        assert {
            "rule_id",
            "category",
            "severity",
            "status",
            "affected_object_ids",
            "title",
            "explanation",
            "evidence",
            "measured_value",
            "expected_value",
            "recommendation",
            "confidence",
            "source_method",
        } <= set(QualityFinding.model_fields)

    def test_not_evaluable_is_excluded_and_reduces_confidence(self, state):
        daylight = state["assessment"].category_scores[QualityCategory.DAYLIGHT_EXTERNAL_ACCESS]
        assert daylight.score == 100.0
        assert daylight.confidence == 0.7
        assert daylight.coverage_status is CoverageStatus.PARTIAL
        assert daylight.score_status is ScoreStatus.WORKABLE
        assert daylight.not_evaluable_checks == 1
        assert finding(state["assessment"], "DAY-004").status is FindingStatus.NOT_EVALUABLE

    def test_zero_evidence_is_unrated_instead_of_100(self, state):
        unsupported = tuple(
            item.model_copy(
                update={
                    "status": FindingStatus.NOT_EVALUABLE,
                    "confidence": 0.0,
                    "measured_value": None,
                }
            )
            for item in state["assessment"].findings
        )
        scoring = _score(unsupported, load_criteria_profile())
        assert scoring.raw_weighted_score is None
        assert scoring.overall_score is None
        assert scoring.score_status is ScoreStatus.NOT_RATED
        assert scoring.evidence_coverage == 0.0
        assert all(result.evaluated_checks == 0 for result in scoring.category_scores.values())

    def test_reference_score_and_constraints_are_calibrated(self, state):
        assessment = state["assessment"]
        assert assessment.assessment_version == "1.3.0"
        assert assessment.criteria_profile.profile_version == "1.2.0"
        assert assessment.raw_weighted_score == 88.83
        assert assessment.evidence_coverage == 0.917
        assert assessment.coverage_adjusted_score == 81.46
        assert assessment.overall_score == 81.46
        assert assessment.score_status is ScoreStatus.SUBSTANTIAL_REVISION
        assert [constraint.constraint_id for constraint in assessment.status_constraints] == [
            "critical_category_floor:room_usability",
            "multiple_unresolved_major_findings",
        ]
        assert [failure.category for failure in assessment.category_floor_failures] == [
            QualityCategory.ROOM_USABILITY
        ]

    def test_room_assessments_and_metrics_cover_canonical_rooms(self, state):
        assessment = state["assessment"]
        assert [item.room_id for item in assessment.room_assessments] == sorted(
            room.id for room in state["concept"].rooms
        )
        assert assessment.plan_metrics.room_count == len(state["concept"].rooms)
        assert assessment.plan_metrics.bedroom_count == 3


class TestScoringCalibration:
    def test_high_average_cannot_hide_critically_weak_usability(self, state):
        findings = supported_pass_findings(
            state["assessment"],
            **{
                "USE-001": FindingStatus.FAIL,
                "USE-002": FindingStatus.FAIL,
                "USE-003": FindingStatus.FAIL,
            },
        )
        scoring = _score(findings, load_criteria_profile())
        assert scoring.coverage_adjusted_score == pytest.approx(80.18, abs=0.01)
        assert scoring.category_scores[QualityCategory.ROOM_USABILITY].evaluated_score == 24.71
        assert scoring.score_status is ScoreStatus.UNSUITABLE
        assert scoring.category_floor_failures[0].category is QualityCategory.ROOM_USABILITY

    def test_one_major_finding_prevents_strong(self, state):
        findings = supported_pass_findings(
            state["assessment"],
            **{"PRO-001": FindingStatus.WARNING},
        )
        scoring = _score(findings, load_criteria_profile())
        assert scoring.coverage_adjusted_score is not None
        assert scoring.coverage_adjusted_score >= 85.0
        assert scoring.score_status is ScoreStatus.WORKABLE
        assert scoring.status_constraints[-1].constraint_id == (
            "multiple_unresolved_major_findings"
        )
        assert scoring.status_constraints[-1].affected_rule_ids == ("PRO-001",)

    def test_failed_major_in_critical_category_caps_at_substantial(self, state):
        findings = supported_pass_findings(state["assessment"], **{"USE-001": FindingStatus.FAIL})
        scoring = _score(findings, load_criteria_profile())
        assert scoring.coverage_adjusted_score is not None
        assert scoring.coverage_adjusted_score >= 85.0
        assert scoring.score_status is ScoreStatus.SUBSTANTIAL_REVISION
        assert "failed_major_critical_category" in {
            constraint.constraint_id for constraint in scoring.status_constraints
        }

    def test_critical_floors_are_configurable_without_hidden_constants(self, state):
        profile = load_criteria_profile()
        payload = profile.model_dump(mode="json")
        payload["scoring"]["critical_category_floors"]["room_usability"] = {
            "strong_min_score": 50.0,
            "workable_min_score": 40.0,
            "substantial_revision_min_score": 30.0,
        }
        relaxed = CriteriaProfile.model_validate(payload)
        first = _score(state["assessment"].findings, relaxed)
        second = _score(state["assessment"].findings, relaxed)
        assert first == second
        assert QualityCategory.ROOM_USABILITY not in {
            failure.category for failure in first.category_floor_failures
        }

    def test_constraint_order_is_deterministic_for_reordered_evidence(self, state):
        profile = load_criteria_profile()
        forward = _score(state["assessment"].findings, profile)
        reverse = _score(tuple(reversed(state["assessment"].findings)), profile)
        assert forward == reverse
        assert [item.constraint_id for item in forward.status_constraints] == [
            "critical_category_floor:room_usability",
            "multiple_unresolved_major_findings",
        ]

    def test_zero_major_findings_can_receive_strong(self, state):
        scoring = _score(supported_pass_findings(state["assessment"]), load_criteria_profile())
        assert scoring.raw_weighted_score == 100.0
        assert scoring.coverage_adjusted_score == 91.7
        assert scoring.score_status is ScoreStatus.STRONG
        assert scoring.status_constraints == ()
        assert scoring.category_floor_failures == ()

    def test_advisory_failure_does_not_force_low_status(self, state):
        findings = supported_pass_findings(state["assessment"], **{"WET-003": FindingStatus.FAIL})
        scoring = _score(findings, load_criteria_profile())
        assert scoring.score_status is ScoreStatus.STRONG
        assert scoring.status_constraints == ()


class TestGeometryAndUsabilityFindings:
    def test_room_overlap_detection(self, state):
        target = next(room for room in state["concept"].rooms if room.id == "bedroom_3")
        assessment = assess(state, replace_room(state["concept"], "bedroom_2", rect=target.rect))
        assert finding(assessment, "GEO-001").status is FindingStatus.FAIL

    def test_room_outside_envelope_detection(self, state):
        moved = Rect(min_x=100, min_y=100, max_x=104, max_y=104)
        assessment = assess(state, replace_room(state["concept"], "majlis", rect=moved))
        assert finding(assessment, "GEO-002").status is FindingStatus.FAIL

    def test_zero_area_room_detection(self, state):
        room = next(room for room in state["concept"].rooms if room.id == "entry")
        zero = Rect(
            min_x=room.rect.min_x,
            min_y=room.rect.min_y,
            max_x=room.rect.min_x,
            max_y=room.rect.max_y,
        )
        assessment = assess(state, replace_room(state["concept"], "entry", rect=zero))
        assert finding(assessment, "GEO-003").status is FindingStatus.FAIL

    def test_minimum_area_finding(self, state):
        room = next(room for room in state["concept"].rooms if room.id == "kitchen")
        small = Rect(
            min_x=room.rect.min_x,
            min_y=room.rect.min_y,
            max_x=room.rect.min_x + 1.5,
            max_y=room.rect.min_y + 2.0,
        )
        assessment = assess(state, replace_room(state["concept"], "kitchen", rect=small))
        assert finding(assessment, "USE-001").status is FindingStatus.FAIL
        assert "kitchen" in finding(assessment, "USE-001").affected_object_ids

    def test_minimum_dimension_finding(self, state):
        room = next(room for room in state["concept"].rooms if room.id == "maid_room")
        narrow = Rect(
            min_x=room.rect.min_x,
            min_y=room.rect.min_y,
            max_x=room.rect.min_x + 0.5,
            max_y=room.rect.max_y,
        )
        assessment = assess(state, replace_room(state["concept"], "maid_room", rect=narrow))
        assert finding(assessment, "USE-002").status is FindingStatus.FAIL
        assert finding(assessment, "GEO-004").status is FindingStatus.FAIL

    def test_aspect_ratio_finding(self, state):
        result = finding(state["assessment"], "USE-003")
        assert result.status is FindingStatus.FAIL
        assert result.affected_object_ids == ("corridor",)
        assert finding(state["assessment"], "GEO-005").status is FindingStatus.PASS

    def test_missing_room_boundaries(self, state):
        walls = tuple(wall for wall in state["concept"].walls if "bedroom_3" not in wall.room_ids)
        assessment = assess(state, state["concept"].model_copy(update={"walls": walls}))
        assert finding(assessment, "GEO-006").status is FindingStatus.FAIL

    def test_blocking_failure_caps_score(self, state):
        target = next(room for room in state["concept"].rooms if room.id == "bedroom_3")
        assessment = assess(state, replace_room(state["concept"], "bedroom_2", rect=target.rect))
        assert assessment.overall_score is not None
        assert assessment.overall_score <= 49.0
        assert assessment.score_status is ScoreStatus.UNSUITABLE
        assert assessment.status_constraints[0].constraint_id == "blocking_finding_cap"


class TestProgramTopologyAndZones:
    def test_missing_program_space(self, state):
        rooms = tuple(room for room in state["concept"].rooms if room.id != "kitchen")
        assessment = assess(state, state["concept"].model_copy(update={"rooms": rooms}))
        assert finding(assessment, "PRO-006").status is FindingStatus.FAIL

    def test_preferred_adjacency(self, state):
        result = finding(state["assessment"], "ADJ-001")
        assert result.status is FindingStatus.PASS
        assert result.measured_value == 1

    def test_discouraged_adjacency_and_public_private_conflict(self, state):
        door = Door(
            id="synthetic_public_private",
            wall_id="W08",
            from_space="majlis",
            to_space="master_bedroom",
            position_m=0.5,
            width_m=0.9,
        )
        concept = state["concept"].model_copy(update={"doors": state["concept"].doors + (door,)})
        assessment = assess(state, concept)
        assert finding(assessment, "ADJ-005").status is FindingStatus.FAIL
        assert finding(assessment, "PRI-002").status is FindingStatus.FAIL

    def test_disconnected_room_detection(self, state):
        doors = tuple(door for door in state["concept"].doors if door.id != "d_bedroom_3")
        assessment = assess(state, state["concept"].model_copy(update={"doors": doors}))
        assert finding(assessment, "CIR-001").status is FindingStatus.FAIL
        assert finding(assessment, "CIR-002").status is FindingStatus.FAIL
        assert "bedroom_3" in finding(assessment, "CIR-002").affected_object_ids

    def test_service_route_family_space_warning(self, state):
        result = finding(state["assessment"], "ADJ-006")
        assert result.status is FindingStatus.WARNING
        assert "maid_room" in result.affected_object_ids

    def test_guest_family_entry_sharing_is_reported(self, state):
        result = finding(state["assessment"], "SAU-005")
        assert result.status is FindingStatus.WARNING
        assert {"entry", "majlis"} <= set(result.affected_object_ids)


class TestEnvironmentalAndWetProxies:
    def test_external_wall_contact_proxy(self, state):
        walls = tuple(
            wall.model_copy(update={"is_external": False})
            if wall.is_external and "bedroom_2" in wall.room_ids
            else wall
            for wall in state["concept"].walls
        )
        assessment = assess(state, state["concept"].model_copy(update={"walls": walls}))
        assert finding(assessment, "DAY-001").status is FindingStatus.FAIL
        assert "bedroom_2" in finding(assessment, "DAY-001").affected_object_ids

    def test_invalidly_hosted_window_does_not_satisfy_opening_proxy(self, state):
        windows = tuple(
            window.model_copy(update={"wall_id": "W01"})
            if window.room_id == "bedroom_2"
            else window
            for window in state["concept"].windows
        )
        assessment = assess(state, state["concept"].model_copy(update={"windows": windows}))
        assert finding(assessment, "GEO-007").status is FindingStatus.FAIL
        assert finding(assessment, "DAY-002").status is FindingStatus.FAIL
        assert "bedroom_2" in finding(assessment, "DAY-002").affected_object_ids

    def test_daylight_compliance_is_not_evaluable(self, state):
        result = finding(state["assessment"], "DAY-004")
        assert result.status is FindingStatus.NOT_EVALUABLE
        assert result.confidence == 0.0
        assert "photometric" in result.explanation

    def test_wet_area_grouping_heuristic(self, state):
        grouping = finding(state["assessment"], "WET-001")
        fragmentation = finding(state["assessment"], "WET-002")
        assert grouping.status is FindingStatus.WARNING
        assert grouping.measured_value == 0.8
        assert grouping.affected_object_ids == ("shared_bath",)
        assert fragmentation.status is FindingStatus.WARNING
        assert fragmentation.measured_value == 3
        assert state["assessment"].plan_metrics.wet_cluster_count == 3

    def test_plumbing_conclusion_is_not_evaluable(self, state):
        result = finding(state["assessment"], "WET-004")
        assert result.status is FindingStatus.NOT_EVALUABLE
        assert "MEP" in result.explanation


class TestDeterministicArtifacts:
    def test_markdown_is_deterministic_and_complete(self, state):
        first = render_quality_summary_markdown(state["assessment"])
        second = render_quality_summary_markdown(state["assessment"])
        assert first == second
        assert DISCLAIMER in first
        assert "Raw weighted score" in first
        assert "Evidence coverage" in first
        assert "## Status constraints" in first
        assert "partial_evidence" in first
        assert "## Room usability" in first
        assert "## Not-evaluable checks" in first

    def test_svg_is_deterministic_and_well_formed(self, state):
        first = render_quality_overlay_svg(state["concept"], state["assessment"])
        second = render_quality_overlay_svg(state["concept"], state["assessment"])
        assert first == second
        root = ET.fromstring(first)
        assert root.tag.endswith("svg")
        assert DISCLAIMER in first
        assert "room-corridor" in first

    def test_json_report_is_deterministic(self, state, tmp_path):
        first = write_quality_report(tmp_path / "a.json", state["assessment"])
        second = write_quality_report(tmp_path / "b.json", state["assessment"])
        assert first.read_bytes() == second.read_bytes()
        assert json.loads(first.read_text(encoding="utf-8"))["disclaimer"] == DISCLAIMER


@pytest.fixture(scope="module")
def exported_quality(state, tmp_path_factory):
    out = tmp_path_factory.mktemp("m61-export")
    manifest = export_project(
        out,
        plot=state["plot"],
        envelope=state["envelope"],
        rules=state["rules"],
        concept=state["concept"],
        match=state["match"],
        style_selection=state["style_selection"],
        pack_ref=state["pack_ref"],
        pack_data=state["pack_data"],
        selection=state["selection"],
        facade=state["facade"],
        run_id="m61-quality-test",
        generation_timestamp="2026-07-14T00:00:00Z",
        source_inputs=["synthetic_reference_fixture"],
    )
    return out, manifest


class TestExportIntegration:
    def test_manifest_includes_verified_quality_hashes(self, exported_quality):
        out, manifest = exported_quality
        expected = {
            "architectural_quality_report.json",
            "architectural_quality_summary.md",
            "architectural_quality_overlay.svg",
        }
        assert expected <= set(manifest.file_sha256)
        for name in expected:
            assert manifest.file_sha256[name] == sha256_file(out / name)
            assert manifest.file_sizes_bytes[name] == (out / name).stat().st_size

    def test_run_json_contains_quality_summary_and_hashes(self, exported_quality):
        out, manifest = exported_quality
        payload = json.loads((out / "run.json").read_text(encoding="utf-8"))
        quality = payload["architectural_quality"]
        assert quality["assessment_version"] == "1.3.0"
        assert manifest.quality_assessment_version == "1.3.0"
        assert manifest.quality_criteria_profile_version == "1.2.0"
        assert quality["assessment_version"] == manifest.quality_assessment_version
        assert quality["criteria_profile"]["id"] == "saudi_villa_concept_v1"
        assert quality["raw_weighted_score"] == manifest.quality_raw_weighted_score
        assert quality["evidence_coverage"] == manifest.quality_evidence_coverage
        assert quality["coverage_adjusted_score"] == manifest.quality_coverage_adjusted_score
        assert quality["overall_score"] == manifest.quality_overall_score
        assert [item["constraint_id"] for item in quality["status_constraints"]] == list(
            manifest.quality_status_constraints
        )
        assert quality["disclaimer"] == DISCLAIMER
        for name in quality["artifacts"]:
            assert payload["output_sha256"][name] == sha256_file(out / name)

    def test_quality_artifacts_are_byte_deterministic(self, state, tmp_path):
        outputs = []
        for name in ("a", "b"):
            out = tmp_path / name
            export_project(
                out,
                plot=state["plot"],
                envelope=state["envelope"],
                rules=state["rules"],
                concept=state["concept"],
                match=state["match"],
                style_selection=state["style_selection"],
                pack_ref=state["pack_ref"],
                pack_data=state["pack_data"],
                selection=state["selection"],
                facade=state["facade"],
                run_id="m61-deterministic",
                generation_timestamp="2026-07-14T00:00:00Z",
            )
            outputs.append(out)
        for filename in (
            "architectural_quality_report.json",
            "architectural_quality_summary.md",
            "architectural_quality_overlay.svg",
            "run.json",
            "export_manifest.json",
        ):
            assert (outputs[0] / filename).read_bytes() == (outputs[1] / filename).read_bytes()

    def test_every_quality_artifact_carries_demo_disclaimer(self, exported_quality):
        out, _ = exported_quality
        for filename in (
            "architectural_quality_report.json",
            "architectural_quality_summary.md",
            "architectural_quality_overlay.svg",
        ):
            assert DISCLAIMER in (out / filename).read_text(encoding="utf-8")
