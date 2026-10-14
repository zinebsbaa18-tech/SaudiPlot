"""Character-zone dataset loading and point-in-polygon lookup (M3).

Deterministic, local, provenance-aware. Rules (SAUDI_CHARACTER_ENGINE.md):

- MVP loads only demo-provenance datasets; any file claiming verified or
  official status is rejected outright (GEOSPATIAL_DATA_PROVENANCE.md rule 2).
- Invalid geometries reject the dataset - untrusted data is never silently
  repaired.
- Overlapping zones are never silently chosen: unique priorities resolve with
  a warning, otherwise the match returns all candidates and requires user
  selection.
- Boundary/near-boundary points reduce confidence and warn.
- No inference of any kind: point-in-polygon lookup only.

Confidence model (transparent, rule-based; see models.py constants):
inside & clear of boundary -> demo_normal (0.8); near boundary or
priority-resolved overlap -> demo_reduced (0.6); exactly on boundary or
unresolved overlap -> demo_low (0.4); no match -> unresolved (None).
"""

from __future__ import annotations

import json
from importlib.resources import as_file, files
from pathlib import Path

from pydantic import ValidationError
from shapely.geometry import Point, shape
from shapely.validation import explain_validity

from saudi_plot_design.character.models import (
    CONFIDENCE_LOW,
    CONFIDENCE_NORMAL,
    CONFIDENCE_REDUCED,
    ArchitecturalCharacterZone,
    CharacterMatch,
    DatasetMetadata,
    LocationPoint,
    MatchMethod,
)
from saudi_plot_design.model import SpdInputError
from saudi_plot_design.plot.geometry import validate_location

# Approximate meters per degree of latitude (and of longitude at Saudi
# latitudes within ~10%): used ONLY for advisory boundary-distance warnings.
_METERS_PER_DEGREE_APPROX = 111_000.0

NEAR_BOUNDARY_TOLERANCE_M = 250.0  # configurable advisory tolerance

_FORBIDDEN_STATUS_TOKENS = ("verified", "official")


class ZoneDataset:
    """A validated demo zone dataset: metadata + zones with shapely geometry."""

    def __init__(
        self,
        metadata: DatasetMetadata,
        zones: tuple[ArchitecturalCharacterZone, ...],
        shapes: dict[str, object],
    ) -> None:
        self.metadata = metadata
        self.zones = zones
        self._shapes = shapes  # zone_id -> shapely polygon

    def shape_of(self, zone_id: str):
        return self._shapes[zone_id]

    def zone_by_id(self, zone_id: str) -> ArchitecturalCharacterZone:
        return next(z for z in self.zones if z.zone_id == zone_id)


def default_dataset_dir() -> Path:
    resource = files("saudi_plot_design").joinpath("data/demo/architectural_character_zones")
    with as_file(resource) as path:
        return Path(path)


def load_zone_dataset(directory: str | Path | None = None) -> ZoneDataset:
    directory = Path(directory) if directory is not None else default_dataset_dir()
    metadata = _load_metadata(directory / "metadata.json")
    zones, shapes = _load_zones(directory / "zones.geojson", metadata)
    return ZoneDataset(metadata, zones, shapes)


def _reject_official_claims(context: str, *values: str) -> None:
    for value in values:
        # Denials ("NOT OFFICIAL", "unofficial", "requires verification") are
        # the point of demo labeling - strip them before scanning so only
        # positive claims trip the guard.
        lowered = value.lower()
        for negation in ("not official", "not verified", "unofficial", "non-official"):
            lowered = lowered.replace(negation, "")
        for token in _FORBIDDEN_STATUS_TOKENS:
            if token in lowered:
                raise SpdInputError(
                    f"{context} claims '{token}' status - the MVP loads only demo data; "
                    f"verified-data activation is NOT NOW and needs a trusted approval "
                    f"mechanism (GEOSPATIAL_DATA_PROVENANCE.md)"
                )


