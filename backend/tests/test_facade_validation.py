"""Tests for the fixed 24-check facade validator (M4) via targeted mutations."""

import pytest

from saudi_plot_design.elevation.facade_selection import select_primary_facade
from saudi_plot_design.elevation.front import generate_front_facade
from saudi_plot_design.elevation.validation import validate_facade
from tests.conftest import reference_pipeline


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


def check(state, selection, facade, check_id, *, deterministic=True):
    report = validate_facade(
        facade,
        state["plot"],
        state["concept"],
        selection,
        state["pack_data"],
        deterministic=deterministic,
    )
    return next(c for c in report.checks if c.id == check_id)


def mutate_opening(facade, opening_id, **updates):
    openings = tuple(
        o.model_copy(update=updates) if o.id == opening_id else o for o in facade.facade_openings
    )
    return facade.model_copy(update={"facade_openings": openings})


class TestChecks:
    def test_unconfirmed_style_fails_f01(self, state, selection, facade):
        broken = facade.model_copy(update={"style_selection_method": "automatic_recommendation"})
        assert not check(state, selection, broken, "F01").passed

    def test_unconfirmed_facade_fails_f02(self, state, selection, facade):
        unconfirmed = selection.model_copy(update={"user_confirmed": False})
        report = validate_facade(
            facade,
            state["plot"],
            state["concept"],
            unconfirmed,
            state["pack_data"],
            deterministic=True,
        )
        assert not next(c for c in report.checks if c.id == "F02").passed

    def test_non_street_boundary_fails_f03(self, state, selection, facade):
        wrong = selection.model_copy(update={"selected_plot_boundary_id": "plot-edge-2"})
        report = validate_facade(
            facade,
            state["plot"],
            state["concept"],
            wrong,
            state["pack_data"],
            deterministic=True,
        )
        assert not next(c for c in report.checks if c.id == "F03").passed

    def test_wrong_wall_fails_f04(self, state, selection, facade):
        # Swap in a side wall (external but facing east, not the street).
        side_wall = next(
            w for w in state["concept"].walls if w.is_external and w.start[0] == w.end[0]
        )
        wrong = selection.model_copy(
            update={
                "selected_building_wall_ids": selection.selected_building_wall_ids[:-1]
                + (side_wall.id,)
            }
        )
        report = validate_facade(
            facade,
            state["plot"],
            state["concept"],
            wrong,
            state["pack_data"],
            deterministic=True,
        )
        assert not next(c for c in report.checks if c.id == "F04").passed

    def test_length_mismatch_fails_f05(self, state, selection, facade):
        wall = facade.facade_wall.model_copy(update={"length_m": 10.0})
        broken = facade.model_copy(update={"facade_wall": wall})
        assert not check(state, selection, broken, "F05").passed

    def test_fake_door_fails_f06(self, state, selection, facade):
        broken = mutate_opening(facade, "F-d_main", source_plan_opening_id="d_ghost")
        assert not check(state, selection, broken, "F06").passed
        assert not check(state, selection, broken, "F22").passed

    def test_removed_plan_door_fails_f06(self, state, selection, facade):
        openings = tuple(o for o in facade.facade_openings if o.id != "F-d_majlis_ext")
        broken = facade.model_copy(update={"facade_openings": openings})
        result = check(state, selection, broken, "F06")
        assert not result.passed
        assert "removed" in result.details

    def test_fake_window_fails_f07(self, state, selection, facade):
        broken = mutate_opening(facade, "F-w_kitchen", source_plan_opening_id="w_ghost")
        assert not check(state, selection, broken, "F07").passed

    def test_opening_on_other_wall_fails_f08(self, state, selection, facade):
        other_wall = next(w.id for w in state["concept"].walls if not w.is_external)
        broken = mutate_opening(facade, "F-w_kitchen", source_plan_wall_id=other_wall)
        assert not check(state, selection, broken, "F08").passed

    def test_opening_outside_extent_fails_f09(self, state, selection, facade):
        broken = mutate_opening(facade, "F-w_kitchen", x_start_m=13.0)
        assert not check(state, selection, broken, "F09").passed

    def test_non_positive_dims_fail_f10(self, state, selection, facade):
        broken = mutate_opening(facade, "F-w_kitchen", width_m=0.0)
        assert not check(state, selection, broken, "F10").passed

    def test_overlap_fails_f11(self, state, selection, facade):
        broken = mutate_opening(facade, "F-w_majlis_2", x_start_m=0.9)
        assert not check(state, selection, broken, "F11").passed

    def test_edge_clearance_fails_f12(self, state, selection, facade):
        broken = mutate_opening(facade, "F-w_majlis_1", x_start_m=0.05)
        assert not check(state, selection, broken, "F12").passed

    def test_spacing_fails_f13(self, state, selection, facade):
        broken = mutate_opening(facade, "F-w_majlis_2", x_start_m=1.85)
        assert not check(state, selection, broken, "F13").passed

    def test_bad_sill_head_fails_f14(self, state, selection, facade):
        broken = mutate_opening(facade, "F-w_kitchen", sill_elevation_m=1.5)
        assert not check(state, selection, broken, "F14").passed

    def test_head_at_wall_limit_fails_f15(self, state, selection, facade):
        broken = mutate_opening(facade, "F-w_kitchen", sill_elevation_m=1.0, head_elevation_m=3.6)
        assert not check(state, selection, broken, "F15").passed

    def test_missing_entrance_frame_fails_f16(self, state, selection, facade):
        elements = tuple(e for e in facade.facade_elements if e.host_opening_id != "F-d_main")
        broken = facade.model_copy(update={"facade_elements": elements})
        assert not check(state, selection, broken, "F16").passed

    def test_element_outside_zone_fails_f17(self, state, selection, facade):
        band = next(e for e in facade.facade_elements if e.element_type == "decorative_band")
        moved = band.model_copy(update={"geometry": {**band.geometry, "z": 4.5}})
        elements = tuple(moved if e.id == band.id else e for e in facade.facade_elements)
        broken = facade.model_copy(update={"facade_elements": elements})
        assert not check(state, selection, broken, "F17").passed

    def test_decor_covering_opening_fails_f18(self, state, selection, facade):
        band = next(e for e in facade.facade_elements if e.element_type == "decorative_band")
        moved = band.model_copy(update={"geometry": {**band.geometry, "z": 1.5}})
        elements = tuple(moved if e.id == band.id else e for e in facade.facade_elements)
        broken = facade.model_copy(update={"facade_elements": elements})
        assert not check(state, selection, broken, "F18").passed

    def test_zero_size_element_fails_f19(self, state, selection, facade):
        frame = next(e for e in facade.facade_elements if e.element_type == "window_frame")
        squashed = frame.model_copy(update={"geometry": {**frame.geometry, "h": 0.0}})
        elements = tuple(squashed if e.id == frame.id else e for e in facade.facade_elements)
        broken = facade.model_copy(update={"facade_elements": elements})
        assert not check(state, selection, broken, "F19").passed

    def test_plinth_outside_pack_range_fails_f20(self, state, selection, facade):
        wall = facade.facade_wall.model_copy(update={"plinth_height_m": 1.5})
        broken = facade.model_copy(update={"facade_wall": wall})
        assert not check(state, selection, broken, "F20").passed

    def test_unknown_material_fails_f21(self, state, selection, facade):
        body = next(e for e in facade.facade_elements if e.element_type == "wall_body")
        alien = body.model_copy(update={"material_id": "granite_imported"})
        elements = tuple(alien if e.id == body.id else e for e in facade.facade_elements)
        broken = facade.model_copy(update={"facade_elements": elements})
        assert not check(state, selection, broken, "F21").passed

    def test_unknown_color_fails_f21(self, state, selection, facade):
        body = next(e for e in facade.facade_elements if e.element_type == "wall_body")
        alien = body.model_copy(update={"color_hex": "#123456"})
        elements = tuple(alien if e.id == body.id else e for e in facade.facade_elements)
        broken = facade.model_copy(update={"facade_elements": elements})
        assert not check(state, selection, broken, "F21").passed

    def test_duplicated_source_fails_f22(self, state, selection, facade):
        clone = facade.facade_openings[0].model_copy(update={"id": "F-clone", "x_start_m": 8.0})
        broken = facade.model_copy(update={"facade_openings": facade.facade_openings + (clone,)})
        assert not check(state, selection, broken, "F22").passed

    def test_missing_disclaimer_fails_f23(self, state, selection, facade):
        broken = facade.model_copy(update={"disclaimer": ""})
        assert not check(state, selection, broken, "F23").passed

    def test_non_deterministic_fails_f24(self, state, selection, facade):
        assert not check(state, selection, facade, "F24", deterministic=False).passed

    def test_all_check_ids_fixed(self, state, selection, facade):
        report = validate_facade(
            facade,
            state["plot"],
            state["concept"],
            selection,
            state["pack_data"],
            deterministic=True,
        )
        assert [c.id for c in report.checks] == [f"F{i:02d}" for i in range(1, 25)]
