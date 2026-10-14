"""Focused M6.3 tests for deterministic professional architectural sheets."""

from __future__ import annotations

import json
import os
from pathlib import Path

import ezdxf
import pytest
from pypdf import PdfReader

from saudi_plot_design.cli import build_parser
from saudi_plot_design.elevation.facade_selection import select_primary_facade
from saudi_plot_design.elevation.front import generate_front_facade
from saudi_plot_design.export.dxf import (
    APPID,
    PROFESSIONAL_LAYER_SPECS,
    _boxes_intersect,
    _professional_door_clearance,
)
from saudi_plot_design.export.pipeline import _publish_with_rollback, export_project
from saudi_plot_design.export.runlog import sha256_file
from saudi_plot_design.layout.engine import optimize_layout
from saudi_plot_design.layout.geometry import geometry_fingerprint
from saudi_plot_design.output import DISCLAIMER
from saudi_plot_design.quality.evaluator import evaluate_architectural_quality
from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
from saudi_plot_design.sheets.engine import (
    BBox,
    _door_clearance_boxes,
    _primitive_within_page,
    _safe_corner_box,
    build_architectural_sheets,
    door_schedule_rows,
    plan_transform,
    room_schedule_rows,
    select_scale,
    window_schedule_rows,
)
from saudi_plot_design.sheets.export import (
    COLLISION_REPORT,
    CONCEPT_PDF,
    REVIEW_PDF,
    SHEET_INDEX,
    SHEET_MANIFEST,
    export_architectural_sheets,
    verify_sheet_manifest,
)
from saudi_plot_design.sheets.graphics import render_sheet_svg
from saudi_plot_design.sheets.models import GRAPHIC_PROFILE, Primitive
from tests.conftest import reference_pipeline

FIXED_RUN = {
    "run_id": "m63-reference",
    "generation_timestamp": "2026-07-15T00:00:00Z",
}


@pytest.fixture(scope="module")
def state():
    base = reference_pipeline()
    rules = load_default_setback_rules()
    envelope = compute_envelope(base["plot"], rules)
    optimization = optimize_layout(base["concept"], envelope)
    concept = optimization.selected_concept
    selection = select_primary_facade(base["plot"], concept, 0, user_confirmed=True)
    facade = generate_front_facade(
        base["plot"],
        concept,
        selection,
        base["match"],
        base["style_selection"],
        base["pack_ref"],
        base["pack_data"],
    )
    assessment = evaluate_architectural_quality(concept, envelope)
    build = build_architectural_sheets(
        plot=base["plot"],
        envelope=envelope,
        rules=rules,
        concept=concept,
        facade=facade,
        pack_ref=base["pack_ref"],
        pack_data=base["pack_data"],
        quality_assessment=assessment,
        candidate_id=optimization.selected_candidate_id,
        issue_date="2026-07-15",
        mode="all",
    )
    return {
        **base,
        "baseline_concept": base["concept"],
        "rules": rules,
        "envelope": envelope,
        "optimization": optimization,
        "concept": concept,
        "selection": selection,
        "facade": facade,
        "assessment": assessment,
        "build": build,
    }


def _export(state, out: Path, *, sheet_set: str = "all", optimized: bool = True):
    if optimized:
        concept = state["concept"]
        selection = state["selection"]
        facade = state["facade"]
        optimization = state["optimization"]
    else:
        concept = state["baseline_concept"]
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
        optimization = None
    return export_project(
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
        source_inputs=["sanitized synthetic reference"],
        optimization_result=optimization,
        sheet_set=sheet_set,
        **FIXED_RUN,
    )


@pytest.fixture(scope="module")
def exports(state, tmp_path_factory):
    first = tmp_path_factory.mktemp("m63-a")
    second = tmp_path_factory.mktemp("m63-b")
    manifest_a = _export(state, first)
    manifest_b = _export(state, second)
    return first, second, manifest_a, manifest_b


def _page(build, number: str, *, review: bool = False):
    pages = build.review_pages if review else build.concept_pages
    return next(page for page in pages if page.number == number)


