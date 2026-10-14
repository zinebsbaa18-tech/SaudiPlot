"""Tests for the Saudi Geographic Character Engine (M3)."""

import json

import pytest

from saudi_plot_design.character.engine import (
    NEAR_BOUNDARY_TOLERANCE_M,
    load_zone_dataset,
    recommend_character,
)
from saudi_plot_design.character.models import LocationPoint, MatchMethod
from saudi_plot_design.model import SpdInputError

PILOT = LocationPoint(latitude=24.65, longitude=46.71)


def square(lon0, lat0, lon1, lat1):
    return {
        "type": "Polygon",
        "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]],
    }


def make_metadata(**overrides):
    base = {
        "dataset_id": "DEMO-TEST-ZONES",
        "version": "0.1.0",
        "created": "2026-07-13",
        "publisher": "test (synthetic)",
        "license_note": "test only",
        "coverage": "synthetic test polygons",
        "crs": "EPSG:4326",
        "status": "DEMO SYNTHETIC - NOT OFFICIAL - REQUIRES VERIFICATION",
        "provenance_level": "demo",
        "limitations": ["synthetic"],
    }
    base.update(overrides)
    return base


def make_feature(zone_id, geometry, priority=1, style_pack_id="najdi_demo_v1", provenance="demo"):
    props = {
        "zone_id": zone_id,
        "name_ar": "تجريبي",
        "name_en": f"{zone_id} (demo)",
        "style_pack_id": style_pack_id,
        "priority": priority,
        "provenance": provenance,
        "known_limitations": ["synthetic"],
    }
    return {"type": "Feature", "properties": props, "geometry": geometry}


def write_dataset(tmp_path, features, metadata=None, provenance_level="demo"):
    d = tmp_path / "zones_ds"
    d.mkdir(exist_ok=True)
    (d / "metadata.json").write_text(json.dumps(metadata or make_metadata()), encoding="utf-8")
    collection = {
        "type": "FeatureCollection",
        "x_provenance": {"level": provenance_level, "statement": "synthetic test"},
        "features": features,
    }
    (d / "zones.geojson").write_text(json.dumps(collection), encoding="utf-8")
    return d


NAJDI_BOX = square(46.0, 24.0, 47.5, 25.4)


class TestShippedDataset:
    def test_shipped_demo_dataset_loads(self):
        ds = load_zone_dataset()
        assert ds.metadata.dataset_id == "DEMO-CHAR-ZONES"
        assert [z.zone_id for z in ds.zones] == [
            "DEMO-ZONE-NAJDI-01",
            "DEMO-ZONE-HEJAZI-01",
            "DEMO-ZONE-ASIRI-01",
        ]
        assert all("NOT OFFICIAL" in z.source_status for z in ds.zones)

    def test_reference_pilot_recommends_demo_najdi(self):
        ds = load_zone_dataset()
        match = recommend_character(ds, PILOT)
        assert match.selected_zone_id == "DEMO-ZONE-NAJDI-01"
        assert match.match_method is MatchMethod.POINT_IN_POLYGON
        assert match.confidence_level == "demo_normal"
        assert match.confidence_value == 0.8
        assert not match.overlap_detected and not match.near_boundary
        assert match.demo_statement.startswith("Demo geographic classification")
        zone = ds.zone_by_id(match.selected_zone_id)
        assert zone.style_pack_id == "najdi_demo_v1"