def _load_json(path: Path, what: str) -> dict:
    if not path.is_file():
        raise SpdInputError(f"{what} not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpdInputError(f"{what} is not valid JSON: {path} ({exc})") from None
    if not isinstance(raw, dict):
        raise SpdInputError(f"{what} must be a JSON object, got {type(raw).__name__}: {path}")
    return raw


def _load_metadata(path: Path) -> DatasetMetadata:
    raw = _load_json(path, "zone dataset metadata")
    try:
        metadata = DatasetMetadata.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(loc) for loc in first["loc"]) or "<root>"
        raise SpdInputError(
            f"zone dataset metadata rejected at '{field}': {first['msg']}"
        ) from None
    if metadata.provenance_level != "demo":
        _reject_official_claims("zone dataset metadata provenance", metadata.provenance_level)
        raise SpdInputError(
            f"zone dataset metadata provenance_level must be 'demo', got "
            f"'{metadata.provenance_level}'"
        )
    _reject_official_claims("zone dataset metadata status", metadata.status)
    if metadata.crs.upper() not in ("EPSG:4326", "CRS84", "OGC:CRS84"):
        raise SpdInputError(f"zone dataset CRS must be EPSG:4326/CRS84, got '{metadata.crs}'")
    return metadata


def _load_zones(
    path: Path, metadata: DatasetMetadata
) -> tuple[tuple[ArchitecturalCharacterZone, ...], dict[str, object]]:
    raw = _load_json(path, "zone dataset")
    if raw.get("type") != "FeatureCollection":
        raise SpdInputError(f"zone dataset must be a GeoJSON FeatureCollection: {path}")
    prov = raw.get("x_provenance")
    if not isinstance(prov, dict) or "level" not in prov:
        raise SpdInputError(f"zone dataset is missing the x_provenance block: {path}")
    if prov["level"] != "demo":
        _reject_official_claims("zone dataset x_provenance", str(prov["level"]))
        raise SpdInputError(f"zone dataset provenance level must be 'demo', got '{prov['level']}'")

    features = raw.get("features")
    if not isinstance(features, list):
        raise SpdInputError(f"zone dataset 'features' must be a list: {path}")

    zones: list[ArchitecturalCharacterZone] = []
    shapes: dict[str, object] = {}
    for i, feature in enumerate(features):
        if not isinstance(feature, dict):
            raise SpdInputError(f"zone feature {i} must be a JSON object")
        props = feature.get("properties")
        if not isinstance(props, dict):
            raise SpdInputError(f"zone feature {i} has no properties object")
        zone_id = props.get("zone_id")
        if not zone_id:
            raise SpdInputError(f"zone feature {i} has no zone_id")
        if zone_id in shapes:
            raise SpdInputError(f"duplicate zone_id '{zone_id}' in zone dataset")
        if props.get("provenance") != "demo":
            _reject_official_claims(
                f"zone '{zone_id}' provenance", str(props.get("provenance", ""))
            )
            raise SpdInputError(f"zone '{zone_id}' is missing 'provenance': 'demo'")
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
            kind = geometry.get("type") if isinstance(geometry, dict) else type(geometry).__name__
            raise SpdInputError(f"zone '{zone_id}' geometry must be a Polygon, got '{kind}'")
        try:
            polygon = shape(geometry)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise SpdInputError(f"zone '{zone_id}' geometry is malformed: {exc}") from None
        if not polygon.is_valid:
            # Untrusted data is never silently repaired (no buffer(0) tricks).
            raise SpdInputError(
                f"zone '{zone_id}' has invalid geometry: {explain_validity(polygon)}"
            )
        priority = props.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise SpdInputError(f"zone '{zone_id}' needs an integer priority")
        zones.append(
            ArchitecturalCharacterZone(
                zone_id=zone_id,
                name_ar=props.get("name_ar", ""),
                name_en=props.get("name_en", ""),
                style_pack_id=props.get("style_pack_id"),
                geometry=geometry,
                priority=priority,
                dataset_id=metadata.dataset_id,
                dataset_version=metadata.version,
                source_status=metadata.status,
                effective_date=props.get("effective_date"),
                known_limitations=tuple(props.get("known_limitations", ())),
            )
        )
        shapes[zone_id] = polygon
    if not zones:
        raise SpdInputError(f"zone dataset contains no zones: {path}")
    return tuple(zones), shapes