def _text(page) -> str:
    return "\n".join(item.text for item in page.primitives if item.kind == "text")


def _primitive_bbox(item) -> BBox:
    if item.kind == "rect":
        return BBox(item.x, item.y, item.x + item.width, item.y + item.height)
    if item.kind == "circle":
        return BBox(
            item.x - item.radius,
            item.y - item.radius,
            item.x + item.radius,
            item.y + item.radius,
        )
    return BBox(
        min(point[0] for point in item.points),
        min(point[1] for point in item.points),
        max(point[0] for point in item.points),
        max(point[1] for point in item.points),
    )


class TestRequiredAreas01To10:
    def test_01_graphic_profile_validation(self):
        assert GRAPHIC_PROFILE.profile_id == "architectural_concept_a3_v1"
        assert GRAPHIC_PROFILE.validate() == ()

    def test_02_a3_paper_geometry(self):
        assert (GRAPHIC_PROFILE.paper_width_mm, GRAPHIC_PROFILE.paper_height_mm) == (420, 297)
        assert GRAPHIC_PROFILE.orientation == "landscape"

    def test_02_svg_text_uses_sheet_units(self, state):
        svg = render_sheet_svg(state["build"].concept_pages[0], GRAPHIC_PROFILE)
        assert 'font-size="7.0556"' in svg
        assert 'font-size="20pt"' not in svg
        assert 'font-family="Arial, Helvetica, sans-serif"' in svg

    def test_03_printable_margins(self):
        assert GRAPHIC_PROFILE.margin_mm == 10
        assert GRAPHIC_PROFILE.title_block_bottom_mm <= 297 - GRAPHIC_PROFILE.margin_mm
        assert not _primitive_within_page(
            Primitive(kind="line", points=((10, 10), (421, 10))), 420, 297
        )

    def test_04_title_block_completeness(self, state):
        required = (
            "SAUDI PLOT DESIGN STUDIO",
            "NOT FOR CONSTRUCTION",
            "P01",
            "GENERATED BY SPD M6.3",
            "SOURCE GEOMETRY",
        )
        for page in state["build"].review_pages:
            text = _text(page)
            assert all(value in text for value in required)
            assert page.number in text
        check_ids = [check["id"] for check in state["build"].validation.checks]
        assert len(check_ids) == len(set(check_ids))

    def test_05_deterministic_sheet_numbering(self, state):
        assert [entry.sheet_number for entry in state["build"].index_entries] == [
            "A-001",
            "A-101",
            "A-201",
            "A-601",
            "A-901",
        ]

    def test_06_deterministic_sheet_ordering(self, state):
        assert [page.number for page in state["build"].concept_pages] == [
            "A-001",
            "A-101",
            "A-201",
            "A-601",
        ]
        assert [page.number for page in state["build"].review_pages][-1] == "A-901"

    def test_07_plan_viewport_fitting(self, state):
        transform, _ = plan_transform(state["plot"], BBox(28, 31, 202, 234))
        points = [transform.point(point) for point in state["plot"].corners]
        assert min(x for x, _ in points) >= 28
        assert max(x for x, _ in points) <= 202
        assert min(y for _, y in points) >= 31
        assert max(y for _, y in points) <= 234

    def test_08_scale_selection(self):
        assert select_scale(20, 30, 174, 203) == 150
        assert select_scale(13.5, 4.3, 210, 90) == 75

    def test_08_index_scale_matches_rendered_page(self, state):
        pages = {page.number: page for page in state["build"].review_pages}
        assert all(
            entry.scale == pages[entry.sheet_number].scale for entry in state["build"].index_entries
        )

    def test_09_north_arrow_rendering(self, state):
        page = _page(state["build"], "A-101")
        assert any(item.role == "north-reference" for item in page.primitives)
        assert "NORTH NOT SURVEYED" in _text(page)
        assert "LOCAL PLOT +Y" in _text(page)

    def test_10_scale_bar_rendering(self, state):
        page = _page(state["build"], "A-101")
        assert sum(item.role == "scale-bar" for item in page.primitives) >= 12
        assert "10 m" in _text(page)


