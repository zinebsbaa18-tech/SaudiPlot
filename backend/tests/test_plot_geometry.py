"""Tests for plot ingest, validation, and metric geometry (M1)."""

import pytest

from saudi_plot_design.model import EdgeClass, SpdInputError
from saudi_plot_design.plot.geometry import (
    build_plot_model,
    corners_from_dimensions,
    enforce_reference_plot,
    load_corners_csv,
    validate_polygon,
)
from tests.conftest import REFERENCE_CORNERS, SAMPLE_CSV, standard_edges


class TestCsvLoading:
    def test_sample_csv_loads_reference_corners(self):
        assert load_corners_csv(SAMPLE_CSV) == REFERENCE_CORNERS

    def test_missing_file(self):
        with pytest.raises(SpdInputError, match="not found"):
            load_corners_csv("no_such_plot.csv")

    def test_wrong_header(self, tmp_path):
        p = tmp_path / "bad.csv"
        p.write_text("x,y\n0,0\n20,0\n20,30\n0,30\n")
        with pytest.raises(SpdInputError, match="header must be exactly 'id,x_m,y_m'"):
            load_corners_csv(p)

    def test_non_numeric_coordinates(self, tmp_path):
        p = tmp_path / "bad.csv"
        p.write_text("id,x_m,y_m\n1,zero,0\n2,20,0\n3,20,30\n4,0,30\n")
        with pytest.raises(SpdInputError, match="row 2.*numeric"):
            load_corners_csv(p)

    def test_non_sequential_ids(self, tmp_path):
        p = tmp_path / "bad.csv"
        p.write_text("id,x_m,y_m\n1,0,0\n3,20,0\n4,20,30\n5,0,30\n")
        with pytest.raises(SpdInputError, match="sequential"):
            load_corners_csv(p)

    def test_explicit_closure_row_is_accepted(self, tmp_path):
        p = tmp_path / "closed.csv"
        p.write_text("id,x_m,y_m\n1,0,0\n2,20,0\n3,20,30\n4,0,30\n5,0,0\n")
        assert load_corners_csv(p) == REFERENCE_CORNERS


class TestPolygonValidation:
    def test_valid_rectangle_metrics(self):
        metrics = validate_polygon(REFERENCE_CORNERS)
        assert metrics.area_m2 == pytest.approx(600.0)
        assert metrics.perimeter_m == pytest.approx(100.0)
        assert metrics.centroid == pytest.approx((10.0, 15.0))
        assert metrics.edge_lengths_m == pytest.approx((20.0, 30.0, 20.0, 30.0))

    def test_reversed_point_order_rejected(self):
        with pytest.raises(SpdInputError, match="counterclockwise"):
            validate_polygon(tuple(reversed(REFERENCE_CORNERS)))

    def test_duplicate_point_rejected(self):
        corners = ((0.0, 0.0), (20.0, 0.0), (20.0, 0.0), (20.0, 30.0), (0.0, 30.0))
        with pytest.raises(SpdInputError, match="duplicate corner"):
            validate_polygon(corners)

    @pytest.mark.parametrize(
        "bowtie",
        [
            # Asymmetric: lobes differ, shoelace sum nonzero.
            ((0.0, 0.0), (20.0, 0.0), (20.0, 30.0), (10.0, -5.0)),
            # Symmetric: lobes cancel to a zero shoelace sum - must still be
            # diagnosed as self-intersection, not as collinear zero area.
            ((0.0, 0.0), (20.0, 30.0), (20.0, 0.0), (0.0, 30.0)),
        ],
    )
    def test_self_intersection_rejected(self, bowtie):
        with pytest.raises(SpdInputError, match="self-intersecting"):
            validate_polygon(bowtie)

    @pytest.mark.parametrize("count", [3, 7])
    def test_invalid_point_count_rejected(self, count):
        if count == 3:
            corners = ((0.0, 0.0), (20.0, 0.0), (10.0, 30.0))
        else:
            corners = tuple((float(i), float(i % 2)) for i in range(7))
        with pytest.raises(SpdInputError, match="4-6 unique corners"):
            validate_polygon(corners)

    def test_zero_area_rejected(self):
        collinear = ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0))
        with pytest.raises(SpdInputError, match="zero area"):
            validate_polygon(collinear)

    def test_implausibly_small_area_rejected(self):
        tiny = ((0.0, 0.0), (2.0, 0.0), (2.0, 3.0), (0.0, 3.0))
        with pytest.raises(SpdInputError, match="plausible residential range"):
            validate_polygon(tiny)

    def test_implausibly_large_area_rejected(self):
        huge = ((0.0, 0.0), (200.0, 0.0), (200.0, 300.0), (0.0, 300.0))
        with pytest.raises(SpdInputError, match="plausible residential range"):
            validate_polygon(huge)

    def test_five_point_polygon_passes_structural_validation(self):
        pentagon = ((0.0, 0.0), (20.0, 0.0), (20.0, 25.0), (10.0, 32.0), (0.0, 25.0))
        metrics = validate_polygon(pentagon)
        assert metrics.area_m2 > 0
        assert len(metrics.edge_lengths_m) == 5


