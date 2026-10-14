"""Tests for the Compact 3BR planner: generation, transforms, rejection (M2)."""

import pytest

from saudi_plot_design.model import EXTERIOR, BuildableEnvelope, EdgeClass
from saudi_plot_design.planner import skeleton as sk
from saudi_plot_design.planner.compact_3br import plan_compact_3br
from saudi_plot_design.plot.geometry import build_plot_model
from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
from tests.conftest import REFERENCE_CORNERS, standard_edges


@pytest.fixture(scope="module")
def reference_setup():
    model, _ = build_plot_model(REFERENCE_CORNERS, standard_edges(), 15.0, location=(24.65, 46.71))
    envelope = compute_envelope(model, load_default_setback_rules())
    return model, envelope


@pytest.fixture(scope="module")
def concept(reference_setup):
    model, envelope = reference_setup
    return plan_compact_3br(model, envelope)


def small_envelope(width, depth):
    return BuildableEnvelope(
        corners=((0.0, 0.0), (width, 0.0), (width, depth), (0.0, depth)),
        area_m2=width * depth,
        width_m=width,
        depth_m=depth,
    )


class TestReferenceGeneration:
    def test_concept_is_valid(self, concept):
        assert concept.is_valid
        assert concept.rejection_reasons == ()
        assert concept.validation is not None and concept.validation.passed

    def test_required_rooms_exist_exactly_once(self, concept):
        ids = [r.id for r in concept.rooms]
        assert sorted(ids) == sorted(sk.REQUIRED_ROOM_IDS)
        assert len(ids) == len(set(ids)) == 14

    def test_rooms_inside_footprint(self, concept):
        for room in concept.rooms:
            assert concept.footprint.contains(room.rect), room.id

    def test_no_room_overlap(self, concept):
        rooms = concept.rooms
        for i, a in enumerate(rooms):
            for b in rooms[i + 1 :]:
                assert a.rect.overlap_area(b.rect) == pytest.approx(0.0, abs=1e-9)

    def test_total_room_area_equals_footprint(self, concept):
        # The authored tiling covers the footprint exactly: overlap-free rooms
        # summing to the footprint area means no gaps either.
        assert concept.total_room_area_m2 == pytest.approx(concept.footprint.area, abs=1e-6)
        assert concept.total_room_area_m2 == pytest.approx(214.65)

    def test_known_room_areas(self, concept):
        areas = {r.id: r.area_m2 for r in concept.rooms}
        assert areas["majlis"] == pytest.approx(25.65)
        assert areas["master_bedroom"] == pytest.approx(25.65)
        assert areas["bedroom_2"] == pytest.approx(21.6)
        assert areas["bedroom_3"] == pytest.approx(21.6)
        assert areas["guest_wc"] == pytest.approx(4.86)

    def test_wall_connectivity(self, concept):
        rooms = {r.id for r in concept.rooms}
        for wall in concept.walls:
            assert 1 <= len(wall.room_ids) <= 2
            assert set(wall.room_ids) <= rooms
            if len(wall.room_ids) == 2:
                assert not wall.is_external
            else:
                assert wall.is_external

    def test_shared_walls_deduplicated(self, concept):
        # Exactly one internal wall exists per adjacent room pair per line.
        seen = set()
        for wall in concept.walls:
            if wall.is_external:
                continue
            axis = "v" if wall.start[0] == wall.end[0] else "h"
            level = wall.start[0] if axis == "v" else wall.start[1]
            key = (frozenset(wall.room_ids), axis, round(level, 6))
            assert key not in seen, f"duplicate shared wall {key}"
            seen.add(key)

    def test_doors_hosted_on_walls(self, concept):
        walls = {w.id: w for w in concept.walls}
        for door in concept.doors:
            wall = walls[door.wall_id]
            spaces = {door.from_space, door.to_space}
            if EXTERIOR in spaces:
                assert wall.is_external
                assert (spaces - {EXTERIOR}) == set(wall.room_ids)
            else:
                assert spaces == set(wall.room_ids)

    def test_windows_hosted_on_external_walls(self, concept):
        walls = {w.id: w for w in concept.walls}
        for window in concept.windows:
            wall = walls[window.wall_id]
            assert wall.is_external
            assert window.room_id in wall.room_ids

    def test_openings_inside_wall_bounds(self, concept):
        walls = {w.id: w for w in concept.walls}
        for opening in list(concept.doors) + list(concept.windows):
            wall = walls[opening.wall_id]
            assert opening.position_m >= 0
            assert opening.position_m + opening.width_m <= wall.length_m + 1e-6

    def test_bedrooms_have_external_wall_and_window(self, concept):
        walls_by_room = {}
        for wall in concept.walls:
            for rid in wall.room_ids:
                walls_by_room.setdefault(rid, []).append(wall)
        for rid in ("master_bedroom", "bedroom_2", "bedroom_3"):
            assert any(w.is_external for w in walls_by_room[rid]), rid
            assert any(w.room_id == rid for w in concept.windows), rid

    def test_main_entrance_present(self, concept):
        main = [d for d in concept.doors if d.entrance_type == "main"]
        assert len(main) == 1
        assert EXTERIOR in (main[0].from_space, main[0].to_space)

    def test_majlis_entrance_present_and_separate(self, concept):
        majlis = [d for d in concept.doors if d.entrance_type == "majlis"]
        assert len(majlis) == 1
        assert {majlis[0].from_space, majlis[0].to_space} == {EXTERIOR, "majlis"}


