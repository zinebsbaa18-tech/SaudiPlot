"""Tests for the facade gate, projection, template, and reference case (M4)."""

import pytest

from saudi_plot_design.character.models import SelectionMethod
from saudi_plot_design.character.selection import override_selection, recommend_style
from saudi_plot_design.elevation.facade_selection import select_primary_facade
from saudi_plot_design.elevation.front import facade_generation_gate, generate_front_facade
from saudi_plot_design.model import EdgeClass
from tests.conftest import reference_pipeline

ARABIC_LOGICAL = "الطابع النجدي التجريبي"
ARABIC_REVERSED = "يبيرجتلا يدجنلا عباطلا"


@pytest.fixture(scope="module")
def state():
    return reference_pipeline()


@pytest.fixture(scope="module")
def selection(state):
    return select_primary_facade(state["plot"], state["concept"], 0, user_confirmed=True)


@pytest.fixture(scope="module")
def facade(state, selection):
    return generate_front_facade(
        state["plot"],
        state["concept"],
        selection,
        state["match"],
        state["style_selection"],
        state["pack_ref"],
        state["pack_data"],
    )


def generate(state, selection, **overrides):
    args = {
        "plot": state["plot"],
        "concept": state["concept"],
        "selection": selection,
        "match": state["match"],
        "style_selection": state["style_selection"],
        "pack_ref": state["pack_ref"],
        "pack_data": state["pack_data"],
    }
    args.update(overrides)
    return generate_front_facade(
        args["plot"],
        args["concept"],
        args["selection"],
        args["match"],
        args["style_selection"],
        args["pack_ref"],
        args["pack_data"],
    )


class TestGate:
    def test_unconfirmed_facade_blocked(self, state):
        unconfirmed = select_primary_facade(
            state["plot"], state["concept"], 0, user_confirmed=False
        )
        gate = facade_generation_gate(
            state["plot"],
            state["concept"],
            unconfirmed,
            state["match"],
            state["style_selection"],
            state["pack_ref"],
        )
        assert not gate.passed
        assert any("not user-confirmed" in r for r in gate.reasons)

    def test_blocked_before_style_confirmation(self, state, selection):
        zone_pack = state["dataset"].zone_by_id(state["match"].selected_zone_id).style_pack_id
        unconfirmed_style = recommend_style(state["match"], zone_pack)
        gate = facade_generation_gate(
            state["plot"],
            state["concept"],
            selection,
            state["match"],
            unconfirmed_style,
            state["pack_ref"],
        )
        assert not gate.passed
        assert any("style gate" in r for r in gate.reasons)

    def test_confirmed_style_passes_gate(self, state, selection):
        gate = facade_generation_gate(
            state["plot"],
            state["concept"],
            selection,
            state["match"],
            state["style_selection"],
            state["pack_ref"],
        )
        assert gate.passed

    def test_zone_incompatible_pack_blocked_without_override(self, state, selection):
        forced = state["style_selection"].model_copy(update={"override_reason": None})
        hejazi = reference_pipeline(location=(21.5, 39.2))
        gate = facade_generation_gate(
            state["plot"],
            state["concept"],
            selection,
            hejazi["match"],
            forced,
            state["pack_ref"],
        )
        assert not gate.passed
        assert any("not declared applicable" in r for r in gate.reasons)

    def test_override_with_reason_passes_and_generates(self, state, selection):
        hejazi = reference_pipeline(location=(21.5, 39.2))
        base = recommend_style(hejazi["match"], None)
        overridden = override_selection(
            base, state["pack_ref"], "client requested Najdi style outside its demo zone"
        )
        facade = generate(state, selection, match=hejazi["match"], style_selection=overridden)
        assert facade.is_valid
        assert facade.style_selection_method == SelectionMethod.MANUAL_OVERRIDE.value

    def test_no_facing_wall_is_structured_rejection(self, state):
        # Synthetic concept with all street-facing walls stripped: the gate
        # rejects with a specific reason instead of fabricating an elevation.
        fp = state["concept"].footprint
        walls = tuple(
            w
            for w in state["concept"].walls
            if not (w.is_external and w.start[1] == fp.min_y and w.end[1] == fp.min_y)
        )
        stripped = state["concept"].model_copy(update={"walls": walls})
        empty_selection = select_primary_facade(state["plot"], stripped, 0, user_confirmed=True)
        facade = generate(state, empty_selection, concept=stripped)
        assert not facade.is_valid
        assert any("no building wall faces" in r for r in facade.rejection_reasons)
        assert facade.facade_openings == ()


