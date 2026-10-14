"""Tests for the M4 facade SVG preview."""

import xml.etree.ElementTree as ET

import pytest

from saudi_plot_design.elevation.facade_selection import select_primary_facade
from saudi_plot_design.elevation.front import generate_front_facade
from saudi_plot_design.export.svg_elevation import render_facade_svg, write_facade_svg
from saudi_plot_design.output import DISCLAIMER
from tests.conftest import reference_pipeline

ARABIC_LOGICAL = "الطابع النجدي التجريبي"
ARABIC_REVERSED = "يبيرجتلا يدجنلا عباطلا"


@pytest.fixture(scope="module")
def state():
    return reference_pipeline()


@pytest.fixture(scope="module")
def facade(state):
    selection = select_primary_facade(state["plot"], state["concept"], 0, user_confirmed=True)
    return generate_front_facade(
        state["plot"],
        state["concept"],
        selection,
        state["match"],
        state["style_selection"],
        state["pack_ref"],
        state["pack_data"],
    )


@pytest.fixture(scope="module")
def svg(state, facade):
    return render_facade_svg(facade, state["pack_data"])


class TestFacadeSvg:
    def test_valid_xml(self, svg):
        root = ET.fromstring(svg)
        assert root.tag.endswith("svg")
        assert root.get("viewBox")

    def test_no_raster_images(self, svg):
        assert "<image" not in svg
        assert "base64" not in svg

    def test_deterministic(self, state, facade):
        assert render_facade_svg(facade, state["pack_data"]) == render_facade_svg(
            facade, state["pack_data"]
        )

    def test_disclaimer_present(self, svg):
        assert DISCLAIMER.split(" — ")[1][:30] in svg
        assert "DEMO DATA" in svg

    def test_arabic_material_names_logical_order(self, svg):
        # Arabic must appear in logical Unicode order, never reversed.
        assert "لياسة طينية" in svg  # earthen render (demo), logical order
        assert ARABIC_REVERSED not in svg

    def test_source_ids_as_attributes(self, svg, facade):
        for opening in facade.facade_openings:
            assert f'data-source-plan-opening="{opening.source_plan_opening_id}"' in svg

    def test_contains_all_layers(self, svg, facade):
        for needle in (
            "finished ground 0.00",
            "facade length",
            "wall 3.6 m",
            "materials (DEMO)",
            "main entrance",
            "majlis entrance",
            facade.style_pack_id,
            facade.plan_concept_id,
            "plot-edge-1",
        ):
            assert needle in svg, needle

    def test_writes_to_disk(self, state, facade, tmp_path):
        path = write_facade_svg(tmp_path / "elev" / "facade.svg", facade, state["pack_data"])
        assert path.is_file()
        assert path.read_text(encoding="utf-8").startswith("<svg")

    def test_element_count_matches_concept(self, svg, facade):
        # Every element and opening renders exactly once.
        assert svg.count("data-element-type=") == len(facade.facade_elements)
        assert svg.count("data-source-plan-opening=") == len(facade.facade_openings)