class TestRequiredAreas11To20:
    def test_11_plot_boundary_rendering(self, state):
        page = _page(state["build"], "A-101")
        items = [item for item in page.primitives if item.role == "plot-boundary"]
        assert len(items) == 1 and items[0].source_id == state["plot"].plot_id

    def test_12_setback_rendering(self, state):
        page = _page(state["build"], "A-101")
        envelope = [item for item in page.primitives if item.role == "buildable-envelope"]
        assert len(envelope) == 1 and envelope[0].dash_mm
        assert "FRONT SETBACK 3 m" in _text(page)

    def test_13_footprint_rendering(self, state):
        page = _page(state["build"], "A-101")
        items = [item for item in page.primitives if item.role == "building-footprint"]
        assert len(items) == 1 and items[0].source_id == state["concept"].concept_id

    def test_14_wall_hierarchy(self, state):
        page = _page(state["build"], "A-101")
        external = [item for item in page.primitives if item.role == "wall-cut"]
        internal = [item for item in page.primitives if item.role == "wall-projected"]
        assert external and internal
        assert min(item.stroke_width_mm for item in external) > max(
            item.stroke_width_mm for item in internal
        )

    def test_15_door_geometry_matches_canonical_openings(self, state):
        page = _page(state["build"], "A-101")
        leaf_ids = {item.source_id for item in page.primitives if item.role == "door-leaf"}
        swing_ids = {
            item.source_id for item in page.primitives if item.role == "door-swing-schematic"
        }
        expected = {door.id for door in state["concept"].doors}
        assert leaf_ids == expected == swing_ids

    def test_16_window_geometry_matches_canonical_openings(self, state):
        page = _page(state["build"], "A-101")
        ids = {item.source_id for item in page.primitives if item.role == "window-symbol"}
        assert ids == {window.id for window in state["concept"].windows}

    def test_17_room_labels_have_known_ids_and_inside_anchors(self, state):
        page = _page(state["build"], "A-101", review=True)
        transform, _ = plan_transform(state["plot"], BBox(28, 31, 202, 234))
        rooms = {room.id: room for room in state["concept"].rooms}
        labels = [item for item in page.primitives if item.role == "room-label"]
        assert {item.source_id for item in labels} == set(rooms)
        for item in labels:
            box = transform.rect(rooms[item.source_id].rect)
            assert box.min_x <= item.x <= box.max_x
            assert box.min_y <= item.y <= box.max_y

    def test_18_annotation_collision_resolution(self, state, exports):
        assert all(not record.unresolved for record in state["build"].collisions)
        payload = json.loads((exports[0] / COLLISION_REPORT).read_text(encoding="utf-8"))
        assert payload["summary"]["unresolved_collisions"] == 0
        assert payload["summary"]["required_annotations_silently_omitted"] == 0

    def test_19_dimension_engine_uses_canonical_values(self, state):
        text = _text(_page(state["build"], "A-101"))
        footprint = state["concept"].footprint
        assert "20.00 m PLOT" in text
        assert "30.00 m PLOT" in text
        assert f"{footprint.width:.2f} m FOOTPRINT" in text
        assert f"{footprint.height:.2f} m FOOTPRINT" in text

    def test_20_no_duplicate_dimension_labels_at_same_position(self, state):
        page = _page(state["build"], "A-101")
        labels = [
            (item.x, item.y, item.text)
            for item in page.primitives
            if item.kind == "text" and item.role == "dimension"
        ]
        assert len(labels) == len(set(labels))