class TestReferenceFacade:
    def test_reference_facade_passes_all_24_checks(self, facade):
        assert facade.is_valid
        assert len(facade.validation.checks) == 24
        assert facade.validation.passed

    def test_real_doors_project(self, facade):
        doors = [o for o in facade.facade_openings if o.opening_type == "door"]
        assert {d.source_plan_opening_id for d in doors} == {"d_main", "d_majlis_ext"}

    def test_real_windows_project(self, facade):
        windows = [o for o in facade.facade_openings if o.opening_type == "window"]
        assert {w.source_plan_opening_id for w in windows} == {
            "w_majlis_1",
            "w_majlis_2",
            "w_kitchen",
        }

    def test_entrances_identified(self, facade):
        entrance_types = {o.entrance_type for o in facade.facade_openings if o.entrance_type}
        assert entrance_types == {"main", "majlis"}

    def test_pack_governs_heights(self, facade, state):
        dims = state["pack_data"].facade_rules.facade_dimensions
        for o in facade.facade_openings:
            if o.opening_type == "window":
                assert o.sill_elevation_m == dims.window_sill_height_m
                assert o.head_elevation_m == dims.window_head_height_m
            else:
                assert o.head_elevation_m == dims.door_head_height_m

    def test_no_fake_openings(self, facade, state):
        plan_openings = {d.id for d in state["concept"].doors} | {
            w.id for w in state["concept"].windows
        }
        for o in facade.facade_openings:
            assert o.source_plan_opening_id in plan_openings

    def test_deterministic_json(self, state, selection, facade):
        again = generate(state, selection)
        assert facade.model_dump_json() == again.model_dump_json()

    def test_arabic_name_stored_in_logical_order(self, state, facade):
        from saudi_plot_design.output import facade_concept_report
        import json

        assert state["pack_ref"].name_ar == ARABIC_LOGICAL
        payload = json.dumps(facade_concept_report(facade), ensure_ascii=False)
        assert ARABIC_REVERSED not in payload

    def test_window_ratio_conflict_is_unsupported_state(self, state, selection):
        dims = state["pack_data"].facade_rules.facade_dimensions
        narrow = dims.model_copy(update={"window_sill_height_m": 2.0})  # height 0.6
        rules = state["pack_data"].facade_rules.model_copy(update={"facade_dimensions": narrow})
        pack_data = state["pack_data"].model_copy(update={"facade_rules": rules})
        facade = generate(state, selection, pack_data=pack_data)
        assert not facade.is_valid
        assert any("outside the pack range" in r for r in facade.rejection_reasons)