class TestLookupCases:
    def test_point_strictly_inside_one_zone(self, tmp_path):
        ds = load_zone_dataset(write_dataset(tmp_path, [make_feature("Z1", NAJDI_BOX)]))
        match = recommend_character(ds, PILOT)
        assert match.selected_zone_id == "Z1"
        assert match.confidence_level == "demo_normal"

    def test_point_outside_all_zones_unresolved(self):
        ds = load_zone_dataset()
        match = recommend_character(ds, LocationPoint(latitude=20.0, longitude=50.0))
        assert match.match_method is MatchMethod.NO_MATCH
        assert match.selected_zone_id is None
        assert match.matched_zone_ids == ()
        assert match.confidence_level == "unresolved"
        assert match.confidence_value is None
        assert match.warnings

    def test_point_exactly_on_boundary(self, tmp_path):
        ds = load_zone_dataset(write_dataset(tmp_path, [make_feature("Z1", NAJDI_BOX)]))
        match = recommend_character(ds, LocationPoint(latitude=24.0, longitude=46.5))
        assert match.match_method is MatchMethod.POINT_IN_POLYGON_BOUNDARY
        assert match.confidence_level == "demo_low"
        assert match.near_boundary
        assert match.boundary_distance_m == 0.0
        assert any("boundary" in w for w in match.warnings)

    def test_point_near_boundary_reduced_confidence(self, tmp_path):
        ds = load_zone_dataset(write_dataset(tmp_path, [make_feature("Z1", NAJDI_BOX)]))
        # ~111 m inside the southern edge (0.001 deg), below the 250 m tolerance.
        match = recommend_character(ds, LocationPoint(latitude=24.001, longitude=46.7))
        assert match.confidence_level == "demo_reduced"
        assert match.near_boundary
        assert 0 < match.boundary_distance_m <= NEAR_BOUNDARY_TOLERANCE_M
        assert any("tolerance" in w for w in match.warnings)

    def test_overlap_with_unique_priorities(self, tmp_path):
        overlapping = square(46.5, 24.4, 47.0, 25.0)
        ds = load_zone_dataset(
            write_dataset(
                tmp_path,
                [
                    make_feature("Z-LOW", NAJDI_BOX, priority=2),
                    make_feature("Z-HIGH", overlapping, priority=1, style_pack_id=None),
                ],
            )
        )
        match = recommend_character(ds, PILOT)
        assert match.overlap_detected
        assert match.matched_zone_ids == ("Z-HIGH", "Z-LOW")
        assert match.selected_zone_id == "Z-HIGH"  # lower value = higher precedence
        assert match.confidence_level == "demo_reduced"
        assert any("resolved" in w for w in match.warnings)

    def test_overlap_with_equal_priorities_requires_user_selection(self, tmp_path):
        overlapping = square(46.5, 24.4, 47.0, 25.0)
        ds = load_zone_dataset(
            write_dataset(
                tmp_path,
                [
                    make_feature("Z-A", NAJDI_BOX, priority=1),
                    make_feature("Z-B", overlapping, priority=1),
                ],
            )
        )
        match = recommend_character(ds, PILOT)
        assert match.overlap_detected
        assert match.selected_zone_id is None
        assert match.matched_zone_ids == ("Z-A", "Z-B")
        assert match.confidence_level == "demo_low"
        assert any("user selection required" in w for w in match.warnings)


class TestDatasetRejection:
    def test_invalid_geojson_rejected(self, tmp_path):
        d = tmp_path / "zones_ds"
        d.mkdir()
        (d / "metadata.json").write_text(json.dumps(make_metadata()), encoding="utf-8")
        (d / "zones.geojson").write_text("{not json", encoding="utf-8")
        with pytest.raises(SpdInputError, match="not valid JSON"):
            load_zone_dataset(d)

    def test_self_intersecting_zone_rejected(self, tmp_path):
        bowtie = {
            "type": "Polygon",
            "coordinates": [[[46.0, 24.0], [47.0, 25.0], [47.0, 24.0], [46.0, 25.0], [46.0, 24.0]]],
        }
        d = write_dataset(tmp_path, [make_feature("Z1", bowtie)])
        with pytest.raises(SpdInputError, match="invalid geometry"):
            load_zone_dataset(d)

    def test_missing_metadata_rejected(self, tmp_path):
        d = tmp_path / "zones_ds"
        d.mkdir()
        collection = {"type": "FeatureCollection", "features": []}
        (d / "zones.geojson").write_text(json.dumps(collection), encoding="utf-8")
        with pytest.raises(SpdInputError, match="metadata not found"):
            load_zone_dataset(d)

    def test_missing_feature_provenance_rejected(self, tmp_path):
        feature = make_feature("Z1", NAJDI_BOX)
        del feature["properties"]["provenance"]
        d = write_dataset(tmp_path, [feature])
        with pytest.raises(SpdInputError, match="provenance"):
            load_zone_dataset(d)

    def test_missing_collection_provenance_rejected(self, tmp_path):
        d = tmp_path / "zones_ds"
        d.mkdir()
        (d / "metadata.json").write_text(json.dumps(make_metadata()), encoding="utf-8")
        collection = {"type": "FeatureCollection", "features": [make_feature("Z1", NAJDI_BOX)]}
        (d / "zones.geojson").write_text(json.dumps(collection), encoding="utf-8")
        with pytest.raises(SpdInputError, match="x_provenance"):
            load_zone_dataset(d)

    def test_dataset_claiming_official_status_rejected(self, tmp_path):
        metadata = make_metadata(status="Official architectural zones of Riyadh")
        d = write_dataset(tmp_path, [make_feature("Z1", NAJDI_BOX)], metadata=metadata)
        with pytest.raises(SpdInputError, match="official"):
            load_zone_dataset(d)

    def test_dataset_claiming_verified_provenance_rejected(self, tmp_path):
        metadata = make_metadata(provenance_level="verified")
        d = write_dataset(tmp_path, [make_feature("Z1", NAJDI_BOX)], metadata=metadata)
        with pytest.raises(SpdInputError, match="verified"):
            load_zone_dataset(d)

    def test_feature_claiming_verified_provenance_rejected(self, tmp_path):
        d = write_dataset(tmp_path, [make_feature("Z1", NAJDI_BOX, provenance="verified")])
        with pytest.raises(SpdInputError, match="verified"):
            load_zone_dataset(d)

    def test_duplicate_zone_id_rejected(self, tmp_path):
        d = write_dataset(
            tmp_path,
            [make_feature("Z1", NAJDI_BOX), make_feature("Z1", square(40, 20, 41, 21))],
        )
        with pytest.raises(SpdInputError, match="duplicate zone_id"):
            load_zone_dataset(d)

    def test_non_polygon_geometry_rejected(self, tmp_path):
        point_geom = {"type": "Point", "coordinates": [46.5, 24.5]}
        d = write_dataset(tmp_path, [make_feature("Z1", point_geom)])
        with pytest.raises(SpdInputError, match="must be a Polygon"):
            load_zone_dataset(d)

    def test_wrong_crs_rejected(self, tmp_path):
        metadata = make_metadata(crs="EPSG:3857")
        d = write_dataset(tmp_path, [make_feature("Z1", NAJDI_BOX)], metadata=metadata)
        with pytest.raises(SpdInputError, match="CRS"):
            load_zone_dataset(d)

    def test_missing_priority_rejected(self, tmp_path):
        feature = make_feature("Z1", NAJDI_BOX)
        del feature["properties"]["priority"]
        d = write_dataset(tmp_path, [feature])
        with pytest.raises(SpdInputError, match="priority"):
            load_zone_dataset(d)