class TestRequiredAreas21To30:
    def test_21_room_schedule_coverage(self, state):
        rows = room_schedule_rows(state["concept"], state["assessment"])
        assert len(rows) == len(state["concept"].rooms) == 14
        assert {row[0] for row in rows} == {room.id for room in state["concept"].rooms}

    def test_22_door_schedule_coverage(self, state):
        rows = door_schedule_rows(state["concept"], state["facade"])
        assert len(rows) == len(state["concept"].doors) == 15
        assert all(row[0].startswith("D") and " / d_" in row[0] for row in rows)

    def test_23_window_schedule_authored_and_na_handling(self, state):
        rows = window_schedule_rows(state["concept"], state["facade"])
        assert len(rows) == len(state["concept"].windows) == 11
        non_front = next(row for row in rows if "w_bedroom_2" in row[0])
        assert non_front[4:6] == ("1.30", "1.10")
        assert non_front[7] == "PLAN NOMINAL / FACADE N/A"
        internal_door = next(
            row
            for row in door_schedule_rows(state["concept"], state["facade"])
            if "d_bedroom_2" in row[0]
        )
        assert internal_door[5] == "N/A"

    def test_24_furniture_symbols_inside_rooms(self, state):
        page = _page(state["build"], "A-101", review=True)
        transform, _ = plan_transform(state["plot"], BBox(28, 31, 202, 234))
        rooms = {room.id: room for room in state["concept"].rooms}
        symbols = [
            item
            for item in page.primitives
            if item.role in {"concept-furniture", "concept-fixture"}
        ]
        assert symbols
        assert any(record.symbol_type == "wardrobe" for record in state["build"].furniture)
        for item in symbols:
            assert _primitive_bbox(item).inside(transform.rect(rooms[item.source_id].rect))

    def test_25_furniture_does_not_overlap_walls(self, state):
        page = _page(state["build"], "A-101", review=True)
        transform, _ = plan_transform(state["plot"], BBox(28, 31, 202, 234))
        rooms = {room.id: room for room in state["concept"].rooms}
        for item in page.primitives:
            if item.role in {"concept-furniture", "concept-fixture"}:
                assert _primitive_bbox(item).inside(
                    transform.rect(rooms[item.source_id].rect), gap=0.05
                )

    def test_26_furniture_clears_schematic_door_swings(self, state):
        page = _page(state["build"], "A-101", review=True)
        transform, _ = plan_transform(state["plot"], BBox(28, 31, 202, 234))
        clearance = _door_clearance_boxes(state["concept"], transform)
        for item in page.primitives:
            if item.role in {"concept-furniture", "concept-fixture"}:
                assert not any(
                    _primitive_bbox(item).intersects(box) for box in clearance[item.source_id]
                )

    def test_27_furniture_omissions_are_reported(self, state):
        omitted = [record for record in state["build"].furniture if record.disposition == "omitted"]
        assert {record.room_id for record in omitted} == {"guest_wc", "shared_bath"}
        assert all(record.reason for record in omitted)

    def test_28_unsafe_furniture_placement_is_detected(self):
        usable = BBox(0, 0, 10, 10)
        assert _safe_corner_box(usable, 4, 4, (BBox(0, 0, 10, 10),)) is None

    def test_29_elevation_composition(self, state):
        page = _page(state["build"], "A-201")
        assert any(item.role.startswith("facade-") for item in page.primitives)
        assert {item.source_id for item in page.primitives if item.role == "facade-opening"} == {
            opening.source_plan_opening_id for opening in state["facade"].facade_openings
        }
        assert "PARAPET" in _text(page) and "FINISHED GROUND" in _text(page)

    def test_30_schedule_pagination(self, state, exports):
        assert sum(page.number == "A-601" for page in state["build"].concept_pages) == 1
        reader = PdfReader(exports[0] / CONCEPT_PDF)
        schedule_pages = [page for page in reader.pages if "ROOM SCHEDULE" in page.extract_text()]
        assert len(schedule_pages) == 1


