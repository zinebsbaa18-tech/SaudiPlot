"""Tests for the structured JSON plot report (M1)."""

import json

from saudi_plot_design.output import DISCLAIMER, plot_report, write_plot_report
from saudi_plot_design.plot.geometry import build_plot_model, load_corners_csv
from saudi_plot_design.rules.setbacks import compute_envelope, load_setback_rules
from tests.conftest import DEMO_RULES, SAMPLE_CSV, standard_edges


def build_report():
    corners = load_corners_csv(SAMPLE_CSV)
    model, metrics = build_plot_model(corners, standard_edges(), 15.0, location=(24.65, 46.71))
    rules = load_setback_rules(DEMO_RULES)
    envelope = compute_envelope(model, rules)
    return plot_report(model, metrics, rules, envelope)


class TestPlotReport:
    def test_report_carries_unconditional_disclaimer(self):
        report = build_report()
        assert report["disclaimer"] == DISCLAIMER

    def test_disclaimer_is_verbatim_mandated_text(self):
        # Exact text from GEOSPATIAL_DATA_PROVENANCE.md par.1 rule 3, em dash included.
        assert DISCLAIMER == (
            "DEMO DATA — geographic zones, setback rules, and style rules are "
            "demonstration data, not official Saudi regulations or official "
            "Saudi Architecture guidelines."
        )

    def test_report_content(self):
        report = build_report()
        assert report["metrics"]["area_m2"] == 600.0
        assert report["metrics"]["perimeter_m"] == 100.0
        assert report["metrics"]["centroid_m"] == [10.0, 15.0]
        assert report["plot"]["street_edge_index"] == 0
        assert report["plot"]["street_width_m"] == 15.0
        assert report["setback_rules"]["id"] == "DEMO-SETBACK-01"
        assert report["setback_rules"]["provenance"] == "demo"
        assert report["buildable_envelope"]["width_m"] == 16.0
        assert report["buildable_envelope"]["depth_m"] == 25.0
        assert report["buildable_envelope"]["area_m2"] == 400.0

    def test_report_round_trips_to_disk(self, tmp_path):
        report = build_report()
        path = write_plot_report(tmp_path / "run" / "plot_report.json", report)
        assert json.loads(path.read_text(encoding="utf-8")) == report
