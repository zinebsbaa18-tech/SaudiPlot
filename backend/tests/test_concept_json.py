"""Tests for canonical concept JSON output and schema round-trip (M2)."""

import json

import pytest

from saudi_plot_design.model import Concept
from saudi_plot_design.output import DISCLAIMER, concept_report, write_concept_report
from saudi_plot_design.planner.compact_3br import plan_compact_3br
from saudi_plot_design.plot.geometry import build_plot_model
from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
from tests.conftest import REFERENCE_CORNERS, standard_edges


@pytest.fixture(scope="module")
def concept():
    model, _ = build_plot_model(REFERENCE_CORNERS, standard_edges(), 15.0)
    envelope = compute_envelope(model, load_default_setback_rules())
    return plan_compact_3br(model, envelope)


class TestConceptJson:
    def test_report_carries_unconditional_disclaimer(self, concept):
        report = concept_report(concept)
        assert report["disclaimer"] == DISCLAIMER
        assert report["is_valid"] is True

    def test_schema_round_trip(self, concept, tmp_path):
        path = write_concept_report(tmp_path / "concept.json", concept)
        data = json.loads(path.read_text(encoding="utf-8"))
        # The concept payload validates against the canonical pydantic schema
        # and reconstructs an identical model.
        restored = Concept.model_validate(data["concept"])
        assert restored == concept

    def test_json_is_deterministic(self, concept, tmp_path):
        p1 = write_concept_report(tmp_path / "a.json", concept)
        p2 = write_concept_report(tmp_path / "b.json", concept)
        assert p1.read_text(encoding="utf-8") == p2.read_text(encoding="utf-8")

    def test_report_contains_all_collections(self, concept):
        payload = concept_report(concept)["concept"]
        assert len(payload["rooms"]) == 14
        assert len(payload["walls"]) > 20
        assert len(payload["doors"]) == 15
        assert len(payload["windows"]) == 11
        assert payload["skeleton_id"] == "compact_3br"
        assert payload["assumptions"]

    def test_rejected_concept_serializes(self, tmp_path):
        from saudi_plot_design.model import BuildableEnvelope

        model, _ = build_plot_model(REFERENCE_CORNERS, standard_edges(), 15.0)
        tiny = BuildableEnvelope(
            corners=((0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (0.0, 5.0)),
            area_m2=25.0,
            width_m=5.0,
            depth_m=5.0,
        )
        rejected = plan_compact_3br(model, tiny)
        report = concept_report(rejected)
        assert report["is_valid"] is False
        assert report["concept"]["rejection_reasons"]
        restored = Concept.model_validate(report["concept"])
        assert not restored.is_valid