def recommend_character(
    dataset: ZoneDataset,
    location: LocationPoint,
    *,
    near_boundary_tolerance_m: float = NEAR_BOUNDARY_TOLERANCE_M,
) -> CharacterMatch:
    """Deterministic point-in-polygon lookup producing a CharacterMatch."""
    validate_location((location.latitude, location.longitude))
    point = Point(location.longitude, location.latitude)  # GeoJSON axis order

    candidates = [z for z in dataset.zones if dataset.shape_of(z.zone_id).covers(point)]
    warnings: list[str] = []

    if not candidates:
        return CharacterMatch(
            point=location,
            matched_zone_ids=(),
            selected_zone_id=None,
            match_method=MatchMethod.NO_MATCH,
            confidence_level="unresolved",
            confidence_value=None,
            dataset_id=dataset.metadata.dataset_id,
            dataset_version=dataset.metadata.version,
            source_status=dataset.metadata.status,
            warnings=("no demo zone contains this point; manual style selection required",),
        )

    matched_ids = tuple(sorted(z.zone_id for z in candidates))
    overlap = len(candidates) > 1
    if overlap:
        warnings.append(
            f"point lies in {len(candidates)} overlapping demo zones: {', '.join(matched_ids)}"
        )
        # Never silently choose: resolve only when the candidates' priorities
        # single out one zone (lower value = higher precedence); otherwise
        # return all candidates and require user selection.
        best_priority = min(z.priority for z in candidates)
        best = [z for z in candidates if z.priority == best_priority]
        if len(best) > 1:
            level, value = CONFIDENCE_LOW
            return CharacterMatch(
                point=location,
                matched_zone_ids=matched_ids,
                selected_zone_id=None,
                match_method=MatchMethod.POINT_IN_POLYGON,
                confidence_level=level,
                confidence_value=value,
                overlap_detected=True,
                dataset_id=dataset.metadata.dataset_id,
                dataset_version=dataset.metadata.version,
                source_status=dataset.metadata.status,
                warnings=tuple(
                    warnings
                    + [
                        f"overlapping zones share priority {best_priority}; no automatic "
                        f"recommendation - user selection required"
                    ]
                ),
            )
        selected = best[0]
        warnings.append(
            f"overlap resolved to '{selected.zone_id}' by documented unique priority; "
            f"confirm explicitly"
        )
    else:
        selected = candidates[0]

    selected_shape = dataset.shape_of(selected.zone_id)
    distance_deg = point.distance(selected_shape.boundary)
    boundary_distance_m = round(distance_deg * _METERS_PER_DEGREE_APPROX, 1)
    on_boundary = distance_deg == 0.0
    near_boundary = not on_boundary and boundary_distance_m <= near_boundary_tolerance_m

    if on_boundary:
        level, value = CONFIDENCE_LOW
        method = MatchMethod.POINT_IN_POLYGON_BOUNDARY
        warnings.append(
            f"point lies exactly on the boundary of '{selected.zone_id}'; "
            f"explicit confirmation required"
        )
    elif near_boundary or overlap:
        level, value = CONFIDENCE_REDUCED
        method = MatchMethod.POINT_IN_POLYGON
        if near_boundary:
            warnings.append(
                f"point is ~{boundary_distance_m:g} m from the zone boundary "
                f"(tolerance {near_boundary_tolerance_m:g} m, approximate conversion); "
                f"confirm explicitly"
            )
    else:
        level, value = CONFIDENCE_NORMAL
        method = MatchMethod.POINT_IN_POLYGON

    return CharacterMatch(
        point=location,
        matched_zone_ids=matched_ids,
        selected_zone_id=selected.zone_id,
        match_method=method,
        confidence_level=level,
        confidence_value=value,
        boundary_distance_m=boundary_distance_m,
        overlap_detected=overlap,
        near_boundary=near_boundary or on_boundary,
        dataset_id=dataset.metadata.dataset_id,
        dataset_version=dataset.metadata.version,
        source_status=dataset.metadata.status,
        warnings=tuple(warnings),
    )