class TestReviewRegressions:
    """Regression tests for Codex M4 review findings."""

    def test_skewed_plot_within_m1_tolerance_generates(self):
        # P1: a street edge sloping 0.02 m (M1-accepted) must not lose its
        # facade to an over-strict parallel tolerance.
        from saudi_plot_design.character.engine import load_zone_dataset, recommend_character
        from saudi_plot_design.character.models import LocationPoint
        from saudi_plot_design.character.selection import confirm_selection, recommend_style
        from saudi_plot_design.planner.compact_3br import plan_compact_3br
        from saudi_plot_design.plot.geometry import build_plot_model
        from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
        from saudi_plot_design.styles.loader import load_pilot_style_pack
        from tests.conftest import standard_edges

        skewed_corners = ((0.0, 0.0), (20.0, 0.02), (20.0, 30.02), (0.0, 30.0))
        plot, _ = build_plot_model(skewed_corners, standard_edges(), 15.0, (24.65, 46.71))
        envelope = compute_envelope(plot, load_default_setback_rules())
        concept = plan_compact_3br(plot, envelope)
        assert concept.is_valid
        dataset = load_zone_dataset()
        pack_ref, pack_data = load_pilot_style_pack(
            known_zone_ids=tuple(z.zone_id for z in dataset.zones)
        )
        match = recommend_character(dataset, LocationPoint(latitude=24.65, longitude=46.71))
        zone_pack = dataset.zone_by_id(match.selected_zone_id).style_pack_id
        style = confirm_selection(recommend_style(match, zone_pack), pack_ref)
        selection = select_primary_facade(plot, concept, 0, user_confirmed=True)
        assert selection.selected_building_wall_ids  # walls found despite skew
        facade = generate_front_facade(plot, concept, selection, match, style, pack_ref, pack_data)
        assert facade.is_valid

    def test_missing_facing_segment_fails_validation(self, state, selection, facade):
        # P1: a subset selection must not silently shorten the facade.
        from saudi_plot_design.elevation.validation import validate_facade

        subset = selection.model_copy(
            update={"selected_building_wall_ids": selection.selected_building_wall_ids[:-1]}
        )
        report = validate_facade(
            facade,
            state["plot"],
            state["concept"],
            subset,
            state["pack_data"],
            deterministic=True,
        )
        f04 = next(c for c in report.checks if c.id == "F04")
        assert not f04.passed
        assert "missing from the selection" in f04.details

    def test_pack_version_mismatch_blocks_gate(self, state, selection):
        # P1: a selection confirmed against one version must not consume
        # another version's data.
        stale = state["style_selection"].model_copy(update={"style_pack_version": "0.0.9"})
        gate = facade_generation_gate(
            state["plot"],
            state["concept"],
            selection,
            state["match"],
            stale,
            state["pack_ref"],
            state["pack_data"],
        )
        assert not gate.passed
        assert any("re-confirmation required" in r for r in gate.reasons)

    def test_pack_data_reference_mismatch_blocks_gate(self, state, selection):
        core = state["pack_data"].core.model_copy(update={"version": "0.2.0"})
        drifted = state["pack_data"].model_copy(update={"core": core})
        gate = facade_generation_gate(
            state["plot"],
            state["concept"],
            selection,
            state["match"],
            state["style_selection"],
            state["pack_ref"],
            drifted,
        )
        assert not gate.passed
        assert any("does not match the confirmed pack reference" in r for r in gate.reasons)

    def test_selection_for_other_concept_blocks_gate(self, state, selection):
        # Regression (Codex stop-gate): a confirmed selection must be bound to
        # the concept being generated, not replayable against another one.
        foreign = selection.model_copy(update={"concept_id": "compact_3br-v1-o180-m1-s1x1"})
        gate = facade_generation_gate(
            state["plot"],
            state["concept"],
            foreign,
            state["match"],
            state["style_selection"],
            state["pack_ref"],
            state["pack_data"],
        )
        assert not gate.passed
        assert any("re-selection required" in r for r in gate.reasons)

    def test_selection_for_other_plot_blocks_gate(self, state, selection):
        foreign = selection.model_copy(update={"project_id": "plot-20x30-street3"})
        gate = facade_generation_gate(
            state["plot"],
            state["concept"],
            foreign,
            state["match"],
            state["style_selection"],
            state["pack_ref"],
            state["pack_data"],
        )
        assert not gate.passed
        assert any("confirmed for project 'plot-20x30-street3'" in r for r in gate.reasons)

    def test_same_id_different_plot_blocks_gate(self, state, selection):
        # Regression (Codex stop-gate round 2): two plots can share plot_id
        # (same dims + street index); the content fingerprint must catch the
        # substitution.
        from saudi_plot_design.plot.geometry import build_plot_model
        from tests.conftest import REFERENCE_CORNERS, standard_edges

        other_plot, _ = build_plot_model(
            REFERENCE_CORNERS, standard_edges(), 20.0, location=(24.65, 46.71)
        )  # street width differs -> same plot_id, different content
        assert other_plot.plot_id == state["plot"].plot_id
        assert other_plot.fingerprint != state["plot"].fingerprint
        gate = facade_generation_gate(
            other_plot,
            state["concept"],
            selection,
            state["match"],
            state["style_selection"],
            state["pack_ref"],
            state["pack_data"],
        )
        assert not gate.passed
        assert any("content fingerprint mismatch" in r for r in gate.reasons)

    def test_same_id_different_concept_blocks_gate(self, state, selection):
        # A concept from a skewed plot shares the concept_id but differs in
        # geometry - the fingerprint must catch it.
        from saudi_plot_design.planner.compact_3br import plan_compact_3br
        from saudi_plot_design.plot.geometry import build_plot_model
        from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
        from tests.conftest import standard_edges

        skewed_corners = ((0.0, 0.0), (20.0, 0.02), (20.0, 30.02), (0.0, 30.0))
        skewed_plot, _ = build_plot_model(skewed_corners, standard_edges(), 15.0)
        envelope = compute_envelope(skewed_plot, load_default_setback_rules())
        other_concept = plan_compact_3br(skewed_plot, envelope)
        assert other_concept.concept_id == state["concept"].concept_id
        assert other_concept.fingerprint != state["concept"].fingerprint
        gate = facade_generation_gate(
            state["plot"],
            other_concept,
            selection,
            state["match"],
            state["style_selection"],
            state["pack_ref"],
            state["pack_data"],
        )
        assert not gate.passed
        assert any("different concept with the same id" in r for r in gate.reasons)

    def test_versionless_confirmed_selection_blocks_gate(self, state, selection):
        # Regression (Codex M4 verification P1): a confirmed selection with no
        # recorded pack version cannot be bound to the loaded pack.
        legacy = state["style_selection"].model_copy(update={"style_pack_version": None})
        gate = facade_generation_gate(
            state["plot"],
            state["concept"],
            selection,
            state["match"],
            legacy,
            state["pack_ref"],
            state["pack_data"],
        )
        assert not gate.passed
        assert any("records no pack version" in r for r in gate.reasons)

    def test_coordinated_transform_shift_fails_validation(self, state, selection, facade):
        # Regression (Codex M4 verification P2): shifting the stored origin
        # AND all openings consistently must still fail - the validator uses
        # an independently recomputed transform.
        from saudi_plot_design.elevation.validation import validate_facade

        shift = 0.05
        origin = facade.facade_wall.local_origin_world_xy
        x_dir = facade.facade_wall.x_axis_world_dir
        shifted_wall = facade.facade_wall.model_copy(
            update={
                "local_origin_world_xy": (
                    origin[0] - shift * x_dir[0],
                    origin[1] - shift * x_dir[1],
                )
            }
        )
        shifted_openings = tuple(
            o.model_copy(update={"x_start_m": o.x_start_m + shift}) for o in facade.facade_openings
        )
        broken = facade.model_copy(
            update={"facade_wall": shifted_wall, "facade_openings": shifted_openings}
        )
        report = validate_facade(
            broken,
            state["plot"],
            state["concept"],
            selection,
            state["pack_data"],
            deterministic=True,
        )
        failed_ids = {c.id for c in report.failures()}
        assert {"F06", "F07"} & failed_ids

    def test_corrupted_stored_transform_fails_f05(self, state, selection, facade):
        # Regression (Codex M4 verification round 2, P2): corrupted transform
        # metadata with untouched opening coordinates must still fail.
        from saudi_plot_design.elevation.validation import validate_facade

        origin = facade.facade_wall.local_origin_world_xy
        corrupted_wall = facade.facade_wall.model_copy(
            update={"local_origin_world_xy": (origin[0] + 0.5, origin[1])}
        )
        broken = facade.model_copy(update={"facade_wall": corrupted_wall})
        report = validate_facade(
            broken,
            state["plot"],
            state["concept"],
            selection,
            state["pack_data"],
            deterministic=True,
        )
        f05 = next(c for c in report.checks if c.id == "F05")
        assert not f05.passed
        assert "stored facade origin" in f05.details

    def test_nan_transform_component_fails_f05(self, state, selection, facade):
        # Regression (Codex M4 verification round 3, P2): NaN defeats plain
        # tolerance comparisons and must be rejected explicitly.
        from saudi_plot_design.elevation.validation import validate_facade

        corrupted_wall = facade.facade_wall.model_copy(
            update={"local_origin_world_xy": (float("nan"), 3.0)}
        )
        broken = facade.model_copy(update={"facade_wall": corrupted_wall})
        report = validate_facade(
            broken,
            state["plot"],
            state["concept"],
            selection,
            state["pack_data"],
            deterministic=True,
        )
        assert not next(c for c in report.checks if c.id == "F05").passed

    def test_corrupted_outward_normal_fails_f05(self, state, selection, facade):
        # Regression (Codex M4 verification round 3, P2): the stored outward
        # normal is validated too, not just origin and x-axis.
        from saudi_plot_design.elevation.validation import validate_facade

        corrupted_wall = facade.facade_wall.model_copy(
            update={"outward_normal_world_dir": (0.0, 1.0)}  # points away from street
        )
        broken = facade.model_copy(update={"facade_wall": corrupted_wall})
        report = validate_facade(
            broken,
            state["plot"],
            state["concept"],
            selection,
            state["pack_data"],
            deterministic=True,
        )
        f05 = next(c for c in report.checks if c.id == "F05")
        assert not f05.passed
        assert "outward normal" in f05.details

    def test_moved_opening_fails_f06_f07(self, state, selection, facade):
        # P2: a projection regression that shifts an opening must be caught.
        from saudi_plot_design.elevation.validation import validate_facade

        moved = tuple(
            o.model_copy(update={"x_start_m": o.x_start_m + 0.05}) if o.id == "F-w_majlis_2" else o
            for o in facade.facade_openings
        )
        broken = facade.model_copy(update={"facade_openings": moved})
        report = validate_facade(
            broken,
            state["plot"],
            state["concept"],
            selection,
            state["pack_data"],
            deterministic=True,
        )
        f07 = next(c for c in report.checks if c.id == "F07")
        assert not f07.passed
        assert "moved from its true plan position" in f07.details

    def test_deficient_pack_is_structured_rejection(self, state, selection):
        # P2: a same-id pack missing template prerequisites must reject
        # cleanly, never crash with IndexError/AssertionError.
        materials = state["pack_data"].materials.model_copy(
            update={"material_palette": state["pack_data"].materials.material_palette[:1]}
        )
        deficient = state["pack_data"].model_copy(update={"materials": materials})
        facade = generate(state, selection, pack_data=deficient)
        assert not facade.is_valid
        assert any("lacks template material" in r for r in facade.rejection_reasons)

    def test_empty_rule_list_is_structured_rejection(self, state, selection):
        rules = state["pack_data"].facade_rules.model_copy(update={"shading_element_ids": ()})
        deficient = state["pack_data"].model_copy(update={"facade_rules": rules})
        facade = generate(state, selection, pack_data=deficient)
        assert not facade.is_valid
        assert any("declares no shading_element_ids" in r for r in facade.rejection_reasons)


