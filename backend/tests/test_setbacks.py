"""Tests for setback rule loading and buildable-envelope computation (M1)."""

import json

import pytest

from saudi_plot_design.model import SetbackRuleSet, SpdInputError
from saudi_plot_design.plot.geometry import build_plot_model
from saudi_plot_design.rules.setbacks import (
    compute_envelope,
    load_default_setback_rules,
    load_setback_rules,
)
from tests.conftest import DEMO_RULES, REFERENCE_CORNERS, standard_edges


def demo_rule_dict(**overrides):
    base = json.loads(DEMO_RULES.read_text(encoding="utf-8"))
    base.update(overrides)
    return base


def write_rules(tmp_path, data):
    p = tmp_path / "rules.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture
def reference_plot():
    model, _ = build_plot_model(REFERENCE_CORNERS, standard_edges(), 15.0)
    return model


class TestRuleLoading:
    def test_demo_rules_load(self):
        rules = load_setback_rules(DEMO_RULES)
        assert rules.id == "DEMO-SETBACK-01"
        assert rules.provenance == "demo"
        assert (rules.front_m, rules.side_m, rules.rear_m) == (3.0, 2.0, 2.0)

    def test_verified_provenance_rejected(self, tmp_path):
        p = write_rules(tmp_path, demo_rule_dict(provenance="verified"))
        with pytest.raises(SpdInputError, match="provenance"):
            load_setback_rules(p)

    def test_missing_provenance_rejected(self, tmp_path):
        data = demo_rule_dict()
        del data["provenance"]
        p = write_rules(tmp_path, data)
        with pytest.raises(SpdInputError, match="provenance"):
            load_setback_rules(p)

    def test_non_demo_id_rejected(self, tmp_path):
        p = write_rules(tmp_path, demo_rule_dict(id="RIYADH-SETBACK-01"))
        with pytest.raises(SpdInputError, match="id"):
            load_setback_rules(p)

    def test_extra_field_rejected(self, tmp_path):
        p = write_rules(tmp_path, demo_rule_dict(max_height_m=12.0))
        with pytest.raises(SpdInputError, match="max_height_m"):
            load_setback_rules(p)

    def test_negative_setback_rejected(self, tmp_path):
        p = write_rules(tmp_path, demo_rule_dict(front_m=-3.0))
        with pytest.raises(SpdInputError, match="front_m"):
            load_setback_rules(p)

    def test_missing_file(self):
        with pytest.raises(SpdInputError, match="not found"):
            load_setback_rules("no_such_rules.json")

    def test_default_rules_load_from_package_resources(self):
        rules = load_default_setback_rules()
        assert rules.id == "DEMO-SETBACK-01"
        assert rules.provenance == "demo"

    def test_infinite_setback_rejected(self, tmp_path):
        p = tmp_path / "rules.json"
        p.write_text(
            json.dumps(demo_rule_dict()).replace('"front_m": 3.0', '"front_m": 1e400'),
            encoding="utf-8",
        )
        with pytest.raises(SpdInputError, match="front_m"):
            load_setback_rules(p)

    def test_nan_setback_rejected(self, tmp_path):
        p = tmp_path / "rules.json"
        p.write_text(
            json.dumps(demo_rule_dict()).replace('"side_m": 2.0', '"side_m": NaN'),
            encoding="utf-8",
        )
        with pytest.raises(SpdInputError, match="side_m"):
            load_setback_rules(p)


class TestEnvelope:
    def test_reference_envelope_16_by_25(self, reference_plot):
        envelope = compute_envelope(reference_plot, load_setback_rules(DEMO_RULES))
        assert envelope.width_m == pytest.approx(16.0)
        assert envelope.depth_m == pytest.approx(25.0)
        assert envelope.area_m2 == pytest.approx(400.0)
        assert set(envelope.corners) == {(2.0, 3.0), (18.0, 3.0), (18.0, 28.0), (2.0, 28.0)}

    def test_envelope_with_street_on_far_edge(self):
        from saudi_plot_design.model import EdgeClass

        edges = (EdgeClass.NEIGHBOR, EdgeClass.NEIGHBOR, EdgeClass.STREET, EdgeClass.NEIGHBOR)
        model, _ = build_plot_model(REFERENCE_CORNERS, edges, 15.0)
        envelope = compute_envelope(model, load_setback_rules(DEMO_RULES))
        # Front setback (3 m) now at y=30 side, rear (2 m) at y=0.
        assert set(envelope.corners) == {(2.0, 2.0), (18.0, 2.0), (18.0, 27.0), (2.0, 27.0)}
        assert envelope.area_m2 == pytest.approx(400.0)

    def test_empty_envelope_rejected(self, reference_plot):
        rules = SetbackRuleSet(
            id="DEMO-HUGE",
            provenance="demo",
            display_name="demo",
            statement="demo",
            front_m=16.0,
            side_m=11.0,
            rear_m=16.0,
        )
        with pytest.raises(SpdInputError, match="no buildable area"):
            compute_envelope(reference_plot, rules)

    def test_suspiciously_small_envelope_rejected(self, reference_plot):
        rules = SetbackRuleSet(
            id="DEMO-TIGHT",
            provenance="demo",
            display_name="demo",
            statement="demo",
            front_m=14.5,
            side_m=9.9,
            rear_m=14.5,
        )
        with pytest.raises(SpdInputError, match="below the minimum plannable area"):
            compute_envelope(reference_plot, rules)
