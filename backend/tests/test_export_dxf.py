"""Tests for the M5 layered DXF export (reopen + audit via ezdxf)."""

import ezdxf
import pytest

from saudi_plot_design.elevation.facade_selection import select_primary_facade
from saudi_plot_design.elevation.front import generate_front_facade
from saudi_plot_design.export.dxf import APPID, ELEVATION_OFFSET_X_M, FIXED_LAYERS, _write_dxf
from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
from tests.conftest import reference_pipeline


@pytest.fixture(scope="module")
def state():
    s = reference_pipeline()
    s["rules"] = load_default_setback_rules()
    s["envelope"] = compute_envelope(s["plot"], s["rules"])
    s["selection"] = select_primary_facade(s["plot"], s["concept"], 0, user_confirmed=True)
    s["facade"] = generate_front_facade(
        s["plot"],
        s["concept"],
        s["selection"],
        s["match"],
        s["style_selection"],
        s["pack_ref"],
        s["pack_data"],
    )
    return s


@pytest.fixture(scope="module")
def dxf_path(state, tmp_path_factory):
    return _write_dxf(
        tmp_path_factory.mktemp("dxf") / "reference.dxf",
        state["plot"],
        state["envelope"],
        state["rules"],
        state["concept"],
        state["match"],
        state["pack_ref"],
        state["selection"],
        state["facade"],
    )


@pytest.fixture(scope="module")
def doc(dxf_path):
    return ezdxf.readfile(dxf_path)


@pytest.fixture(scope="module")
def msp(doc):
    return doc.modelspace()


class TestDxf:
    def test_generates_and_reopens(self, dxf_path, doc):
        assert dxf_path.stat().st_size > 10_000
        assert doc.dxfversion == "AC1032"  # R2018

    def test_audit_clean(self, doc):
        auditor = doc.audit()
        assert not auditor.has_errors, [str(e) for e in auditor.errors]

    def test_units_meters(self, doc):
        assert doc.header["$INSUNITS"] == 6

    def test_every_required_layer_exists(self, doc):
        names = {layer.dxf.name for layer in doc.layers}
        missing = set(FIXED_LAYERS) - names
        assert not missing, missing

    def test_no_unexpected_layer(self, doc):
        # ezdxf mandates layer '0' and 'Defpoints' (dimension definition
        # points); everything else must be in the fixed documented set.
        names = {layer.dxf.name for layer in doc.layers}
        extra = names - set(FIXED_LAYERS) - {"0", "Defpoints"}
        assert not extra, extra

    def test_walls_map_to_correct_layers(self, msp, state):
        external = msp.query('LINE[layer=="WALLS_EXTERNAL"]')
        internal = msp.query('LINE[layer=="WALLS_INTERNAL"]')
        n_external = sum(1 for w in state["concept"].walls if w.is_external)
        n_internal = sum(1 for w in state["concept"].walls if not w.is_external)
        assert len(external) == n_external
        assert len(internal) == n_internal

    def test_doors_map_to_doors_layer(self, msp, state):
        assert len(msp.query('LINE[layer=="DOORS"]')) == len(state["concept"].doors)

    def test_windows_map_to_windows_layer(self, msp, state):
        assert len(msp.query('LINE[layer=="WINDOWS"]')) == len(state["concept"].windows)

    def test_facade_openings_map_to_elevation_layers(self, msp, state):
        doors = msp.query('LWPOLYLINE[layer=="ELEVATION_DOORS"]')
        windows = msp.query('LWPOLYLINE[layer=="ELEVATION_WINDOWS"]')
        facade = state["facade"]
        assert len(doors) == sum(1 for o in facade.facade_openings if o.opening_type == "door")
        assert len(windows) == sum(1 for o in facade.facade_openings if o.opening_type == "window")

    def test_decorative_elements_on_approved_layers(self, msp, state):
        approved = {
            "ELEVATION_WALL",
            "ELEVATION_PLINTH",
            "ELEVATION_PARAPET",
            "ELEVATION_SHADING",
            "ELEVATION_DECORATION",
            "ELEVATION_FENCE",
            "ELEVATION_GATE",
        }
        element_polylines = [
            e
            for e in msp.query("LWPOLYLINE")
            if e.dxf.layer.startswith("ELEVATION_")
            and e.dxf.layer not in ("ELEVATION_DOORS", "ELEVATION_WINDOWS")
        ]
        assert len(element_polylines) == len(state["facade"].facade_elements)
        for entity in element_polylines:
            assert entity.dxf.layer in approved

    def test_room_names_editable_text(self, msp, state):
        texts = {e.dxf.text for e in msp.query('TEXT[layer=="ROOM_NAMES"]')}
        for room in state["concept"].rooms:
            assert room.name in texts

    def test_room_areas_exported(self, msp, state):
        texts = {e.dxf.text for e in msp.query('TEXT[layer=="ROOM_AREAS"]')}
        for room in state["concept"].rooms:
            assert f"{room.area_m2:.1f} m2" in texts

    def test_traceability_xdata_and_text(self, msp, state):
        doors = msp.query('LINE[layer=="DOORS"]')
        xdata_values = set()
        for entity in doors:
            xdata_values.update(tag.value for tag in entity.get_xdata(APPID))
        for door in state["concept"].doors:
            assert door.id in xdata_values
        trace_texts = " ".join(e.dxf.text for e in msp.query('TEXT[layer=="TRACEABILITY"]'))
        assert state["plot"].fingerprint in trace_texts
        assert state["concept"].fingerprint in trace_texts

    def test_dimensions_are_real_dim_entities(self, msp):
        assert len(msp.query('DIMENSION[layer=="DIMENSIONS"]')) >= 3
        assert len(msp.query('DIMENSION[layer=="ELEVATION_DIMENSIONS"]')) >= 2

    def test_no_raster_entities(self, msp):
        assert len(msp.query("IMAGE")) == 0
        assert len(msp.query("IMAGEDEF")) == 0

    def test_plan_and_elevation_spatially_separated(self, msp, state):
        # Plan occupies x <= 20; elevation entities live beyond the offset.
        elevation_min_x = min(
            min(p[0] for p in e.get_points())
            for e in msp.query("LWPOLYLINE")
            if e.dxf.layer.startswith("ELEVATION_")
        )
        assert elevation_min_x >= ELEVATION_OFFSET_X_M - 2.0  # frames extend slightly left
        plan_max_x = max(
            max(p[0] for p in e.get_points())
            for e in msp.query("LWPOLYLINE")
            if not e.dxf.layer.startswith("ELEVATION_")
        )
        assert plan_max_x <= 25.0
        assert plan_max_x < elevation_min_x

    def test_arabic_present_in_title_block(self, msp):
        title_texts = " ".join(e.dxf.text for e in msp.query('TEXT[layer=="TITLE_BLOCK"]'))
        assert "الطابع النجدي التجريبي" in title_texts
        assert "يبيرجتلا يدجنلا عباطلا" not in title_texts

    def test_setback_rule_provenance_in_audit_block(self, msp, state):
        # Regression (Codex M5 P2): the audit block must identify the rule set.
        title_texts = " ".join(e.dxf.text for e in msp.query('TEXT[layer=="TITLE_BLOCK"]'))
        assert f"setback rule set {state['rules'].id} ({state['rules'].provenance})" in title_texts

    def test_disclaimer_layer(self, msp):
        texts = " ".join(e.dxf.text for e in msp.query('TEXT[layer=="DISCLAIMERS"]'))
        assert "DEMO DATA" in texts