class TestRequiredAreas31To40:
    def test_31_a901_finding_coverage(self, state):
        text = _text(_page(state["build"], "A-901", review=True))
        active = {
            finding.rule_id
            for finding in state["assessment"].findings
            if finding.severity.value in {"major", "moderate"}
            and finding.status.value in {"warning", "fail"}
        }
        assert active <= set(text.split())
        assert "UNSUPPORTED / NOT EVALUABLE" in text

    def test_32_adj006_and_sau005_remain(self, state):
        text = _text(_page(state["build"], "A-901", review=True))
        assert "ADJ-006" in text and "SAU-005" in text
        assert state["assessment"].overall_score == 88.89
        assert state["assessment"].score_status.value == "workable_with_targeted_revisions"

    def test_32_candidate_id_does_not_imply_a_score(self, state):
        assessment = state["assessment"].model_copy(update={"overall_score": 87.65})
        build = build_architectural_sheets(
            plot=state["plot"],
            envelope=state["envelope"],
            rules=state["rules"],
            concept=state["concept"],
            facade=state["facade"],
            pack_ref=state["pack_ref"],
            pack_data=state["pack_data"],
            quality_assessment=assessment,
            candidate_id="candidate-016",
            issue_date="2026-07-15",
            mode="all",
        )
        assert build.validation.passed
        assert "87.65" in _text(_page(build, "A-901", review=True))

    def test_33_clean_set_omits_debug_overlays(self, state):
        page = _page(state["build"], "A-101")
        assert not any(item.role == "review-marker" for item in page.primitives)
        assert "CLEAN VARIANT" in _text(page)

    def test_34_review_set_retains_review_evidence(self, state):
        page = _page(state["build"], "A-101", review=True)
        assert {item.source_id for item in page.primitives if item.role == "review-marker"} == {
            "ADJ-006",
            "SAU-005",
        }
        assert "REVIEW VARIANT" in _text(page)

    def test_35_pdf_media_box_is_a3_landscape(self, exports):
        for name in (CONCEPT_PDF, REVIEW_PDF):
            reader = PdfReader(exports[0] / name)
            for page in reader.pages:
                assert float(page.mediabox.width) == pytest.approx(1190.55, abs=0.5)
                assert float(page.mediabox.height) == pytest.approx(841.89, abs=0.5)

    def test_36_pdf_page_order(self, exports):
        concept = [page.extract_text() for page in PdfReader(exports[0] / CONCEPT_PDF).pages]
        review = [page.extract_text() for page in PdfReader(exports[0] / REVIEW_PDF).pages]
        assert len(concept) == 4 and len(review) == 5
        assert [
            "COVER AND DESIGN BASIS" in concept[0],
            "SITE AND GROUND FLOOR PLAN" in concept[1],
            "FRONT ELEVATION" in concept[2],
            "ROOM, DOOR AND WINDOW SCHEDULES" in concept[3],
        ] == [True] * 4
        assert "DESIGN REVIEW AND LIMITATIONS" in review[4]

    def test_37_pdf_text_and_disclaimers(self, exports):
        for name in (CONCEPT_PDF, REVIEW_PDF):
            for page in PdfReader(exports[0] / name).pages:
                text = page.extract_text()
                assert "DEMO DATA" in text
                assert "NOT FOR CONSTRUCTION" in text
                assert "APPROVED" not in text

    def test_38_svg_determinism(self, exports):
        first, second, _, _ = exports
        names = sorted(path.relative_to(first) for path in (first / "sheets").glob("*.svg"))
        assert names
        for name in names:
            assert (first / name).read_bytes() == (second / name).read_bytes()

    def test_39_pdf_determinism(self, exports):
        first, second, _, _ = exports
        for name in (CONCEPT_PDF, REVIEW_PDF):
            assert (first / name).read_bytes() == (second / name).read_bytes()

    def test_40_dxf_determinism(self, exports):
        first, second, _, _ = exports
        name = "saudi_plot_design_reference.dxf"
        assert (first / name).read_bytes() == (second / name).read_bytes()