class TestTransforms:
    def test_mirrored_variant_valid(self, reference_setup):
        model, envelope = reference_setup
        concept = plan_compact_3br(model, envelope, mirrored=True)
        assert concept.is_valid
        assert concept.mirrored is True

    def test_rotated_variant_valid(self):
        edges = (EdgeClass.NEIGHBOR, EdgeClass.NEIGHBOR, EdgeClass.STREET, EdgeClass.NEIGHBOR)
        model, _ = build_plot_model(REFERENCE_CORNERS, edges, 15.0)
        envelope = compute_envelope(model, load_default_setback_rules())
        concept = plan_compact_3br(model, envelope)
        assert concept.orientation_deg == 180
        assert concept.is_valid
        # Front of the footprint sits on the envelope edge nearest the street.
        assert concept.footprint.max_y == pytest.approx(27.0)

    def test_mirroring_moves_rooms(self, reference_setup, concept):
        model, envelope = reference_setup
        mirrored = plan_compact_3br(model, envelope, mirrored=True)
        base_majlis = next(r for r in concept.rooms if r.id == "majlis")
        mirrored_majlis = next(r for r in mirrored.rooms if r.id == "majlis")
        assert base_majlis.rect != mirrored_majlis.rect
        assert base_majlis.area_m2 == pytest.approx(mirrored_majlis.area_m2)

    def test_scaled_variant_within_limits_valid(self, reference_setup):
        model, envelope = reference_setup
        concept = plan_compact_3br(model, envelope, scale_x=1.1, scale_y=1.05)
        assert concept.is_valid
        assert concept.footprint.width == pytest.approx(13.5 * 1.1)


class TestRejection:
    def test_scale_outside_limits_rejected(self, reference_setup):
        model, envelope = reference_setup
        concept = plan_compact_3br(model, envelope, scale_x=1.5)
        assert not concept.is_valid
        assert any("scale_x" in r for r in concept.rejection_reasons)
        assert concept.rooms == ()

    def test_footprint_too_small_envelope(self, reference_setup):
        model, _ = reference_setup
        concept = plan_compact_3br(model, small_envelope(10.0, 12.0))
        assert not concept.is_valid
        reasons = " | ".join(concept.rejection_reasons)
        assert "exceeds buildable envelope width" in reasons
        assert "exceeds buildable envelope depth" in reasons

    def test_excessively_narrow_envelope(self, reference_setup):
        model, _ = reference_setup
        concept = plan_compact_3br(model, small_envelope(8.0, 30.0))
        assert not concept.is_valid
        assert any("width" in r for r in concept.rejection_reasons)

    def test_rejection_is_structured_not_exception(self, reference_setup):
        model, _ = reference_setup
        concept = plan_compact_3br(model, small_envelope(5.0, 5.0))
        assert concept.footprint is None
        assert concept.validation is None
        assert concept.rejection_reasons
        assert concept.assumptions  # honesty metadata still present


