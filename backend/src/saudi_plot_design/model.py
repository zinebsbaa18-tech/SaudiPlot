"""Shared data model for the pipeline (ARCHITECTURE.md par.4).

All coordinates are local plot coordinates in meters, counterclockwise.
Only ``PlotModel.location`` is geographic (WGS84), and it is consumed solely
by the character engine (M3).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict


def content_fingerprint(canonical: str) -> str:
    """Short deterministic content hash used to bind confirmations to the
    exact object they were made for (ids alone are not unique)."""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class SpdInputError(ValueError):
    """User-input error with a one-line actionable message (CLI exit 2 from M5)."""


class EdgeClass(str, Enum):
    STREET = "street"
    NEIGHBOR = "neighbor"
    PATH = "path"
    UNKNOWN = "unknown"


class EdgeRole(str, Enum):
    FRONT = "front"
    SIDE = "side"
    REAR = "rear"


Corner = tuple[float, float]


@dataclass(frozen=True)
class PlotMetrics:
    """Metric geometry of a validated plot polygon."""

    area_m2: float
    perimeter_m: float
    centroid: Corner
    edge_lengths_m: tuple[float, ...]


@dataclass(frozen=True)
class PlotModel:
    """A validated plot: polygon, edge classification, street width, location.

    ``edges[i]`` classifies the boundary segment from ``corners[i]`` to
    ``corners[(i + 1) % len(corners)]``.
    """

    corners: tuple[Corner, ...]
    edges: tuple[EdgeClass, ...]
    street_width_m: float
    location: tuple[float, float] | None = None  # (lat, lon) WGS84

    @property
    def street_edge_index(self) -> int:
        return self.edges.index(EdgeClass.STREET)

    @property
    def plot_id(self) -> str:
        """Deterministic plot identifier shared by all pipeline artifacts.

        NOT unique across plots with equal dimensions/street index - use
        ``fingerprint`` to bind a confirmation to this exact plot."""
        xs = [c[0] for c in self.corners]
        ys = [c[1] for c in self.corners]
        return (
            f"plot-{max(xs) - min(xs):g}x{max(ys) - min(ys):g}-street{self.street_edge_index + 1}"
        )

    @property
    def fingerprint(self) -> str:
        """Content hash over everything that defines this plot."""
        canonical = (
            f"{self.corners}|{tuple(e.value for e in self.edges)}"
            f"|{self.street_width_m}|{self.location}"
        )
        return content_fingerprint(canonical)

    def edge_corners(self, i: int) -> tuple[Corner, Corner]:
        return self.corners[i], self.corners[(i + 1) % len(self.corners)]

    def edge_length(self, i: int) -> float:
        (x1, y1), (x2, y2) = self.edge_corners(i)
        return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5


@dataclass(frozen=True)
class SetbackRuleSet:
    """A setback rule set. In the MVP only demo-provenance rule sets load."""

    id: str
    provenance: str
    display_name: str
    statement: str
    front_m: float
    side_m: float
    rear_m: float

    def distance_for(self, role: EdgeRole) -> float:
        if role is EdgeRole.FRONT:
            return self.front_m
        if role is EdgeRole.REAR:
            return self.rear_m
        return self.side_m


@dataclass(frozen=True)
class BuildableEnvelope:
    """The buildable region after setbacks, with street-aligned extents."""

    corners: tuple[Corner, ...]
    area_m2: float
    width_m: float  # extent parallel to the street edge
    depth_m: float  # extent perpendicular to the street edge


# --- Canonical floor-plan concept model (M2) ------------------------------
# One geometry source for the SVG preview and all future PDF/DXF/elevation
# renderers (ARCHITECTURE.md D1): exporters never compute geometry.

EXTERIOR = "exterior"  # sentinel space id for outside the building


class Zone(str, Enum):
    PUBLIC = "public"
    FAMILY = "family"
    PRIVATE = "private"
    WET_SERVICE = "wet_service"
    CIRCULATION = "circulation"


class Rect(BaseModel):
    """Axis-aligned rectangle in world meters."""

    model_config = ConfigDict(frozen=True)

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def area(self) -> float:
        return self.width * self.height

    def contains(self, other: Rect, tol: float = 1e-6) -> bool:
        return (
            other.min_x >= self.min_x - tol
            and other.min_y >= self.min_y - tol
            and other.max_x <= self.max_x + tol
            and other.max_y <= self.max_y + tol
        )

    def overlap_area(self, other: Rect) -> float:
        w = min(self.max_x, other.max_x) - max(self.min_x, other.min_x)
        h = min(self.max_y, other.max_y) - max(self.min_y, other.min_y)
        return w * h if (w > 0 and h > 0) else 0.0


class Room(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    type: str
    name: str
    rect: Rect
    zone: Zone
    priority: int
    habitable: bool
    wet: bool
    requires_external_wall: bool
    requires_window: bool
    # En-suite exemption: this room is deliberately reached through the named
    # bedroom (e.g. master bath); None for normally-circulated rooms.
    access_via_room: str | None = None
    width_m: float
    length_m: float
    area_m2: float


class Wall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    start: Corner
    end: Corner
    thickness_m: float
    height_m: float  # placeholder; the style pack governs facade height (M4)
    is_external: bool
    room_ids: tuple[str, ...]  # 2 room ids (internal) or 1 (external)

    @property
    def length_m(self) -> float:
        return ((self.end[0] - self.start[0]) ** 2 + (self.end[1] - self.start[1]) ** 2) ** 0.5


class Door(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    wall_id: str
    from_space: str  # room id or EXTERIOR
    to_space: str
    position_m: float  # offset of the door start along the wall, from wall start
    width_m: float
    entrance_type: str | None = None  # authored main/majlis/service/secondary intent


class Window(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    wall_id: str
    room_id: str
    position_m: float  # offset of the window start along the wall, from wall start
    width_m: float
    sill_height_m: float  # nominal; style pack governs at elevation (M4)
    head_height_m: float


class ValidationCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    passed: bool
    details: str = ""


class ValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    checks: tuple[ValidationCheck, ...]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def failures(self) -> tuple[ValidationCheck, ...]:
        return tuple(c for c in self.checks if not c.passed)


class Concept(BaseModel):
    """A Compact 3BR concept, or an honest structured rejection.

    A rejected concept has ``is_valid=False`` and non-empty
    ``rejection_reasons``. Pre-placement rejections (bad scale, envelope too
    small, footprint outside the real envelope) carry no geometry; rejections
    from failed livability validation retain the geometry and the full
    validation report for inspection.
    """

    model_config = ConfigDict(frozen=True)

    concept_id: str
    plot_id: str
    skeleton_id: str
    skeleton_version: int
    footprint: Rect | None
    orientation_deg: int
    mirrored: bool
    scale_x: float
    scale_y: float
    rooms: tuple[Room, ...] = ()
    walls: tuple[Wall, ...] = ()
    doors: tuple[Door, ...] = ()
    windows: tuple[Window, ...] = ()
    total_room_area_m2: float = 0.0
    validation: ValidationReport | None = None
    assumptions: tuple[str, ...] = ()
    rejection_reasons: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.rejection_reasons and self.validation is not None and self.validation.passed

    @property
    def fingerprint(self) -> str:
        """Content hash over the concept geometry (validation excluded so the
        value is identical before and after the report is attached)."""
        return content_fingerprint(self.model_dump_json(exclude={"validation"}))
