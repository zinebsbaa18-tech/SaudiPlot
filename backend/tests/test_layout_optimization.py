"""Focused M6.2 deterministic layout-improvement tests."""

from __future__ import annotations

import json

import pytest

from saudi_plot_design.cli import main
from saudi_plot_design.elevation.facade_selection import select_primary_facade
from saudi_plot_design.elevation.front import generate_front_facade
from saudi_plot_design.export.pipeline import export_project
from saudi_plot_design.export.runlog import sha256_file
from saudi_plot_design.layout.engine import _rank, _regression_guard, optimize_layout
from saudi_plot_design.layout.geometry import (
    LayoutGeometryError,
    geometry_fingerprint,
    opening_intents,
    rebuild_concept,
    replace_intent,
)
from saudi_plot_design.layout.models import SearchConfig, TransformationAudit
from saudi_plot_design.layout.overlay import render_optimization_overlay_svg
from saudi_plot_design.layout.reporting import (
    optimization_report_payload,
    render_candidate_comparison_csv,
)
from saudi_plot_design.layout.transformations import LayoutTransformation
from saudi_plot_design.model import EdgeClass, SpdInputError
from saudi_plot_design.output import DISCLAIMER
from saudi_plot_design.planner.compact_3br import plan_compact_3br
from saudi_plot_design.quality.models import FindingStatus, QualityCategory
from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
from tests.conftest import reference_pipeline


@pytest.fixture(scope="module")
def state():
    value = reference_pipeline()
    value["rules"] = load_default_setback_rules()
    value["envelope"] = compute_envelope(value["plot"], value["rules"])
    value["baseline_dump"] = value["concept"].model_dump_json()
    value["result"] = optimize_layout(value["concept"], value["envelope"])
    return value


def _candidate(state, *transformation_ids):
    return next(
        candidate
        for candidate in state["result"].candidates
        if candidate.transformation_ids == transformation_ids
    )


def _finding(candidate, rule_id):
    return next(
        finding for finding in candidate.quality_assessment.findings if finding.rule_id == rule_id
    )


def _empty_audit(transformation_id: str) -> TransformationAudit:
    return TransformationAudit(
        transformation_id=transformation_id,
        description="synthetic deterministic test transformation",
        affected_room_ids=(),
        affected_opening_ids=(),
        changes=(),
    )


class TestCandidateGeneration:
    def test_default_search_generates_exactly_32_candidates(self, state):
        assert len(state["result"].candidates) == 32

    def test_generation_is_byte_stable(self, state):
        second = optimize_layout(state["concept"], state["envelope"])
        first_ids = [
            (candidate.candidate_id, candidate.transformation_ids, candidate.geometry_fingerprint)
            for candidate in state["result"].candidates
        ]
        second_ids = [
            (candidate.candidate_id, candidate.transformation_ids, candidate.geometry_fingerprint)
            for candidate in second.candidates
        ]
        assert first_ids == second_ids

    def test_geometry_fingerprint_is_content_based(self, state):
        baseline = state["result"].baseline_candidate
        changed = _candidate(state, "M62-T01-front-room-rebalance")
        assert baseline.geometry_fingerprint == geometry_fingerprint(state["concept"])
        assert changed.geometry_fingerprint != baseline.geometry_fingerprint

    def test_duplicate_geometry_is_recorded_and_not_ranked(self, state):
        duplicate = LayoutTransformation(
            "M62-TEST-duplicate",
            "synthetic duplicate",
            lambda concept, _candidate_id: (concept, _empty_audit("M62-TEST-duplicate")),
        )
        result = optimize_layout(
            state["concept"],
            state["envelope"],
            config=SearchConfig(max_candidates=2, max_transformation_depth=1),
            transformations=(duplicate,),
        )
        attempt = result.candidates[1]
        assert attempt.duplicate_of_candidate_id == "candidate-000-baseline"
        assert attempt.rejection.code == "duplicate_geometry"
        assert not attempt.eligible_for_selection

    def test_candidate_limit_is_enforced(self, state):
        result = optimize_layout(
            state["concept"],
            state["envelope"],
            config=SearchConfig(max_candidates=7, max_transformation_depth=5),
        )
        assert len(result.candidates) == 7

    def test_transformation_depth_is_enforced(self, state):
        result = optimize_layout(
            state["concept"],
            state["envelope"],
            config=SearchConfig(max_candidates=32, max_transformation_depth=1),
        )
        assert len(result.candidates) == 6
        assert max(len(candidate.transformation_ids) for candidate in result.candidates) == 1

    def test_parent_ids_follow_canonical_prefixes(self, state):
        candidate = _candidate(
            state,
            "M62-T01-front-room-rebalance",
            "M62-T03-corridor-reproportion",
        )
        parent = _candidate(state, "M62-T01-front-room-rebalance")
        assert candidate.parent_candidate_id == parent.candidate_id

    def test_candidate_ids_are_stable_final_tiebreakers(self, state):
        candidate = _candidate(state, "M62-T01-front-room-rebalance")
        later = candidate.model_copy(update={"candidate_id": "candidate-999"})
        assert _rank(candidate) < _rank(later)