class TestReviewRegressions:
    """Regression tests for Codex M2 review findings."""

    @staticmethod
    def rotated_envelope(envelope, degrees):
        import math

        angle = math.radians(degrees)
        cx, cy = 10.0, 15.5
        corners = tuple(
            (
                cx + (x - cx) * math.cos(angle) - (y - cy) * math.sin(angle),
                cy + (x - cx) * math.sin(angle) + (y - cy) * math.cos(angle),
            )
            for x, y in envelope.corners
        )
        return BuildableEnvelope(
            corners=corners,
            area_m2=envelope.area_m2,
            width_m=envelope.width_m,
            depth_m=envelope.depth_m,
        )

    def test_sloped_front_envelope_translates_footprint_inward(self, reference_setup):
        # P1 (round 2): a front edge sloping 0.02 m (within M1 tolerances)
        # must not reject - the footprint translates a few centimeters inward.
        from shapely.geometry import Polygon, box

        model, envelope = reference_setup
        sloped = BuildableEnvelope(
            corners=((2.0, 3.0), (18.0, 3.02), (18.0, 28.0), (2.0, 28.0)),
            area_m2=envelope.area_m2,
            width_m=envelope.width_m,
            depth_m=envelope.depth_m,
        )
        concept = plan_compact_3br(model, sloped)
        assert concept.is_valid
        fp = concept.footprint
        assert (
            Polygon(sloped.corners).buffer(1e-6).covers(box(fp.min_x, fp.min_y, fp.max_x, fp.max_y))
        )

    def test_slightly_rotated_envelope_still_fits(self, reference_setup):
        # P1: a 5-degree rotated envelope still admits the footprint - the
        # planner places it inside the actual polygon instead of rejecting.
        from shapely.geometry import Polygon, box

        model, envelope = reference_setup
        skewed = self.rotated_envelope(envelope, 5.0)
        concept = plan_compact_3br(model, skewed)
        assert concept.is_valid
        fp = concept.footprint
        assert (
            Polygon(skewed.corners).buffer(1e-6).covers(box(fp.min_x, fp.min_y, fp.max_x, fp.max_y))
        )

    def test_heavily_rotated_envelope_rejected(self, reference_setup):
        # P1: when no axis-aligned placement exists the rejection is honest.
        model, envelope = reference_setup
        skewed = self.rotated_envelope(envelope, 12.0)
        concept = plan_compact_3br(model, skewed)
        assert not concept.is_valid
        assert any("does not fit inside" in r for r in concept.rejection_reasons)
        assert concept.footprint is None

    def test_vertical_downscaling_is_out_of_authored_limits(self, reference_setup):
        # P2: scale_y < 1.0 breaks the 1.5 m bath/laundry band minimums.
        model, envelope = reference_setup
        concept = plan_compact_3br(model, envelope, scale_y=0.95)
        assert not concept.is_valid
        assert any("scale_y" in r for r in concept.rejection_reasons)

    def test_horizontal_downscaling_within_limits_is_valid(self, reference_setup):
        # P2 (round 2): scale_x=0.95 keeps every minimum - it must stay valid.
        model, envelope = reference_setup
        concept = plan_compact_3br(model, envelope, scale_x=0.95)
        assert concept.is_valid
        assert concept.footprint.width == pytest.approx(13.5 * 0.95)

    def test_failed_validation_becomes_structured_rejection(self, reference_setup, monkeypatch):
        # P2: any failed livability check must populate rejection_reasons.
        from saudi_plot_design.model import ValidationCheck, ValidationReport
        from saudi_plot_design.planner import compact_3br as planner_module

        failing = ValidationReport(
            checks=(
                ValidationCheck(id="C99", name="forced failure", passed=False, details="forced"),
            )
        )
        monkeypatch.setattr(planner_module, "validate_concept", lambda _: failing)
        model, envelope = reference_setup
        concept = plan_compact_3br(model, envelope)
        assert not concept.is_valid
        assert concept.rejection_reasons == ("validation C99 failed: forced",)
        assert concept.rooms  # geometry retained for inspection


class TestDeterminism:
    def test_same_input_identical_output(self, reference_setup):
        model, envelope = reference_setup
        a = plan_compact_3br(model, envelope)
        b = plan_compact_3br(model, envelope)
        assert a == b
        assert a.model_dump_json() == b.model_dump_json()
