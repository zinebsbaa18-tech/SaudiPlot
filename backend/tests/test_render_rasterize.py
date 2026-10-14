"""Smoke tests: real design-engine plan SVG through _rasterize_svg.

These tests confirm that cairosvg can process the actual SVG output produced
by ``saudi_plot_design`` (Saudi-character styling, hatching, Arabic labels,
multi-layer geometry) — not just a hand-written stub.  A failure here means
users with a Gemini key would silently get a broken presentation render.

The suite skips cleanly when cairosvg is not installed (core-only environment).
"""

from __future__ import annotations

import pytest

cairosvg = pytest.importorskip("cairosvg", reason="cairosvg not installed")

# Design-engine helpers — always available in the backend package.
from saudi_plot_design.export.svg_preview import write_concept_svg  # noqa: E402
from saudi_plot_design.planner.compact_3br import plan_compact_3br  # noqa: E402
from saudi_plot_design.plot.geometry import build_plot_model  # noqa: E402
from saudi_plot_design.rules.setbacks import (  # noqa: E402
    compute_envelope,
    load_default_setback_rules,
)
from saudi_plot_api.services.render import _rasterize_svg  # noqa: E402
from tests.conftest import REFERENCE_CORNERS, standard_edges  # noqa: E402

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(scope="module")
def plan_svg(tmp_path_factory):
    """Write a full design-engine plan SVG to a temp file and return the path."""
    tmp = tmp_path_factory.mktemp("render_rasterize")
    model, _ = build_plot_model(REFERENCE_CORNERS, standard_edges(), 15.0)
    envelope = compute_envelope(model, load_default_setback_rules())
    concept = plan_compact_3br(model, envelope)
    return write_concept_svg(tmp / "plan.svg", model, envelope, concept)


class TestRasterizeSvg:
    def test_returns_valid_png(self, plan_svg):
        """_rasterize_svg must return bytes that start with the PNG signature."""
        png = _rasterize_svg(plan_svg)
        assert png[:8] == _PNG_SIG, (
            f"Expected PNG header {_PNG_SIG.hex()}, got {png[:8].hex()}"
        )

    def test_png_is_not_trivially_empty(self, plan_svg):
        """The PNG must be large enough to contain real geometry, not a blank tile."""
        png = _rasterize_svg(plan_svg)
        # A 700×1065 plan should easily exceed 10 KB when non-trivial content
        # is present.  This catches cairosvg producing a tiny blank image.
        assert len(png) > 10_000, (
            f"PNG is suspiciously small ({len(png)} bytes) — "
            "cairosvg may have produced a blank or corrupt image."
        )

    def test_input_svg_contains_expected_content(self, plan_svg):
        """Guard: ensure the fixture produces a real engineering SVG, not a stub."""
        text = plan_svg.read_text(encoding="utf-8")
        assert "<svg" in text
        assert "STREET" in text  # street-edge label must be present
        # Arabic room labels confirm the full label-rendering pipeline ran.
        assert "جلوس" in text or "مجلس" in text or "Majlis" in text

    def test_different_plot_orientation_also_rasterizes(self, tmp_path):
        """A plot with the street on the far (north) edge must also rasterize.

        Regression guard: rotated plans produce different SVG geometry and have
        tripped rasterizers that assume a canonical viewBox orientation.
        """
        from saudi_plot_design.model import EdgeClass

        north_street = (
            EdgeClass.NEIGHBOR,
            EdgeClass.NEIGHBOR,
            EdgeClass.STREET,
            EdgeClass.NEIGHBOR,
        )
        model, _ = build_plot_model(REFERENCE_CORNERS, north_street, 15.0)
        envelope = compute_envelope(model, load_default_setback_rules())
        concept = plan_compact_3br(model, envelope)
        svg_path = write_concept_svg(tmp_path / "plan_north.svg", model, envelope, concept)
        png = _rasterize_svg(svg_path)
        assert png[:8] == _PNG_SIG
        assert len(png) > 10_000
