"""Tests for the M5 A3 PDF export (reopen validation via pypdf)."""

import pytest
from pypdf import PdfReader

from saudi_plot_design.elevation.facade_selection import select_primary_facade
from saudi_plot_design.elevation.front import generate_front_facade
from saudi_plot_design.export.pdf import PaperTransform, _write_pdf
from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
from tests.conftest import reference_pipeline

ARABIC_LOGICAL = "الطابع النجدي التجريبي"
ARABIC_REVERSED = "يبيرجتلا يدجنلا عباطلا"


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


def render(state, path):
    return _write_pdf(
        path,
        state["plot"],
        state["envelope"],
        state["rules"],
        state["concept"],
        state["match"],
        state["style_selection"],
        state["pack_ref"],
        state["pack_data"],
        state["selection"],
        state["facade"],
    )


@pytest.fixture(scope="module")
def pdf_path(state, tmp_path_factory):
    return render(state, tmp_path_factory.mktemp("pdf") / "reference.pdf")


@pytest.fixture(scope="module")
def reader(pdf_path):
    return PdfReader(pdf_path)


@pytest.fixture(scope="module")
def all_text(reader):
    return [page.extract_text() for page in reader.pages]


class TestPdf:
    def test_generates(self, pdf_path):
        assert pdf_path.is_file() and pdf_path.stat().st_size > 1000

    def test_exactly_two_pages(self, reader):
        assert len(reader.pages) == 2

    def test_a3_landscape(self, reader):
        for page in reader.pages:
            assert float(page.mediabox.width) == pytest.approx(1190.55, abs=0.5)
            assert float(page.mediabox.height) == pytest.approx(841.89, abs=0.5)

    def test_contains_project_id_and_fingerprints(self, state, all_text):
        joined = "\n".join(all_text)
        assert state["plot"].plot_id in joined
        assert state["plot"].fingerprint[:8] in joined
        assert state["concept"].fingerprint[:8] in joined

    def test_arabic_logical_in_metadata(self, state, reader):
        keywords = reader.metadata.get("/Keywords", "")
        assert ARABIC_LOGICAL in keywords
        assert ARABIC_REVERSED not in keywords
        assert state["pack_ref"].style_pack_id in keywords

    def test_metadata_declares_demo(self, reader):
        assert "DEMO" in reader.metadata.get("/Subject", "")
        assert "saudi-plot-design" in reader.metadata.get("/Creator", "")

    def test_disclaimer_on_both_sheets(self, all_text):
        for text in all_text:
            assert "DEMO DATA" in text
            assert "not official Saudi regulations" in text

    def test_sheet1_site_plan_content(self, all_text):
        sheet1 = all_text[0]
        for needle in (
            "Site and Floor Plan",
            "room schedule",
            "Men's Majlis",
            "area summary",
            "demo setback assumptions",
            "DEMO-SETBACK-01",
            "north unknown",
            "20.00 m plot width",
            "edge 1: street",
        ):
            assert needle in sheet1, needle

    def test_sheet2_elevation_content(self, all_text, state):
        sheet2 = all_text[1]
        for needle in (
            "Front Elevation",
            "architectural character",
            "DEMO-ZONE-NAJDI-01",
            "najdi_demo_v1",
            "material / color legend",
            "source-opening traceability",
            "d_main",
            "known limitations",
            "main entrance",
            "facade length",
        ):
            assert needle in sheet2, needle

    def test_deterministic_bytes(self, state, tmp_path):
        a = render(state, tmp_path / "a.pdf").read_bytes()
        b = render(state, tmp_path / "b.pdf").read_bytes()
        assert a == b

    def test_no_raster_images(self, reader):
        for page in reader.pages:
            resources = page.get("/Resources", {})
            xobjects = resources.get("/XObject", {}) if resources else {}
            assert not xobjects  # no image XObjects at all


class TestPaperTransform:
    def test_known_mapping(self):
        from reportlab.lib.units import mm

        t = PaperTransform(45.0, 60.0, 5.0)  # 1:200
        x, y = t.pt(0.0, 0.0)
        assert x == pytest.approx(45.0 * mm)
        assert y == pytest.approx(60.0 * mm)
        x, y = t.pt(20.0, 30.0)
        assert x == pytest.approx((45.0 + 100.0) * mm)
        assert y == pytest.approx((60.0 + 150.0) * mm)
        assert t.length(2.0) == pytest.approx(10.0 * mm)
