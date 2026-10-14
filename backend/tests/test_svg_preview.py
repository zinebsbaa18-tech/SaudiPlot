"""Smoke tests for the M2 engineering SVG preview."""

import pytest

from saudi_plot_design.export.svg_preview import render_concept_svg, write_concept_svg
from saudi_plot_design.output import DISCLAIMER
from saudi_plot_design.planner.compact_3br import plan_compact_3br
from saudi_plot_design.plot.geometry import build_plot_model
from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
from tests.conftest import REFERENCE_CORNERS, standard_edges


@pytest.fixture(scope="module")
def setup():
    model, _ = build_plot_model(REFERENCE_CORNERS, standard_edges(), 15.0)
    envelope = compute_envelope(model, load_default_setback_rules())
    return model, envelope, plan_compact_3br(model, envelope)


class TestSvgPreview:
    def test_svg_renders_and_is_wellformed_xml(self, setup):
        import xml.etree.ElementTree as ET

        svg = render_concept_svg(*setup)
        root = ET.fromstring(svg)
        assert root.tag.endswith("svg")

    def test_svg_contains_all_layers(self, setup):
        svg = render_concept_svg(*setup)
        _, _, concept = setup
        assert "STREET" in svg
        assert "Men&apos;s Majlis" in svg or "Men's Majlis" in svg
        assert svg.count("<line") >= len(concept.walls) + len(concept.doors) + len(concept.windows)
        assert "footprint" in svg and "envelope" in svg

    def test_svg_carries_unconditional_disclaimer(self, setup):
        svg = render_concept_svg(*setup)
        # The em dash is XML-escaped-safe as-is; check a distinctive fragment.
        assert "DEMO DATA" in svg
        assert DISCLAIMER.split(" — ")[1][:30] in svg

    def test_svg_writes_to_disk(self, setup, tmp_path):
        path = write_concept_svg(tmp_path / "preview" / "concept.svg", *setup)
        assert path.is_file()
        assert path.read_text(encoding="utf-8").startswith("<svg")

    def test_rotated_street_label_clears_title_zone(self):
        # Regression (Codex M2 P2): with the street on the far edge the label
        # sits at the top of the drawing and must not overlap the title block.
        import re

        from saudi_plot_design.model import EdgeClass

        edges = (EdgeClass.NEIGHBOR, EdgeClass.NEIGHBOR, EdgeClass.STREET, EdgeClass.NEIGHBOR)
        model, _ = build_plot_model(REFERENCE_CORNERS, edges, 15.0)
        envelope = compute_envelope(model, load_default_setback_rules())
        concept = plan_compact_3br(model, envelope)
        svg = render_concept_svg(model, envelope, concept)
        street_text = next(part for part in svg.split("<text") if "STREET" in part)
        label_y = float(re.search(r'y="([-\d.]+)"', street_text).group(1))
        assert label_y > 55.0  # below the reserved title zone (title at y<=46)

    def test_rejected_concept_still_renders(self, setup):
        from saudi_plot_design.model import BuildableEnvelope

        model, envelope, _ = setup
        tiny = BuildableEnvelope(
            corners=((0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (0.0, 5.0)),
            area_m2=25.0,
            width_m=5.0,
            depth_m=5.0,
        )
        rejected = plan_compact_3br(model, tiny)
        svg = render_concept_svg(model, envelope, rejected)
        assert "REJECTED" in svg
