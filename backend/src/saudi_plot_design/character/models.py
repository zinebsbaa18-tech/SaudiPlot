"""Typed models for the character engine (M3).

Classification data only - no facade geometry. Every artifact built from
these models carries the unconditional DEMO disclaimer (output.py) and the
demo classification statement below.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

DEMO_CLASSIFICATION_STATEMENT = "Demo geographic classification — requires verification."

# Transparent rule-based confidence (documented in SAUDI_CHARACTER_ENGINE.md
# par.5): fixed demo labels with bounded numeric values. These describe the
# geometric quality of the demo lookup only - never official correctness.
CONFIDENCE_NORMAL = ("demo_normal", 0.8)
CONFIDENCE_REDUCED = ("demo_reduced", 0.6)
CONFIDENCE_LOW = ("demo_low", 0.4)


class SelectionMethod(str, Enum):
    AUTOMATIC_RECOMMENDATION = "automatic_recommendation"
    USER_CONFIRMED = "user_confirmed"
    MANUAL_OVERRIDE = "manual_override"
    UNRESOLVED = "unresolved"


class MatchMethod(str, Enum):
    POINT_IN_POLYGON = "point_in_polygon"
    POINT_IN_POLYGON_BOUNDARY = "point_in_polygon_boundary"
    NO_MATCH = "no_match"


class LocationPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    latitude: float
    longitude: float
    # Where the coordinate came from. Plot corners are local meters, so a
    # geographic centroid cannot be derived from them; the user-provided plot
    # location stands in for the centroid (documented assumption).
    source: str = "user_provided_plot_location"
    confidence: str = "user_provided"
    user_confirmed: bool = False


class ArchitecturalCharacterZone(BaseModel):
    model_config = ConfigDict(frozen=True)

    zone_id: str
    name_ar: str
    name_en: str
    style_pack_id: str | None  # None: zone has no installed pack in the MVP
    geometry: dict  # GeoJSON Polygon (validated at load; shapely used internally)
    priority: int  # lower value = higher precedence in overlap resolution
    dataset_id: str
    dataset_version: str
    source_status: str  # always a demo status in the MVP
    effective_date: str | None = None
    known_limitations: tuple[str, ...] = ()


class DatasetMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str
    version: str
    created: str
    publisher: str
    license_note: str
    coverage: str
    crs: str
    status: str
    provenance_level: str
    limitations: tuple[str, ...]


class CharacterMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    point: LocationPoint
    matched_zone_ids: tuple[str, ...]
    selected_zone_id: str | None  # None: no match, or overlap needs user choice
    match_method: MatchMethod
    confidence_level: str  # demo_normal | demo_reduced | demo_low | unresolved
    confidence_value: float | None  # None when unresolved
    boundary_distance_m: float | None = None  # approximate (deg x ~111 km)
    overlap_detected: bool = False
    near_boundary: bool = False
    dataset_id: str
    dataset_version: str
    source_status: str
    demo_statement: str = DEMO_CLASSIFICATION_STATEMENT
    warnings: tuple[str, ...] = ()


class StyleSelection(BaseModel):
    model_config = ConfigDict(frozen=True)

    recommended_style_pack_id: str | None
    selected_style_pack_id: str | None
    selection_method: SelectionMethod
    user_confirmed: bool = False
    override_reason: str | None = None
    style_pack_version: str | None = None
    warnings: tuple[str, ...] = ()


class StylePackReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    style_pack_id: str
    name_ar: str
    name_en: str
    version: str
    status: str  # demo_requires_architect_review in the MVP
    applicable_zone_ids: tuple[str, ...]
    source_metadata: dict
    reviewer: str | None = None
    review_date: str | None = None
    limitations: tuple[str, ...] = ()


class GateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    passed: bool
    reasons: tuple[str, ...]  # why the gate blocked (empty when passed)