class TestRequiredAreas41To50:
    def test_41_professional_dxf_layer_mapping(self, state, exports):
        doc = ezdxf.readfile(exports[0] / "saudi_plot_design_reference.dxf")
        names = {layer.dxf.name for layer in doc.layers}
        assert set(PROFESSIONAL_LAYER_SPECS) <= names
        for name, spec in PROFESSIONAL_LAYER_SPECS.items():
            layer = doc.layers.get(name)
            assert layer.dxf.lineweight == spec["lineweight"]
            assert layer.dxf.linetype == spec["linetype"]
        msp = doc.modelspace()
        assert len(msp.query('ARC[layer=="A-DOOR"]')) == 15
        assert len(msp.query('LINE[layer=="A-WIND"]')) == 22
        rooms = {room.id: room for room in state["concept"].rooms}
        clearance = _professional_door_clearance(state["concept"])
        symbols = [
            *msp.query('LWPOLYLINE[layer=="A-FURN"]'),
            *msp.query('LWPOLYLINE[layer=="A-FIXT"]'),
        ]
        assert symbols
        assert any(entity.get_xdata(APPID)[1].value == "wardrobe" for entity in symbols)
        for entity in symbols:
            room_id = entity.get_xdata(APPID)[0].value
            points = list(entity.get_points("xy"))
            box = (
                min(point[0] for point in points),
                min(point[1] for point in points),
                max(point[0] for point in points),
                max(point[1] for point in points),
            )
            room = rooms[room_id].rect
            assert room.min_x < box[0] < box[2] < room.max_x
            assert room.min_y < box[1] < box[3] < room.max_y
            assert not any(_boxes_intersect(box, other) for other in clearance[room_id])

    def test_42_run_json_integration(self, state, exports):
        payload = json.loads((exports[0] / "run.json").read_text(encoding="utf-8"))
        sheets = payload["architectural_sheets"]
        assert sheets["sheet_set_mode"] == "all"
        assert sheets["source_candidate_id"] == "candidate-016"
        assert sheets["source_geometry_fingerprint"] == geometry_fingerprint(state["concept"])
        for name, digest in payload["output_sha256"].items():
            assert sha256_file(exports[0] / name) == digest

    def test_43_export_and_sheet_manifest_integration(self, exports):
        first, _, manifest, _ = exports
        assert manifest.schema_version == 3
        assert manifest.sheet_set_mode == "all"
        assert manifest.architectural_sheet_validation_status == "all_sheet_checks_passed"
        assert manifest.architectural_sheet_unresolved_collisions == 0
        assert verify_sheet_manifest(first) == ()
        for name, digest in manifest.file_sha256.items():
            assert sha256_file(first / name) == digest

    def test_44_sheet_index_consistency(self, exports):
        payload = json.loads((exports[0] / SHEET_INDEX).read_text(encoding="utf-8"))
        assert [sheet["sheet_number"] for sheet in payload["sheets"]] == [
            "A-001",
            "A-101",
            "A-201",
            "A-601",
            "A-901",
        ]
        assert all((exports[0] / sheet["output_filename"]).is_file() for sheet in payload["sheets"])

    def test_45_geometry_fingerprint_consistency(self, state, exports):
        expected = geometry_fingerprint(state["concept"])
        index = json.loads((exports[0] / SHEET_INDEX).read_text(encoding="utf-8"))
        manifest = json.loads((exports[0] / SHEET_MANIFEST).read_text(encoding="utf-8"))
        assert index["source_geometry_fingerprint"] == expected
        assert manifest["source_geometry_fingerprint"] == expected
        assert all(page.geometry_fingerprint == expected for page in state["build"].review_pages)

    def test_46_baseline_mode_compatibility(self, state, tmp_path):
        manifest = _export(state, tmp_path / "baseline", sheet_set="concept", optimized=False)
        assert manifest.layout_mode is None
        assert manifest.sheet_source_candidate_id == "baseline"
        assert (tmp_path / "baseline" / CONCEPT_PDF).is_file()
        assert not (tmp_path / "baseline" / REVIEW_PDF).exists()

    def test_47_optimized_mode_compatibility(self, state, exports):
        manifest = exports[2]
        assert manifest.layout_mode == "optimized"
        assert manifest.layout_selected_candidate_id == "candidate-016"
        assert manifest.quality_overall_score == 88.89
        assert state["optimization"].selected_candidate_id == "candidate-016"

    def test_48_sheet_generation_does_not_change_selected_geometry(self, state):
        before = state["concept"].model_dump_json()
        render_sheet_svg(_page(state["build"], "A-101"), GRAPHIC_PROFILE)
        assert state["concept"].model_dump_json() == before
        assert state["concept"].fingerprint == "5d41fae6e39c6d0e"

    def test_49_existing_cli_and_new_sheet_modes(self, tmp_path):
        parser = build_parser()
        common = [
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
            "--out",
            str(tmp_path),
        ]
        assert parser.parse_args(common).sheet_set == "concept"
        for mode in ("none", "concept", "review", "all"):
            args = parser.parse_args([*common, "--sheet-set", mode])
            assert (
                args.sheet_set == mode and args.paper_size == "A3" and args.sheet_language == "en"
            )
        with pytest.raises(SystemExit):
            parser.parse_args([*common, "--paper-size", "A1"])
        with pytest.raises(SystemExit):
            parser.parse_args([*common, "--sheet-language", "ar"])

    def test_50_complete_sheet_validation_is_green(self, state):
        assert state["build"].validation.passed
        assert all(check["passed"] for check in state["build"].validation.checks)
        assert state["assessment"].overall_score == 88.89
        assert [
            finding.rule_id
            for finding in state["assessment"].findings
            if finding.severity.value == "major" and finding.status.value in {"warning", "fail"}
        ] == ["ADJ-006", "SAU-005"]