class TestGeometryAndTransformations:
    def test_front_partition_preserves_combined_band(self, state):
        candidate = _candidate(state, "M62-T01-front-room-rebalance")
        rooms = {room.id: room for room in candidate.concept.rooms}
        assert rooms["entry"].rect.max_x == rooms["guest_wc"].rect.min_x
        assert rooms["guest_wc"].rect.max_x == rooms["kitchen"].rect.min_x
        assert rooms["entry"].rect.min_x == 8.95
        assert rooms["kitchen"].rect.max_x == 16.75

    def test_adjacent_room_resize_preserves_shared_boundary(self, state):
        candidate = _candidate(state, "M62-T02-wet-service-rebalance")
        rooms = {room.id: room for room in candidate.concept.rooms}
        assert rooms["master_bath"].rect.max_x == rooms["laundry"].rect.min_x
        assert rooms["shared_bath"].rect.max_y == rooms["bedroom_2"].rect.min_y

    def test_door_relocation_on_valid_host_passes(self, state):
        intents = replace_intent(opening_intents(state["concept"]), "d_dining", center_fraction=0.7)
        concept = rebuild_concept(
            state["concept"],
            {room.id: room.rect for room in state["concept"].rooms},
            intents,
            concept_id="synthetic-door-relocation",
        )
        assert concept.is_valid
        assert next(door for door in concept.doors if door.id == "d_dining").position_m > 1.5

    def test_invalid_door_host_side_is_rejected(self, state):
        intents = replace_intent(opening_intents(state["concept"]), "d_main", external_side="E")
        with pytest.raises(LayoutGeometryError, match="no real host wall"):
            rebuild_concept(
                state["concept"],
                {room.id: room.rect for room in state["concept"].rooms},
                intents,
                concept_id="invalid-door-host",
            )

    def test_room_overlap_is_rejected(self, state):
        rects = {room.id: room.rect for room in state["concept"].rooms}
        rects["entry"] = rects["entry"].model_copy(update={"max_x": rects["entry"].max_x + 0.2})
        with pytest.raises(LayoutGeometryError, match="overlap"):
            rebuild_concept(
                state["concept"], rects, opening_intents(state["concept"]), concept_id="overlap"
            )

    def test_envelope_violation_is_rejected(self, state):
        rects = {room.id: room.rect for room in state["concept"].rooms}
        rects["majlis"] = rects["majlis"].model_copy(update={"min_x": 0.0})
        with pytest.raises(LayoutGeometryError, match="outside the footprint"):
            rebuild_concept(
                state["concept"], rects, opening_intents(state["concept"]), concept_id="outside"
            )

    def test_gap_in_room_union_is_rejected(self, state):
        rects = {room.id: room.rect for room in state["concept"].rooms}
        rects["entry"] = rects["entry"].model_copy(update={"max_x": rects["entry"].max_x - 0.1})
        with pytest.raises(LayoutGeometryError, match="does not exactly tile"):
            rebuild_concept(
                state["concept"], rects, opening_intents(state["concept"]), concept_id="gap"
            )

    def test_required_program_removal_is_rejected(self, state):
        rects = {room.id: room.rect for room in state["concept"].rooms if room.id != "maid_room"}
        with pytest.raises(LayoutGeometryError, match="program mismatch"):
            rebuild_concept(
                state["concept"], rects, opening_intents(state["concept"]), concept_id="missing"
            )

    def test_room_metrics_are_derived_from_rectangles(self, state):
        concept = state["result"].selected_concept
        for room in concept.rooms:
            assert room.width_m == round(room.rect.width, 6)
            assert room.length_m == round(room.rect.height, 6)
            assert room.area_m2 == round(room.rect.area, 6)

    def test_wet_service_transform_keeps_plumbing_validation(self, state):
        candidate = _candidate(state, "M62-T02-wet-service-rebalance")
        check = next(check for check in candidate.validation.checks if check.id == "C11")
        assert check.passed

    def test_corridor_reproportion_improves_aspect_ratio(self, state):
        candidate = _candidate(state, "M62-T03-corridor-reproportion")
        before = next(room for room in state["concept"].rooms if room.id == "corridor")
        after = next(room for room in candidate.concept.rooms if room.id == "corridor")
        assert max(after.width_m, after.length_m) / min(after.width_m, after.length_m) < (
            max(before.width_m, before.length_m) / min(before.width_m, before.length_m)
        )

    def test_service_access_remains_separate_from_internal_service_warning(self, state):
        candidate = _candidate(state, "M62-T04-direct-service-access")
        finding = _finding(candidate, "ADJ-006")
        assert finding.status is FindingStatus.WARNING
        assert finding.measured_value["supported_external_alternatives"] == 1

    def test_guest_route_transform_does_not_use_exit_reentry_for_credit(self, state):
        candidate = _candidate(state, "M62-T05-separate-guest-family-route")
        assert _finding(candidate, "SAU-005").status is FindingStatus.FAIL
        assert not candidate.eligible_for_selection

    def test_service_doors_use_real_nonstreet_walls(self, state):
        candidate = _candidate(state, "M62-T04-direct-service-access")
        walls = {wall.id: wall for wall in candidate.concept.walls}
        for opening_id in ("d_kitchen_service", "d_maid_service"):
            door = next(door for door in candidate.concept.doors if door.id == opening_id)
            wall = walls[door.wall_id]
            assert wall.is_external
            assert wall.start[0] == wall.end[0] == candidate.concept.footprint.max_x

    def test_transformation_audit_is_reversible(self, state):
        selected = state["result"].selected_candidate
        assert len(selected.transformation_audit) == 3
        for audit in selected.transformation_audit:
            assert audit.changes
            assert all(
                change.before is not None or change.after is not None for change in audit.changes
            )

    def test_baseline_object_is_never_mutated(self, state):
        assert state["concept"].model_dump_json() == state["baseline_dump"]


