"""Plot polygon ingest, validation, and metric geometry (PRD.md FR-1).

Two layers:

1. ``validate_polygon`` - structural validation of any 4-6 point plot polygon
   (closure, duplicates, self-intersection, winding order, plausible area)
   plus metric geometry.
2. ``enforce_reference_plot`` - the MVP generation gate: only the 20 m x 30 m
   axis-aligned reference rectangle proceeds to setbacks and planning
   (LOCKED_MVP_SCOPE.md capability 1).
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

from shapely.geometry import Polygon
from shapely.validation import explain_validity

from saudi_plot_design.model import Corner, EdgeClass, PlotMetrics, PlotModel, SpdInputError
from saudi_plot_design.plot.edges import require_single_street, validate_street_width

CSV_HEADER = ("id", "x_m", "y_m")
MIN_POINTS = 4
MAX_POINTS = 6
MIN_PLAUSIBLE_AREA_M2 = 50.0
MAX_PLAUSIBLE_AREA_M2 = 10_000.0
RIGHT_ANGLE_TOL_DEG = 0.5
LENGTH_TOL_M = 0.05
REFERENCE_WIDTH_M = 20.0
REFERENCE_DEPTH_M = 30.0
_COINCIDENT_TOL_M = 1e-9


def load_corners_csv(path: str | Path) -> tuple[Corner, ...]:
    """Read plot corners from the single documented CSV format (PRD.md FR-1.2)."""
    path = Path(path)
    if not path.is_file():
        raise SpdInputError(f"plot CSV not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise SpdInputError(f"plot CSV is empty: {path}")
    header = tuple(cell.strip().lower() for cell in rows[0])
    if header != CSV_HEADER:
        raise SpdInputError(
            f"plot CSV header must be exactly 'id,x_m,y_m', got '{','.join(rows[0])}'"
        )
    corners: list[Corner] = []
    for row_no, row in enumerate(rows[1:], start=2):
        if len(row) != 3:
            raise SpdInputError(f"plot CSV row {row_no} must have 3 columns, got {len(row)}")
        row_id, x_raw, y_raw = (cell.strip() for cell in row)
        expected_id = str(row_no - 1)
        if row_id != expected_id:
            raise SpdInputError(
                f"plot CSV row {row_no}: id must be '{expected_id}' (sequential from 1), "
                f"got '{row_id}'"
            )
        try:
            corners.append((float(x_raw), float(y_raw)))
        except ValueError:
            raise SpdInputError(
                f"plot CSV row {row_no}: coordinates must be numeric, got '{x_raw}','{y_raw}'"
            ) from None
    return _drop_closure_point(tuple(corners))


def corners_from_dimensions(width_m: float, depth_m: float) -> tuple[Corner, ...]:
    """Construct axis-aligned rectangle corners counterclockwise from the origin."""
    if width_m <= 0 or depth_m <= 0:
        raise SpdInputError(f"plot dimensions must be positive, got {width_m} x {depth_m}")
    return ((0.0, 0.0), (width_m, 0.0), (width_m, depth_m), (0.0, depth_m))


def validate_polygon(corners: tuple[Corner, ...]) -> PlotMetrics:
    """Structurally validate a plot polygon and return its metric geometry."""
    corners = _drop_closure_point(corners)
    if not (MIN_POINTS <= len(corners) <= MAX_POINTS):
        raise SpdInputError(
            f"plot must have {MIN_POINTS}-{MAX_POINTS} unique corners, got {len(corners)}"
        )
    for i, (x, y) in enumerate(corners):
        if not (math.isfinite(x) and math.isfinite(y)):
            raise SpdInputError(f"plot corner {i + 1} must have finite coordinates, got ({x}, {y})")
    for i, a in enumerate(corners):
        for j in range(i + 1, len(corners)):
            if _distance(a, corners[j]) <= _COINCIDENT_TOL_M:
                raise SpdInputError(
                    f"duplicate corner: points {i + 1} and {j + 1} are both ({a[0]:g}, {a[1]:g})"
                )
    # Validity first: a symmetric bowtie has a shoelace sum of zero (its lobes
    # cancel), so an area-first check would misdiagnose self-intersection as
    # collinearity. Only genuinely collinear corners get the zero-area message.
    if _all_collinear(corners):
        raise SpdInputError("plot polygon has zero area (corners are collinear)")
    polygon = Polygon(corners)
    if not polygon.is_valid:
        raise SpdInputError(
            f"plot polygon is self-intersecting or malformed: {explain_validity(polygon)}"
        )
    signed_area = _shoelace(corners)
    if abs(signed_area) <= _COINCIDENT_TOL_M:
        raise SpdInputError("plot polygon has zero area")
    if signed_area < 0:
        raise SpdInputError(
            "plot corners must be in counterclockwise order (got clockwise - reverse the row order)"
        )
    area = polygon.area
    if not (MIN_PLAUSIBLE_AREA_M2 <= area <= MAX_PLAUSIBLE_AREA_M2):
        raise SpdInputError(
            f"plot area {area:.1f} m2 is outside the plausible residential range "
            f"{MIN_PLAUSIBLE_AREA_M2:g}-{MAX_PLAUSIBLE_AREA_M2:g} m2 - check units (meters)"
        )
    edge_lengths = tuple(
        _distance(corners[i], corners[(i + 1) % len(corners)]) for i in range(len(corners))
    )
    centroid = polygon.centroid
    return PlotMetrics(
        area_m2=area,
        perimeter_m=polygon.exterior.length,
        centroid=(centroid.x, centroid.y),
        edge_lengths_m=edge_lengths,
    )


def enforce_reference_plot(corners: tuple[Corner, ...]) -> None:
    """MVP generation gate: only the 20 m x 30 m reference rectangle proceeds."""
    reference = corners_from_dimensions(REFERENCE_WIDTH_M, REFERENCE_DEPTH_M)
    if len(corners) != 4:
        raise SpdInputError(
            f"only the {REFERENCE_WIDTH_M:g} m x {REFERENCE_DEPTH_M:g} m rectangular "
            f"reference plot is supported in this MVP (got {len(corners)} corners)"
        )
    for i in range(4):
        angle = _corner_angle_deg(corners[i - 1], corners[i], corners[(i + 1) % 4])
        if abs(angle - 90.0) > RIGHT_ANGLE_TOL_DEG:
            raise SpdInputError(
                f"plot corner {i + 1} angle is {angle:.2f} deg - the MVP reference plot "
                f"must be rectangular (90 deg within {RIGHT_ANGLE_TOL_DEG} deg)"
            )
    for i in range(4):
        if _distance(corners[i], reference[i]) > LENGTH_TOL_M:
            raise SpdInputError(
                f"only the {REFERENCE_WIDTH_M:g} m x {REFERENCE_DEPTH_M:g} m reference plot "
                f"(corners (0,0),(20,0),(20,30),(0,30)) is supported in this MVP"
            )


def validate_location(location: tuple[float, float] | None) -> tuple[float, float] | None:
    if location is None:
        return None
    lat, lon = location
    # NaN passes chained range comparisons (both evaluate false), so check
    # finiteness explicitly first.
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise SpdInputError(f"location coordinates must be finite numbers, got ({lat}, {lon})")
    if not (-90.0 <= lat <= 90.0):
        raise SpdInputError(f"latitude must be in [-90, 90], got {lat}")
    if not (-180.0 <= lon <= 180.0):
        raise SpdInputError(f"longitude must be in [-180, 180], got {lon}")
    return (lat, lon)


def build_plot_model(
    corners: tuple[Corner, ...],
    edge_classes: tuple[EdgeClass, ...],
    street_width_m: float,
    location: tuple[float, float] | None = None,
) -> tuple[PlotModel, PlotMetrics]:
    """Validate all plot inputs together and return the model plus its metrics."""
    corners = _drop_closure_point(corners)
    metrics = validate_polygon(corners)
    if len(edge_classes) != len(corners):
        raise SpdInputError(
            f"every boundary edge needs a classification: plot has {len(corners)} edges "
            f"but {len(edge_classes)} classes were given"
        )
    require_single_street(edge_classes)
    street_width_m = validate_street_width(street_width_m)
    location = validate_location(location)
    enforce_reference_plot(corners)
    model = PlotModel(
        corners=corners,
        edges=tuple(edge_classes),
        street_width_m=street_width_m,
        location=location,
    )
    street_len = model.edge_length(model.street_edge_index)
    if abs(street_len - REFERENCE_WIDTH_M) > LENGTH_TOL_M:
        raise SpdInputError(
            f"the street edge must be a {REFERENCE_WIDTH_M:g} m frontage edge in this MVP, "
            f"got {street_len:g} m (edge {model.street_edge_index + 1})"
        )
    return model, metrics


def _drop_closure_point(corners: tuple[Corner, ...]) -> tuple[Corner, ...]:
    """Accept an explicitly closed ring by dropping a final point equal to the first."""
    if len(corners) >= 2 and _distance(corners[0], corners[-1]) <= _COINCIDENT_TOL_M:
        return corners[:-1]
    return corners


def _distance(a: Corner, b: Corner) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _all_collinear(corners: tuple[Corner, ...]) -> bool:
    (x0, y0), (x1, y1) = corners[0], corners[1]
    dx, dy = x1 - x0, y1 - y0
    return all(abs(dx * (y - y0) - dy * (x - x0)) <= _COINCIDENT_TOL_M for x, y in corners[2:])


def _shoelace(corners: tuple[Corner, ...]) -> float:
    area = 0.0
    for i, (x1, y1) in enumerate(corners):
        x2, y2 = corners[(i + 1) % len(corners)]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _corner_angle_deg(prev: Corner, at: Corner, nxt: Corner) -> float:
    v1 = (prev[0] - at[0], prev[1] - at[1])
    v2 = (nxt[0] - at[0], nxt[1] - at[1])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 <= _COINCIDENT_TOL_M or n2 <= _COINCIDENT_TOL_M:
        raise SpdInputError(f"plot corner {at} has a zero-length edge")
    cos_a = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cos_a))
