"""Tests for the fixed 15-check livability validator (M2)."""

import pytest

from saudi_plot_design.model import Door, Rect, Room, Window, Zone
from saudi_plot_design.planner.compact_3br import plan_compact_3br
from saudi_plot_design.planner.validation import validate_concept
from saudi_plot_design.plot.geometry import build_plot_model
from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
from tests.conftest import REFERENCE_CORNERS, standard_edges


@pytest.fixture(scope="module")
def concept():
    model, _ = build_plot_model(REFERENCE_CORNERS, standard_edges(), 15.0)
    envelope = compute_envelope(model, load_default_setback_rules())
    return plan_compact_3br(model, envelope)


def replace_room(concept, room_id, **updates):
    rooms = tuple(r.model_copy(update=updates) if r.id == room_id else r for r in concept.rooms)
    return concept.model_copy(update={"rooms": rooms})


def check_by_id(report, check_id):
    return next(c for c in report.checks if c.id == check_id)


class TestChecklist:
    def test_reference_concept_passes_all_15(self, concept):
        report = validate_concept(concept)
        assert len(report.checks) == 15
        assert report.passed
        assert [c.id for c in report.checks] == [f"C{i:02d}" for i in range(1, 16)]

    def test_room_outside_footprint_fails_c01(self, concept):
        moved = replace_room(
            concept, "majlis", rect=Rect(min_x=0.0, min_y=0.0, max_x=5.7, max_y=4.5)
        )
        report = validate_concept(moved)
        assert not check_by_id(report, "C01").passed

    def test_overlapping_rooms_fail_c02(self, concept):
        majlis = next(r for r in concept.rooms if r.id == "majlis")
        grown = Rect(
            min_x=majlis.rect.min_x,
            min_y=majlis.rect.min_y,
            max_x=majlis.rect.max_x + 2.0,
            max_y=majlis.rect.max_y,
        )
        report = validate_concept(replace_room(concept, "majlis", rect=grown))
        assert not check_by_id(report, "C02").passed

    def test_undersized_room_fails_c03(self, concept):
        report = validate_concept(replace_room(concept, "bedroom_2", area_m2=6.0))
        assert not check_by_id(report, "C03").passed

    def test_too_narrow_room_fails_c04(self, concept):
        report = validate_concept(replace_room(concept, "bedroom_2", width_m=1.0))
        assert not check_by_id(report, "C04").passed

    def test_zero_length_wall_fails_c05(self, concept):
        wall = concept.walls[0].model_copy(update={"end": concept.walls[0].start})
        broken = concept.model_copy(update={"walls": (wall,) + concept.walls[1:]})
        assert not check_by_id(validate_concept(broken), "C05").passed

    def test_door_on_wrong_wall_fails_c06(self, concept):
        internal_walls = [w for w in concept.walls if not w.is_external]
        door = concept.doors[0]
        wrong = next(
            w for w in internal_walls if set(w.room_ids) != {door.from_space, door.to_space}
        )
        rewired = door.model_copy(update={"wall_id": wrong.id})
        broken = concept.model_copy(update={"doors": (rewired,) + concept.doors[1:]})
        assert not check_by_id(validate_concept(broken), "C06").passed

    def test_door_without_clearance_fails_c07(self, concept):
        door = concept.doors[0].model_copy(update={"position_m": 0.0})
        broken = concept.model_copy(update={"doors": (door,) + concept.doors[1:]})
        assert not check_by_id(validate_concept(broken), "C07").passed

    def test_bedroom_without_external_wall_fails_c08(self, concept):
        walls = tuple(
            w.model_copy(update={"is_external": False})
            if "bedroom_2" in w.room_ids and w.is_external
            else w
            for w in concept.walls
        )
        broken = concept.model_copy(update={"walls": walls})
        assert not check_by_id(validate_concept(broken), "C08").passed

    def test_bedroom_without_window_fails_c09(self, concept):
        windows = tuple(w for w in concept.windows if w.room_id != "bedroom_2")
        broken = concept.model_copy(update={"windows": windows})
        assert not check_by_id(validate_concept(broken), "C09").passed

    def test_room_only_via_bedroom_fails_c10(self, concept):
        # Rewire the shared bathroom door: corridor -> bedroom_2 access only.
        doors = tuple(
            d.model_copy(update={"from_space": "bedroom_2"}) if d.id == "d_shared_bath" else d
            for d in concept.doors
        )
        broken = concept.model_copy(update={"doors": doors})
        assert not check_by_id(validate_concept(broken), "C10").passed

    def test_ensuite_without_bedroom_door_fails_c10(self, concept):
        doors = tuple(d for d in concept.doors if d.id != "d_master_bath")
        broken = concept.model_copy(update={"doors": doors})
        assert not check_by_id(validate_concept(broken), "C10").passed

    def test_wet_room_without_plumbing_partner_fails_c11(self, concept):
        walls = tuple(w for w in concept.walls if set(w.room_ids) != {"guest_wc", "kitchen"})
        broken = concept.model_copy(update={"walls": walls})
        assert not check_by_id(validate_concept(broken), "C11").passed

    def test_missing_main_entrance_fails_c12(self, concept):
        doors = tuple(d for d in concept.doors if d.entrance_type != "main")
        broken = concept.model_copy(update={"doors": doors})
        assert not check_by_id(validate_concept(broken), "C12").passed

    def test_majlis_only_via_living_fails_c13(self, concept):
        # Remove the majlis street entrance and its entry-hall door, rewire the
        # majlis through the family living room instead.
        doors = tuple(d for d in concept.doors if d.id not in ("d_majlis_ext", "d_majlis_entry"))
        living_door = Door(
            id="d_majlis_living",
            wall_id=concept.doors[0].wall_id,
            from_space="family_living",
            to_space="majlis",
            position_m=0.5,
            width_m=0.9,
        )
        majlis_doors = tuple(d.model_copy() for d in doors) + (
            living_door,
            Door(
                id="d_majlis_ext2",
                wall_id=concept.doors[0].wall_id,
                from_space="exterior",
                to_space="majlis",
                position_m=0.5,
                width_m=1.0,
                entrance_type="majlis",
            ),
        )
        # Entrance exists but the only interior connection is via the living room:
        # C13 still passes because the street door reaches the majlis directly.
        broken = concept.model_copy(update={"doors": majlis_doors})
        assert check_by_id(validate_concept(broken), "C13").passed
        # Without any majlis entrance, C13 fails.
        no_entrance = concept.model_copy(
            update={"doors": tuple(d for d in concept.doors if d.entrance_type != "majlis")}
        )
        assert not check_by_id(validate_concept(no_entrance), "C13").passed

    def test_main_tag_on_internal_door_fails_c12(self, concept):
        # Regression (Codex M2 P2): the tagged door itself must reach exterior.
        doors = tuple(
            d.model_copy(update={"entrance_type": "main" if d.id == "d_majlis_entry" else None})
            if d.id in ("d_main", "d_majlis_entry")
            else d
            for d in concept.doors
        )
        broken = concept.model_copy(update={"doors": doors})
        assert not check_by_id(validate_concept(broken), "C12").passed

    def test_majlis_tag_on_internal_door_fails_c13(self, concept):
        # Regression (Codex M2 P2): the tagged majlis door must itself be the
        # street entrance, not merely leave the majlis globally reachable.
        doors = tuple(
            d.model_copy(update={"entrance_type": "majlis"})
            if d.id == "d_majlis_entry"
            else (d.model_copy(update={"entrance_type": None}) if d.id == "d_majlis_ext" else d)
            for d in concept.doors
        )
        broken = concept.model_copy(update={"doors": doors})
        assert not check_by_id(validate_concept(broken), "C13").passed

    def test_overlapping_openings_fail_c14(self, concept):
        window = concept.windows[0]
        clone = window.model_copy(update={"id": "w_clone"})
        broken = concept.model_copy(update={"windows": concept.windows + (clone,)})
        assert not check_by_id(validate_concept(broken), "C14").passed

    def test_opening_outside_wall_fails_c15(self, concept):
        window = concept.windows[0].model_copy(update={"position_m": 500.0})
        broken = concept.model_copy(update={"windows": (window,) + concept.windows[1:]})
        assert not check_by_id(validate_concept(broken), "C15").passed


class TestGraphHelpers:
    def test_maid_room_reachable_without_bedrooms(self, concept):
        report = validate_concept(concept)
        assert check_by_id(report, "C10").passed

    def test_master_bath_is_authored_ensuite(self, concept):
        room = next(r for r in concept.rooms if r.id == "master_bath")
        assert room.access_via_room == "master_bedroom"
        assert room.zone is Zone.PRIVATE


def test_window_model_has_nominal_heights(concept):
    for window in concept.windows:
        assert isinstance(window, Window)
        assert 0 < window.sill_height_m < window.head_height_m


def test_room_models_expose_dimensions(concept):
    for room in concept.rooms:
        assert isinstance(room, Room)
        assert room.area_m2 == pytest.approx(room.width_m * room.length_m, rel=1e-6)
