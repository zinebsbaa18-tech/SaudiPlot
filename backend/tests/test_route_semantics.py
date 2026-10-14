"""Focused synthetic tests for M6.2.1 entrance and route semantics."""

from __future__ import annotations

import pytest

from saudi_plot_design.layout.engine import _rank, optimize_layout
from saudi_plot_design.layout.transformations import TRANSFORMATIONS
from saudi_plot_design.model import EXTERIOR
from saudi_plot_design.quality.evaluator import evaluate_architectural_quality
from saudi_plot_design.quality.models import FindingStatus
from saudi_plot_design.route_review import (
    render_candidate_ranking_comparison_csv,
    render_entrance_inventory_csv,
    render_entrance_route_overlay_svg,
    render_route_semantics_comparison_csv,
)
from saudi_plot_design.route_semantics import (
    EXTERNAL_PATH_NODE,
    EntranceType,
    RouteType,
    analyze_room_route,
    classify_entrances,
    entrance_separation_evidence,
    route_from_entrance,
    route_penalty_summary,
)
from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
from tests.conftest import reference_pipeline


@pytest.fixture(scope="module")
def state():
    value = reference_pipeline()
    envelope = compute_envelope(value["plot"], load_default_setback_rules())
    result = optimize_layout(value["concept"], envelope)
    return {**value, "envelope": envelope, "result": result}


def _candidate(state, *transformation_ids):
    return next(
        candidate
        for candidate in state["result"].candidates
        if candidate.transformation_ids == transformation_ids
    )


def _with_door_tag(concept, door_id: str, entrance_type: str | None):
    return concept.model_copy(
        update={
            "doors": tuple(
                door.model_copy(update={"entrance_type": entrance_type})
                if door.id == door_id
                else door
                for door in concept.doors
            )
        }
    )


def _finding(candidate, rule_id: str):
    return next(
        finding for finding in candidate.quality_assessment.findings if finding.rule_id == rule_id
    )


class TestEntranceInventory:
    def test_distinct_external_doors_are_not_one_zero_cost_node(self, state):
        graph_route = analyze_room_route(
            state["concept"], "entry", "majlis", RouteType.GENERAL
        ).preferred_route
        assert graph_route.path_kind == "internal"
        assert graph_route.door_ids == ("d_majlis_entry",)
        assert EXTERIOR not in graph_route.room_sequence

    def test_wall_contact_does_not_create_entrance(self, state):
        inventory = classify_entrances(state["concept"])
        assert "master_bedroom" not in {item.internal_room_id for item in inventory}
        assert len(inventory) == 2

    def test_family_guest_and_service_classification(self, state):
        t04 = _candidate(state, "M62-T04-direct-service-access")
        types = {item.door_id: item.entrance_type for item in classify_entrances(t04.concept)}
        assert types == {
            "d_kitchen_service": EntranceType.SERVICE,
            "d_maid_service": EntranceType.SERVICE,
            "d_main": EntranceType.FAMILY_MAIN,
            "d_majlis_ext": EntranceType.GUEST_MAJLIS,
        }

    def test_unknown_entrance_requires_review(self, state):
        concept = _with_door_tag(state["concept"], "d_main", None)
        item = next(item for item in classify_entrances(concept) if item.door_id == "d_main")
        assert item.entrance_type is EntranceType.UNKNOWN
        assert item.requires_review
        assert item.confidence == 0.0

    def test_unknown_guest_intent_does_not_receive_quality_credit(self, state):
        concept = _with_door_tag(state["concept"], "d_majlis_ext", None)
        assessment = evaluate_architectural_quality(concept, state["envelope"])
        sau002 = next(item for item in assessment.findings if item.rule_id == "SAU-002")
        sau005 = next(item for item in assessment.findings if item.rule_id == "SAU-005")
        assert sau002.status is FindingStatus.NOT_EVALUABLE
        assert sau005.status is FindingStatus.NOT_EVALUABLE

    def test_invalid_external_door_geometry_cannot_supply_entrance_credit(self, state):
        concept = state["concept"].model_copy(
            update={
                "doors": tuple(
                    door.model_copy(update={"position_m": 100.0}) if door.id == "d_main" else door
                    for door in state["concept"].doors
                )
            }
        )
        item = next(item for item in classify_entrances(concept) if item.door_id == "d_main")
        route = route_from_entrance(
            concept, EntranceType.FAMILY_MAIN, "family_living", RouteType.FAMILY
        )
        assert item.requires_review and item.confidence == 0.0
        assert not route.available

    def test_classification_is_deterministic(self, state):
        first = tuple(item.model_dump_json() for item in classify_entrances(state["concept"]))
        second = tuple(item.model_dump_json() for item in classify_entrances(state["concept"]))
        assert first == second