class TestQualityAndSelection:
    def test_every_valid_candidate_uses_calibrated_quality_profile(self, state):
        profiles = {
            (
                candidate.quality_assessment.criteria_profile.profile_id,
                candidate.quality_assessment.criteria_profile.profile_version,
            )
            for candidate in state["result"].candidates
            if candidate.quality_assessment is not None
        }
        assert profiles == {("saudi_villa_concept_v1", "1.2.0")}

    def test_selected_reference_with_two_majors_is_workable(self, state):
        selected = state["result"].selected_candidate
        assessment = selected.quality_assessment
        unresolved_major_ids = [
            finding.rule_id
            for finding in assessment.findings
            if finding.severity.value == "major"
            and finding.status in {FindingStatus.WARNING, FindingStatus.FAIL}
        ]
        assert selected.candidate_id == "candidate-016"
        assert assessment.overall_score == 88.89
        assert unresolved_major_ids == ["ADJ-006", "SAU-005"]
        assert assessment.score_status.value == "workable_with_targeted_revisions"
        assert [item.constraint_id for item in assessment.status_constraints] == [
            "multiple_unresolved_major_findings"
        ]

    def test_selected_candidate_has_no_blocking_findings(self, state):
        assessment = state["result"].selected_candidate.quality_assessment
        assert not [
            finding
            for finding in assessment.findings
            if finding.severity.value == "blocking"
            and finding.status in {FindingStatus.WARNING, FindingStatus.FAIL}
        ]

    def test_critical_floor_priority_precedes_total_score(self, state):
        baseline = state["result"].baseline_candidate
        selected = state["result"].selected_candidate
        assert len(selected.quality_assessment.category_floor_failures) < len(
            baseline.quality_assessment.category_floor_failures
        )
        assert selected.selection_rank[0] < baseline.selection_rank[0]

    def test_major_fail_priority_distinguishes_equal_major_counts(self, state):
        full = state["result"].selected_candidate
        four = _candidate(
            state,
            "M62-T01-front-room-rebalance",
            "M62-T02-wet-service-rebalance",
            "M62-T03-corridor-reproportion",
            "M62-T04-direct-service-access",
        )
        assert _rank(full) < _rank(four)

    def test_selected_candidate_improves_room_usability(self, state):
        baseline = state["result"].baseline_candidate.quality_assessment
        selected = state["result"].selected_candidate.quality_assessment
        assert (
            selected.category_scores[QualityCategory.ROOM_USABILITY].evaluated_score
            > baseline.category_scores[QualityCategory.ROOM_USABILITY].evaluated_score
        )

    def test_finding_comparison_records_resolved_and_introduced_tradeoffs(self, state):
        comparison = {item.rule_id: item.change for item in state["result"].finding_comparison}
        assert comparison["USE-001"] == "improved"
        assert comparison["USE-002"] == "improved"
        assert comparison["ADJ-006"] == "unchanged"
        assert comparison["SAU-005"] == "unchanged"
        assert comparison["ADJ-002"] == "unchanged"

    def test_loss_of_evaluable_evidence_is_rejected(self, state):
        baseline = state["result"].baseline_candidate.quality_assessment
        finding = next(item for item in baseline.findings if item.status is FindingStatus.PASS)
        changed_findings = tuple(
            item.model_copy(update={"status": FindingStatus.NOT_EVALUABLE})
            if item.rule_id == finding.rule_id
            else item
            for item in baseline.findings
        )
        candidate = baseline.model_copy(update={"findings": changed_findings})
        regressions, rejection = _regression_guard(baseline, candidate)
        assert rejection is not None
        assert next(
            item for item in regressions if item.rule_id == finding.rule_id
        ).disposition == ("rejected")

    @pytest.mark.parametrize("mirrored", [False, True])
    def test_quality_is_invariant_under_supported_orientation_transforms(self, state, mirrored):
        rotated = reference_pipeline(
            edges=(
                EdgeClass.NEIGHBOR,
                EdgeClass.NEIGHBOR,
                EdgeClass.STREET,
                EdgeClass.NEIGHBOR,
            )
        )
        envelope = compute_envelope(rotated["plot"], state["rules"])
        concept = plan_compact_3br(rotated["plot"], envelope, mirrored=mirrored)
        result = optimize_layout(concept, envelope)
        reference = state["result"].selected_candidate.quality_assessment
        selected = result.selected_candidate.quality_assessment
        assert selected.overall_score == reference.overall_score == 88.89
        assert selected.category_scores == reference.category_scores
        assert [(finding.rule_id, finding.status) for finding in selected.findings] == [
            (finding.rule_id, finding.status) for finding in reference.findings
        ]


