"""Arabic logical-Unicode-order regression tests across ALL serialized
artifacts (M5 closing requirement).

The correct string is stored in logical code-point order; terminals may
visually reorder RTL text, so these tests compare raw code points, never
rendering. The reversed string must not exist anywhere.
"""

import json

import pytest
from pypdf import PdfReader

from saudi_plot_design.elevation.facade_selection import select_primary_facade
from saudi_plot_design.elevation.front import generate_front_facade
from saudi_plot_design.export.pipeline import export_project
from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
from saudi_plot_design.styles.loader import default_styles_root
from tests.conftest import reference_pipeline

CORRECT = "الطابع النجدي التجريبي"
REVERSED = "يبيرجتلا يدجنلا عباطلا"

# The exact expected logical code-point sequence, spelled out so no editor,
# terminal, or bidi algorithm can silently alter what this test asserts.
CORRECT_CODEPOINTS = [
    0x627,
    0x644,
    0x637,
    0x627,
    0x628,
    0x639,  # الطابع
    0x20,
    0x627,
    0x644,
    0x646,
    0x62C,
    0x62F,
    0x64A,  # النجدي
    0x20,
    0x627,
    0x644,
    0x62A,
    0x62C,
    0x631,
    0x64A,
    0x628,
    0x64A,  # التجريبي
]


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    s = reference_pipeline()
    rules = load_default_setback_rules()
    envelope = compute_envelope(s["plot"], rules)
    selection = select_primary_facade(s["plot"], s["concept"], 0, user_confirmed=True)
    facade = generate_front_facade(
        s["plot"],
        s["concept"],
        selection,
        s["match"],
        s["style_selection"],
        s["pack_ref"],
        s["pack_data"],
    )
    out = tmp_path_factory.mktemp("arabic")
    export_project(
        out,
        plot=s["plot"],
        envelope=envelope,
        rules=rules,
        concept=s["concept"],
        match=s["match"],
        style_selection=s["style_selection"],
        pack_ref=s["pack_ref"],
        pack_data=s["pack_data"],
        selection=selection,
        facade=facade,
        run_id="arabic-check",
        generation_timestamp="2026-07-13T00:00:00Z",
    )
    return out


class TestArabicLogicalOrder:
    def test_correct_string_codepoints(self):
        assert [ord(ch) for ch in CORRECT] == CORRECT_CODEPOINTS
        assert CORRECT == "الطابع النجدي التجريبي"
        # Sanity: the reversed variant really is the code-point reversal.
        assert REVERSED == CORRECT[::-1]

    def test_style_pack_json_stores_logical_order(self):
        raw = (default_styles_root() / "najdi_demo_v1" / "style.json").read_text(encoding="utf-8")
        assert CORRECT in raw
        assert REVERSED not in raw
        assert json.loads(raw)["name_ar"] == CORRECT

    def test_run_json_stores_logical_order(self, exported):
        raw = (exported / "run.json").read_text(encoding="utf-8")
        assert REVERSED not in raw
        payload = json.loads(raw)
        assert payload["governed_data_provenance"]["style_pack"]["name_ar"] == CORRECT

    def test_export_manifest_has_no_reversed_string(self, exported):
        raw = (exported / "export_manifest.json").read_text(encoding="utf-8")
        assert REVERSED not in raw

    def test_pdf_metadata_stores_logical_order(self, exported):
        reader = PdfReader(exported / "saudi_plot_design_reference.pdf")
        keywords = reader.metadata.get("/Keywords", "")
        assert CORRECT in keywords
        assert REVERSED not in keywords
        for page in reader.pages:
            text = page.extract_text()
            assert REVERSED not in text

    def test_dxf_stores_logical_order(self, exported):
        raw = (exported / "saudi_plot_design_reference.dxf").read_text(encoding="utf-8")
        assert CORRECT in raw
        assert REVERSED not in raw

    def test_no_reversed_string_in_repository_sources(self):
        # The demo data and package sources must never contain the reversed
        # string (test files legitimately carry it as the negative fixture).
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "src"
        offenders = [
            p
            for p in root.rglob("*")
            if p.is_file()
            and p.suffix in (".py", ".json", ".geojson")
            and REVERSED in p.read_text(encoding="utf-8", errors="ignore")
        ]
        assert not offenders, offenders