class TestRoutePolicy:
    def test_separation_requires_distinct_supported_doors(self, state):
        baseline = entrance_separation_evidence(state["concept"])
        assert baseline.distinct_real_entrance_doors
        missing_guest = entrance_separation_evidence(
            _with_door_tag(state["concept"], "d_majlis_ext", None)
        )
        assert not missing_guest.distinct_real_entrance_doors
        assert missing_guest.requires_review

    def test_guest_wc_exit_reentry_remains_penalized(self, state):
        candidate = _candidate(
            state,
            "M62-T01-front-room-rebalance",
            "M62-T02-wet-service-rebalance",
            "M62-T03-corridor-reproportion",
            "M62-T04-direct-service-access",
            "M62-T05-separate-guest-family-route",
        )
        route = analyze_room_route(
            candidate.concept, "majlis", "guest_wc", RouteType.GUEST_WC
        ).preferred_route
        penalties = route_penalty_summary(candidate.concept)
        assert route.uses_external_path and not route.allowed
        assert penalties.external_guest_wc_detours == 1
        assert penalties.total_penalty > 0

    def test_internal_guest_wc_route_ranks_above_external_detour(self, state):
        internal = state["result"].selected_candidate
        external = _candidate(
            state,
            "M62-T01-front-room-rebalance",
            "M62-T02-wet-service-rebalance",
            "M62-T03-corridor-reproportion",
            "M62-T04-direct-service-access",
            "M62-T05-separate-guest-family-route",
        )
        comparable = external.model_copy(
            update={
                "quality_assessment": internal.quality_assessment,
                "finding_regressions": internal.finding_regressions,
                "rejection": None,
                "eligible_for_selection": True,
            }
        )
        assert _rank(internal) < _rank(comparable)

    def test_service_external_alternative_is_not_internal_access(self, state):
        candidate = _candidate(state, "M62-T04-direct-service-access")
        analysis = analyze_room_route(candidate.concept, "kitchen", "maid_room", RouteType.SERVICE)
        assert analysis.preferred_route.path_kind == "internal"
        assert analysis.preferred_route.door_ids == ("d_kitchen", "d_maid")
        supported = [route for route in analysis.external_routes if route.allowed]
        assert len(supported) == 1
        assert supported[0].external_path_classification == "supported_service_external_route"
        assert supported[0].requires_review

    def test_generic_exterior_path_cannot_resolve_privacy(self, state):
        candidate = _candidate(
            state,
            "M62-T05-separate-guest-family-route",
        )
        assert _finding(candidate, "PRI-003").status is FindingStatus.FAIL
        assert _finding(candidate, "SAU-005").status is FindingStatus.FAIL

    def test_external_route_identifies_both_real_doors(self, state):
        candidate = _candidate(state, "M62-T05-separate-guest-family-route")
        route = analyze_room_route(
            candidate.concept, "majlis", "guest_wc", RouteType.GUEST_WC
        ).preferred_route
        assert route.exit_door_id == "d_majlis_ext"
        assert route.reentry_door_id == "d_main"
        assert EXTERNAL_PATH_NODE in route.room_sequence
        assert {route.exit_door_id, route.reentry_door_id} <= set(route.door_ids)

    def test_external_cost_includes_door_crossings_and_traversal(self, state):
        candidate = _candidate(state, "M62-T05-separate-guest-family-route")
        route = analyze_room_route(
            candidate.concept, "majlis", "guest_wc", RouteType.GUEST_WC
        ).preferred_route
        assert route.external_door_steps == 2
        assert route.external_traversal_steps == 2
        assert route.total_cost == (
            route.internal_door_steps + route.external_door_steps + route.external_traversal_steps
        )


class TestTransformAndRanking:
    def test_t04_description_matches_external_alternative(self, state):
        candidate = _candidate(state, "M62-T04-direct-service-access")
        assert "exterior service doors" in candidate.transformation_audit[0].description
        assert "not direct internal access" in candidate.transformation_audit[0].description

    def test_t05_rejects_absent_entrance_geometry(self, state):
        t05 = next(
            item
            for item in TRANSFORMATIONS
            if item.transformation_id == "M62-T05-separate-guest-family-route"
        )
        missing_guest = _with_door_tag(state["concept"], "d_majlis_ext", None)
        with pytest.raises(ValueError, match="distinct valid authored"):
            t05.apply(missing_guest, "synthetic-missing-guest-entrance")

    def test_candidate_rank_contains_external_detour_penalties(self, state):
        selected = state["result"].selected_candidate
        assert selected.route_penalties.total_penalty == 0
        previous = next(
            candidate
            for candidate in state["result"].candidates
            if candidate.candidate_id == "candidate-031"
        )
        assert previous.route_penalties.total_penalty == 174
        assert previous.route_penalties.disallowed_external_routes == 1

    def test_candidate_ranking_is_deterministic(self, state):
        second = optimize_layout(state["concept"], state["envelope"])
        assert state["result"].selected_candidate_id == second.selected_candidate_id
        assert [candidate.selection_rank for candidate in state["result"].candidates] == [
            candidate.selection_rank for candidate in second.candidates
        ]


class TestReviewArtifactDeterminism:
    def test_route_review_csvs_are_deterministic(self, state):
        second = optimize_layout(state["concept"], state["envelope"])
        renderers = (
            render_entrance_inventory_csv,
            render_route_semantics_comparison_csv,
            render_candidate_ranking_comparison_csv,
        )
        for renderer in renderers:
            assert renderer(state["result"]) == renderer(second)

    def test_route_review_svg_is_deterministic_and_explicit(self, state):
        first = render_entrance_route_overlay_svg(state["result"])
        second = render_entrance_route_overlay_svg(
            optimize_layout(state["concept"], state["envelope"])
        )
        assert first == second
        assert "exit=d_majlis_ext | re-entry=d_main" in first
        assert "family_main" in first
        assert "service" in first
        assert "Unsupported/unknown entrances: none" in first