class TestReportsAndExports:
    def test_json_payload_is_deterministic_and_complete(self, state):
        first = json.dumps(
            optimization_report_payload(state["result"]),
            sort_keys=True,
            ensure_ascii=False,
        )
        second = json.dumps(
            optimization_report_payload(optimize_layout(state["concept"], state["envelope"])),
            sort_keys=True,
            ensure_ascii=False,
        )
        assert first == second
        assert "layout_comparison" in json.loads(first)

    def test_csv_is_deterministic(self, state):
        assert render_candidate_comparison_csv(state["result"]) == render_candidate_comparison_csv(
            optimize_layout(state["concept"], state["envelope"])
        )

    def test_svg_is_deterministic(self, state):
        first = render_optimization_overlay_svg(state["result"])
        second = render_optimization_overlay_svg(
            optimize_layout(state["concept"], state["envelope"])
        )
        assert first == second
        assert "baseline-boundaries" in first
        assert DISCLAIMER in first

    def test_all_optimization_artifacts_embed_disclaimer(self, state):
        payload = json.dumps(optimization_report_payload(state["result"]), ensure_ascii=False)
        assert DISCLAIMER in payload
        assert DISCLAIMER in render_candidate_comparison_csv(state["result"])
        assert DISCLAIMER in render_optimization_overlay_svg(state["result"])

    def test_baseline_cli_remains_default_and_compatible(self, tmp_path):
        out = tmp_path / "baseline"
        code = main(
            [
                "generate",
                "--csv",
                "samples/plot_20x30.csv",
                "--lat",
                "24.65",
                "--lon",
                "46.71",
                "--edges",
                "street,neighbor,neighbor,neighbor",
                "--street-width",
                "15",
                "--confirm-character",
                "najdi",
                "--confirm-facade",
                "--out",
                str(out),
            ]
        )
        assert code == 0
        assert not list(out.glob("layout_*"))
        report = json.loads((out / "architectural_quality_report.json").read_text("utf-8"))
        assert report["overall_score"] == 81.46

    def test_optimized_cli_writes_three_optimization_artifacts(self, tmp_path):
        out = tmp_path / "optimized"
        code = main(
            [
                "generate",
                "--width",
                "20",
                "--depth",
                "30",
                "--lat",
                "24.65",
                "--lon",
                "46.71",
                "--edges",
                "street,neighbor,neighbor,neighbor",
                "--street-width",
                "15",
                "--confirm-character",
                "najdi",
                "--confirm-facade",
                "--layout-mode",
                "optimized",
                "--out",
                str(out),
            ]
        )
        assert code == 0
        assert {path.name for path in out.glob("layout_*")} == {
            "layout_optimization_report.json",
            "layout_candidate_comparison.csv",
            "layout_optimization_overlay.svg",
        }