class TestReferenceGate:
    def test_reference_plot_passes(self):
        enforce_reference_plot(REFERENCE_CORNERS)

    def test_wrong_size_rejected(self):
        with pytest.raises(SpdInputError, match="20 m x 30 m reference plot"):
            enforce_reference_plot(corners_from_dimensions(10.0, 30.0))

    def test_five_point_plot_rejected_at_gate(self):
        pentagon = ((0.0, 0.0), (20.0, 0.0), (20.0, 25.0), (10.0, 32.0), (0.0, 25.0))
        with pytest.raises(SpdInputError, match="rectangular"):
            enforce_reference_plot(pentagon)

    def test_skewed_parallelogram_rejected(self):
        skewed = ((0.0, 0.0), (20.0, 0.0), (22.0, 30.0), (2.0, 30.0))
        with pytest.raises(SpdInputError, match="angle"):
            enforce_reference_plot(skewed)


class TestBuildPlotModel:
    def test_valid_model(self):
        model, metrics = build_plot_model(
            REFERENCE_CORNERS, standard_edges(), 15.0, location=(24.65, 46.71)
        )
        assert model.street_edge_index == 0
        assert model.street_width_m == 15.0
        assert metrics.area_m2 == pytest.approx(600.0)

    def test_missing_edge_classification(self):
        with pytest.raises(SpdInputError, match="4 edges but 3 classes"):
            build_plot_model(
                REFERENCE_CORNERS,
                (EdgeClass.STREET, EdgeClass.NEIGHBOR, EdgeClass.NEIGHBOR),
                15.0,
            )

    def test_street_on_30m_edge_rejected(self):
        edges = (EdgeClass.NEIGHBOR, EdgeClass.STREET, EdgeClass.NEIGHBOR, EdgeClass.NEIGHBOR)
        with pytest.raises(SpdInputError, match="street edge must be a 20 m frontage"):
            build_plot_model(REFERENCE_CORNERS, edges, 15.0)

    def test_invalid_latitude_rejected(self):
        with pytest.raises(SpdInputError, match="latitude"):
            build_plot_model(REFERENCE_CORNERS, standard_edges(), 15.0, location=(100.0, 46.71))

    @pytest.mark.parametrize("location", [(float("nan"), 46.71), (24.65, float("nan"))])
    def test_nan_location_rejected(self, location):
        with pytest.raises(SpdInputError, match="finite"):
            build_plot_model(REFERENCE_CORNERS, standard_edges(), 15.0, location=location)

    def test_nan_corner_rejected(self):
        corners = ((0.0, 0.0), (float("nan"), 0.0), (20.0, 30.0), (0.0, 30.0))
        with pytest.raises(SpdInputError, match="finite"):
            validate_polygon(corners)
