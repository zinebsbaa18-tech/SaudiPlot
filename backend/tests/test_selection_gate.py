"""Tests for style selection, confirmation gate, and M3 artifacts."""

import json

import pytest

from saudi_plot_design.character.engine import load_zone_dataset, recommend_character
from saudi_plot_design.character.models import LocationPoint, SelectionMethod
from saudi_plot_design.character.selection import (
    confirm_selection,
    confirmation_gate,
    override_selection,
    recommend_style,
)
from saudi_plot_design.model import SpdInputError
from saudi_plot_design.output import (
    DISCLAIMER,
    character_match_report,
    style_pack_snapshot,
    style_selection_report,
    write_plot_report,
)
from saudi_plot_design.plot.geometry import build_plot_model
from saudi_plot_design.styles.loader import load_pilot_style_pack
from tests.conftest import REFERENCE_CORNERS, standard_edges

PILOT = LocationPoint(latitude=24.65, longitude=46.71)


@pytest.fixture(scope="module")
def dataset():
    return load_zone_dataset()


@pytest.fixture(scope="module")
def pack(dataset):
    return load_pilot_style_pack(known_zone_ids=tuple(z.zone_id for z in dataset.zones))


@pytest.fixture(scope="module")
def match(dataset):
    return recommend_character(dataset, PILOT)


@pytest.fixture
def recommendation(dataset, match):
    zone = dataset.zone_by_id(match.selected_zone_id)
    return recommend_style(match, zone.style_pack_id)


class TestGateStates:
    def test_state_a_recommended_but_unconfirmed_is_blocked(self, match, recommendation, pack):
        reference, _ = pack
        assert recommendation.selection_method is SelectionMethod.AUTOMATIC_RECOMMENDATION
        assert recommendation.user_confirmed is False
        gate = confirmation_gate(match, recommendation, reference)
        assert not gate.passed
        assert any("user_confirmed is false" in r for r in gate.reasons)

    def test_state_b_user_confirmed_passes(self, match, recommendation, pack):
        reference, _ = pack
        confirmed = confirm_selection(recommendation, reference)
        assert confirmed.selection_method is SelectionMethod.USER_CONFIRMED
        assert confirmed.user_confirmed is True
        assert confirmed.style_pack_version == "0.1.0"
        gate = confirmation_gate(match, confirmed, reference)
        assert gate.passed
        assert gate.reasons == ()

    def test_state_c_override_without_reason_fails(self, recommendation, pack):
        reference, _ = pack
        with pytest.raises(SpdInputError, match="non-empty override reason"):
            override_selection(recommendation, reference, "")
        with pytest.raises(SpdInputError, match="non-empty override reason"):
            override_selection(recommendation, reference, "   ")

    def test_state_c_override_with_reason_passes(self, dataset, pack):
        # Override applies the only pilot pack in a zone it is NOT declared
        # applicable to (Hejazi zone) - reason required, then gate passes.
        reference, _ = pack
        hejazi_match = recommend_character(dataset, LocationPoint(latitude=21.5, longitude=39.2))
        assert hejazi_match.selected_zone_id == "DEMO-ZONE-HEJAZI-01"
        selection = recommend_style(
            hejazi_match, dataset.zone_by_id(hejazi_match.selected_zone_id).style_pack_id
        )
        assert selection.selection_method is SelectionMethod.UNRESOLVED
        overridden = override_selection(
            selection, reference, "client requested Najdi character for a Hejazi-zone plot"
        )
        assert overridden.selection_method is SelectionMethod.MANUAL_OVERRIDE
        assert overridden.override_reason
        gate = confirmation_gate(hejazi_match, overridden, reference)
        assert gate.passed

    def test_state_d_no_match_stays_unresolved_until_confirmed(self, dataset, pack):
        reference, _ = pack
        no_match = recommend_character(dataset, LocationPoint(latitude=20.0, longitude=50.0))
        selection = recommend_style(no_match, None)
        assert selection.selection_method is SelectionMethod.UNRESOLVED
        gate = confirmation_gate(no_match, selection, reference)
        assert not gate.passed
        resolved = override_selection(
            selection, reference, "no demo zone covers the plot; user chose the pilot style"
        )
        gate2 = confirmation_gate(no_match, resolved, reference)
        assert gate2.passed

    def test_zone_incompatible_pack_without_reason_blocked(self, dataset, pack):
        reference, _ = pack
        hejazi_match = recommend_character(dataset, LocationPoint(latitude=21.5, longitude=39.2))
        forced = recommend_style(hejazi_match, "najdi_demo_v1").model_copy(
            update={
                "selection_method": SelectionMethod.USER_CONFIRMED,
                "user_confirmed": True,
                "selected_style_pack_id": "najdi_demo_v1",
            }
        )
        gate = confirmation_gate(hejazi_match, forced, reference)
        assert not gate.passed
        assert any("not declared applicable" in r for r in gate.reasons)

    def test_confirming_non_recommended_pack_requires_override(self, dataset, pack):
        reference, _ = pack
        no_match = recommend_character(dataset, LocationPoint(latitude=20.0, longitude=50.0))
        selection = recommend_style(no_match, None)
        with pytest.raises(SpdInputError, match="use override_selection"):
            confirm_selection(selection, reference)

    def test_missing_inputs_block_gate(self, pack):
        reference, _ = pack
        gate = confirmation_gate(None, None, reference)
        assert not gate.passed
        assert any("lookup has not completed" in r for r in gate.reasons)
        assert any("no style pack selected" in r for r in gate.reasons)


@pytest.fixture(scope="module")
def plot_id():
    model, _ = build_plot_model(REFERENCE_CORNERS, standard_edges(), 15.0, (24.65, 46.71))
    return model.plot_id


class TestArtifacts:
    def test_artifacts_carry_unconditional_disclaimer(self, dataset, match, pack, plot_id):
        reference, data = pack
        zone = dataset.zone_by_id(match.selected_zone_id)
        selection = confirm_selection(recommend_style(match, zone.style_pack_id), reference)
        gate = confirmation_gate(match, selection, reference)
        for artifact in (
            character_match_report(match, plot_id),
            style_selection_report(selection, gate, plot_id),
            style_pack_snapshot(reference, data),
        ):
            assert artifact["disclaimer"] == DISCLAIMER

    def test_artifacts_link_to_plot_id(self, match, plot_id):
        report = character_match_report(match, plot_id)
        assert report["plot_id"] == plot_id == "plot-20x30-street1"
        assert report["character_match"]["demo_statement"].startswith(
            "Demo geographic classification"
        )

    def test_artifact_json_round_trip_and_determinism(self, match, plot_id, tmp_path):
        report = character_match_report(match, plot_id)
        p1 = write_plot_report(tmp_path / "a.json", report)
        p2 = write_plot_report(tmp_path / "b.json", report)
        assert p1.read_text(encoding="utf-8") == p2.read_text(encoding="utf-8")
        assert json.loads(p1.read_text(encoding="utf-8")) == report