@pytest.fixture(scope="module")
def optimized_exports(state, tmp_path_factory):
    outputs = []
    concept = state["result"].selected_concept
    selection = select_primary_facade(state["plot"], concept, 0, user_confirmed=True)
    facade = generate_front_facade(
        state["plot"],
        concept,
        selection,
        state["match"],
        state["style_selection"],
        state["pack_ref"],
        state["pack_data"],
    )
    for name in ("m62-a", "m62-b"):
        out = tmp_path_factory.mktemp(name)
        manifest = export_project(
            out,
            plot=state["plot"],
            envelope=state["envelope"],
            rules=state["rules"],
            concept=concept,
            match=state["match"],
            style_selection=state["style_selection"],
            pack_ref=state["pack_ref"],
            pack_data=state["pack_data"],
            selection=selection,
            facade=facade,
            run_id="m62-deterministic-test",
            generation_timestamp="2026-07-15T00:00:00Z",
            source_inputs=["sanitized_synthetic_reference", "layout_mode=optimized"],
            optimization_result=state["result"],
        )
        outputs.append((out, manifest))
    return outputs


class TestTransactionalIntegration:
    def test_pdf_and_dxf_are_deterministic_after_optimization(self, optimized_exports):
        first, second = optimized_exports
        for filename in ("saudi_plot_design_reference.pdf", "saudi_plot_design_reference.dxf"):
            assert (first[0] / filename).read_bytes() == (second[0] / filename).read_bytes()

    def test_json_csv_svg_run_and_manifest_are_deterministic(self, optimized_exports):
        first, second = optimized_exports
        for filename in (
            "layout_optimization_report.json",
            "layout_candidate_comparison.csv",
            "layout_optimization_overlay.svg",
            "run.json",
            "export_manifest.json",
        ):
            assert (first[0] / filename).read_bytes() == (second[0] / filename).read_bytes()

    def test_manifest_hashes_and_sizes_cover_optimization_artifacts(self, optimized_exports):
        out, manifest = optimized_exports[0]
        for filename in (
            "layout_optimization_report.json",
            "layout_candidate_comparison.csv",
            "layout_optimization_overlay.svg",
        ):
            assert manifest.file_sha256[filename] == sha256_file(out / filename)
            assert manifest.file_sizes_bytes[filename] == (out / filename).stat().st_size
        assert manifest.layout_mode == "optimized"
        assert manifest.schema_version == 2

    def test_run_json_records_selected_candidate_and_artifacts(self, optimized_exports):
        out, manifest = optimized_exports[0]
        payload = json.loads((out / "run.json").read_text("utf-8"))
        optimization = payload["layout_optimization"]
        assert optimization["selected_candidate_id"] == "candidate-016"
        assert optimization["candidate_counts"] == {
            "generated": 32,
            "valid": 16,
            "rejected_or_duplicate": 16,
        }
        assert set(optimization["artifacts"]) == {
            "layout_optimization_report.json",
            "layout_candidate_comparison.csv",
            "layout_optimization_overlay.svg",
        }
        assert manifest.layout_selected_candidate_id == "candidate-016"

    def test_invalid_or_mismatched_candidate_is_never_exported(self, state, tmp_path):
        baseline = state["concept"]
        selection = select_primary_facade(state["plot"], baseline, 0, user_confirmed=True)
        facade = generate_front_facade(
            state["plot"],
            baseline,
            selection,
            state["match"],
            state["style_selection"],
            state["pack_ref"],
            state["pack_data"],
        )
        with pytest.raises(SpdInputError, match="does not select the supplied concept"):
            export_project(
                tmp_path / "blocked",
                plot=state["plot"],
                envelope=state["envelope"],
                rules=state["rules"],
                concept=baseline,
                match=state["match"],
                style_selection=state["style_selection"],
                pack_ref=state["pack_ref"],
                pack_data=state["pack_data"],
                selection=selection,
                facade=facade,
                run_id="m62-invalid-export",
                generation_timestamp="2026-07-15T00:00:00Z",
                optimization_result=state["result"],
            )
        assert not (tmp_path / "blocked").exists()

    def test_stale_optimization_assessment_is_never_exported(self, state, tmp_path):
        concept = state["result"].selected_concept
        selection = select_primary_facade(state["plot"], concept, 0, user_confirmed=True)
        facade = generate_front_facade(
            state["plot"],
            concept,
            selection,
            state["match"],
            state["style_selection"],
            state["pack_ref"],
            state["pack_data"],
        )
        selected = state["result"].selected_candidate
        assessment = selected.quality_assessment.model_copy(
            update={"limitations": (*selected.quality_assessment.limitations, "tampered")}
        )
        stale_selected = selected.model_copy(update={"quality_assessment": assessment})
        stale_result = state["result"].model_copy(
            update={
                "candidates": tuple(
                    stale_selected if item.candidate_id == selected.candidate_id else item
                    for item in state["result"].candidates
                )
            }
        )
        with pytest.raises(SpdInputError, match="audit, or comparison are stale"):
            export_project(
                tmp_path / "stale",
                plot=state["plot"],
                envelope=state["envelope"],
                rules=state["rules"],
                concept=concept,
                match=state["match"],
                style_selection=state["style_selection"],
                pack_ref=state["pack_ref"],
                pack_data=state["pack_data"],
                selection=selection,
                facade=facade,
                run_id="m62-stale-export",
                generation_timestamp="2026-07-15T00:00:00Z",
                optimization_result=stale_result,
            )
        assert not (tmp_path / "stale").exists()