@pytest.mark.parametrize(
    ("mode", "concept_pdf", "review_pdf", "svg_count"),
    (("concept", True, False, 4), ("review", False, True, 5), ("all", True, True, 5)),
)
def test_sheet_export_modes(state, tmp_path, mode, concept_pdf, review_pdf, svg_count):
    result = export_architectural_sheets(
        tmp_path / mode,
        plot=state["plot"],
        envelope=state["envelope"],
        rules=state["rules"],
        concept=state["concept"],
        facade=state["facade"],
        pack_ref=state["pack_ref"],
        pack_data=state["pack_data"],
        quality_assessment=state["assessment"],
        candidate_id="candidate-016",
        generation_timestamp=FIXED_RUN["generation_timestamp"],
        mode=mode,
    )
    assert bool(result.concept_pdf_path) is concept_pdf
    assert bool(result.review_pdf_path) is review_pdf
    assert len(result.svg_paths) == svg_count
    assert verify_sheet_manifest(tmp_path / mode) == ()


def test_sheet_set_none_preserves_legacy_output_surface(state, tmp_path):
    manifest = _export(state, tmp_path, sheet_set="none")
    assert manifest.sheet_set_mode is None
    assert not (tmp_path / SHEET_INDEX).exists()
    assert not (tmp_path / "sheets").exists()


def test_nested_sheet_directory_rolls_back_as_a_unit(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    out = tmp_path / "out"
    (staging / "sheets").mkdir(parents=True)
    (out / "sheets").mkdir(parents=True)
    (staging / "sheets" / "new.svg").write_text("new", encoding="utf-8")
    (out / "sheets" / "old.svg").write_text("old", encoding="utf-8")
    (staging / "run.json").write_text("{}", encoding="utf-8")
    real_replace = os.replace

    def fail_on_run(source, destination):
        if Path(source).name == "run.json" and Path(source).parent == staging:
            raise PermissionError("simulated publication failure")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_on_run)
    with pytest.raises(PermissionError):
        _publish_with_rollback(staging, out)
    assert (out / "sheets" / "old.svg").read_text(encoding="utf-8") == "old"
    assert not (out / "sheets" / "new.svg").exists()


def test_all_sheet_artifacts_embed_unconditional_disclaimer(exports):
    root = exports[0]
    for name in (SHEET_INDEX, SHEET_MANIFEST, COLLISION_REPORT):
        assert json.loads((root / name).read_text(encoding="utf-8"))["disclaimer"] == DISCLAIMER
    for path in (root / "sheets").glob("*.svg"):
        assert "DEMO DATA" in path.read_text(encoding="utf-8")
