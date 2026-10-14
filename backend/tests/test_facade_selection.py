"""Tests for primary facade selection (M4)."""

import pytest

from saudi_plot_design.elevation.facade_selection import facing_walls, select_primary_facade
from saudi_plot_design.model import EdgeClass, SpdInputError
from tests.conftest import reference_pipeline


@pytest.fixture(scope="module")
def state():
    return reference_pipeline()


class TestSelection:
    def test_valid_primary_street_selection(self, state):
        selection = select_primary_facade(state["plot"], state["concept"], 0, user_confirmed=True)
        assert selection.selected_plot_boundary_id == "plot-edge-1"
        assert selection.selection_method == "geometric_facing_match"
        assert selection.user_confirmed
        # Front band rooms: majlis, entry, guest_wc, kitchen -> 4 segments.
        assert len(selection.selected_building_wall_ids) == 4
        assert selection.project_id == "plot-20x30-street1"
        assert not selection.warnings

    def test_non_street_boundary_rejected(self, state):
        with pytest.raises(SpdInputError, match="must be classified 'street'"):
            select_primary_facade(state["plot"], state["concept"], 1, user_confirmed=True)

    def test_out_of_range_boundary_rejected(self, state):
        with pytest.raises(SpdInputError, match="boundary index"):
            select_primary_facade(state["plot"], state["concept"], 7, user_confirmed=True)

    def test_no_facing_wall_yields_empty_selection_with_warning(self, state):
        # Synthetic: strip every street-facing wall from the concept - the
        # selection must be honestly empty, never fabricated. (Any rectangular
        # footprint has some wall facing each side, so this case is built
        # artificially.)
        fp = state["concept"].footprint
        walls = tuple(
            w
            for w in state["concept"].walls
            if not (w.is_external and w.start[1] == fp.min_y and w.end[1] == fp.min_y)
        )
        stripped = state["concept"].model_copy(update={"walls": walls})
        selection = select_primary_facade(state["plot"], stripped, 0, user_confirmed=True)
        assert selection.selected_building_wall_ids == ()
        assert any("no building exterior wall" in w for w in selection.warnings)

    def test_rotated_concept_rear_walls_face_near_street(self, state):
        # A concept oriented for the far street still has rear walls that
        # genuinely face the near street - geometric facing, not wall names.
        rotated = reference_pipeline(
            edges=(EdgeClass.NEIGHBOR, EdgeClass.NEIGHBOR, EdgeClass.STREET, EdgeClass.NEIGHBOR)
        )
        selection = select_primary_facade(state["plot"], rotated["concept"], 0, user_confirmed=True)
        fp = rotated["concept"].footprint
        walls = {w.id: w for w in rotated["concept"].walls}
        assert selection.selected_building_wall_ids
        for wall_id in selection.selected_building_wall_ids:
            assert walls[wall_id].start[1] == pytest.approx(fp.min_y)

    def test_rotated_plot_selects_far_walls(self):
        rotated = reference_pipeline(
            edges=(EdgeClass.NEIGHBOR, EdgeClass.NEIGHBOR, EdgeClass.STREET, EdgeClass.NEIGHBOR)
        )
        selection = select_primary_facade(
            rotated["plot"], rotated["concept"], 2, user_confirmed=True
        )
        assert selection.selected_plot_boundary_id == "plot-edge-3"
        assert len(selection.selected_building_wall_ids) == 4
        walls = {w.id: w for w in rotated["concept"].walls}
        fp = rotated["concept"].footprint
        for wall_id in selection.selected_building_wall_ids:
            wall = walls[wall_id]
            assert wall.start[1] == pytest.approx(fp.max_y)  # north face

    def test_facing_walls_ignores_side_walls(self, state):
        walls = facing_walls(state["plot"], state["concept"], 0)
        fp = state["concept"].footprint
        for wall in walls:
            assert wall.start[1] == pytest.approx(fp.min_y)
            assert wall.end[1] == pytest.approx(fp.min_y)

    def test_mirrored_concept_still_selects_four_segments(self, state):
        from saudi_plot_design.planner.compact_3br import plan_compact_3br
        from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules

        envelope = compute_envelope(state["plot"], load_default_setback_rules())
        mirrored = plan_compact_3br(state["plot"], envelope, mirrored=True)
        selection = select_primary_facade(state["plot"], mirrored, 0, user_confirmed=True)
        assert len(selection.selected_building_wall_ids) == 4