class TestTransforms:
    def test_mirrored_plan_deterministic_order(self, state):
        from saudi_plot_design.planner.compact_3br import plan_compact_3br
        from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules

        envelope = compute_envelope(state["plot"], load_default_setback_rules())
        mirrored = plan_compact_3br(state["plot"], envelope, mirrored=True)
        selection = select_primary_facade(state["plot"], mirrored, 0, user_confirmed=True)
        facade = generate(state, selection, concept=mirrored)
        assert facade.is_valid
        xs = [o.x_start_m for o in facade.facade_openings]
        assert xs == sorted(xs)
        # Mirrored: the kitchen window moves to the low-x side of the facade.
        kitchen = next(o for o in facade.facade_openings if o.source_plan_opening_id == "w_kitchen")
        assert kitchen.x_start_m < facade.facade_wall.length_m / 2

    def test_rotated_plan_generates_correct_wall(self):
        rotated = reference_pipeline(
            edges=(EdgeClass.NEIGHBOR, EdgeClass.NEIGHBOR, EdgeClass.STREET, EdgeClass.NEIGHBOR)
        )
        selection = select_primary_facade(
            rotated["plot"], rotated["concept"], 2, user_confirmed=True
        )
        facade = generate_front_facade(
            rotated["plot"],
            rotated["concept"],
            selection,
            rotated["match"],
            rotated["style_selection"],
            rotated["pack_ref"],
            rotated["pack_data"],
        )
        assert facade.is_valid
        # As seen from the north street, facade X runs east->west.
        assert facade.facade_wall.x_axis_world_dir == (-1.0, 0.0)
        assert facade.facade_wall.outward_normal_world_dir == (0.0, 1.0)
        assert {o.source_plan_opening_id for o in facade.facade_openings} == {
            "d_main",
            "d_majlis_ext",
            "w_majlis_1",
            "w_majlis_2",
            "w_kitchen",
        }