class TestMalformedContainers:
    """Regression tests (Codex M3 P2): malformed containers must raise
    SpdInputError, never AttributeError/TypeError."""

    def test_root_array_rejected(self, tmp_path):
        d = tmp_path / "zones_ds"
        d.mkdir()
        (d / "metadata.json").write_text(json.dumps(make_metadata()), encoding="utf-8")
        (d / "zones.geojson").write_text("[]", encoding="utf-8")
        with pytest.raises(SpdInputError, match="must be a JSON object"):
            load_zone_dataset(d)

    def test_non_list_features_rejected(self, tmp_path):
        d = tmp_path / "zones_ds"
        d.mkdir()
        (d / "metadata.json").write_text(json.dumps(make_metadata()), encoding="utf-8")
        collection = {
            "type": "FeatureCollection",
            "x_provenance": {"level": "demo"},
            "features": "oops",
        }
        (d / "zones.geojson").write_text(json.dumps(collection), encoding="utf-8")
        with pytest.raises(SpdInputError, match="'features' must be a list"):
            load_zone_dataset(d)

    def test_non_dict_feature_rejected(self, tmp_path):
        d = write_dataset(tmp_path, ["not-a-feature"])
        with pytest.raises(SpdInputError, match="feature 0 must be a JSON object"):
            load_zone_dataset(d)

    def test_feature_without_properties_rejected(self, tmp_path):
        d = write_dataset(tmp_path, [{"type": "Feature", "geometry": NAJDI_BOX}])
        with pytest.raises(SpdInputError, match="no properties object"):
            load_zone_dataset(d)

    def test_non_dict_geometry_rejected(self, tmp_path):
        feature = make_feature("Z1", NAJDI_BOX)
        feature["geometry"] = "not-geometry"
        d = write_dataset(tmp_path, [feature])
        with pytest.raises(SpdInputError, match="must be a Polygon"):
            load_zone_dataset(d)

    def test_root_array_metadata_rejected(self, tmp_path):
        d = tmp_path / "zones_ds"
        d.mkdir()
        (d / "metadata.json").write_text("[1, 2]", encoding="utf-8")
        (d / "zones.geojson").write_text("{}", encoding="utf-8")
        with pytest.raises(SpdInputError, match="must be a JSON object"):
            load_zone_dataset(d)


class TestDeterminism:
    def test_same_input_identical_match_json(self):
        ds = load_zone_dataset()
        a = recommend_character(ds, PILOT).model_dump_json()
        b = recommend_character(load_zone_dataset(), PILOT).model_dump_json()
        assert a == b
