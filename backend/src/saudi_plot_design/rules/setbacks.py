"""Setback rule sets and buildable-envelope computation (PRD.md FR-3).

The MVP loads only demo-provenance rule sets (GEOSPATIAL_DATA_PROVENANCE.md
par.1 rule 2): a file claiming any other provenance level is rejected outright.
"""

from __future__ import annotations

import json
from importlib.resources import as_file, files
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from saudi_plot_design.model import (
    BuildableEnvelope,
    Corner,
    PlotModel,
    SetbackRuleSet,
    SpdInputError,
)
from saudi_plot_design.plot.edges import edge_roles

MIN_ENVELOPE_AREA_M2 = 25.0
_STRIP_EXTENSION_M = 1.0


class _SetbackFile(BaseModel):
    """On-disk schema for a setback rule set (demo-only in the MVP)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^DEMO-[A-Z0-9-]+$")
    provenance: Literal["demo"]
    display_name: str
    statement: str
    # allow_inf_nan=False: json.loads turns 1e400 into inf, which satisfies
    # gt=0 and would reach GEOS with non-finite coordinates.
    front_m: float = Field(gt=0, allow_inf_nan=False)
    side_m: float = Field(gt=0, allow_inf_nan=False)
    rear_m: float = Field(gt=0, allow_inf_nan=False)


def load_setback_rules(path: str | Path) -> SetbackRuleSet:
    path = Path(path)
    if not path.is_file():
        raise SpdInputError(f"setback rule file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpdInputError(f"setback rule file is not valid JSON: {path} ({exc})") from None
    try:
        parsed = _SetbackFile.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(loc) for loc in first["loc"]) or "<root>"
        raise SpdInputError(
            f"setback rule file {path.name} rejected at '{field}': {first['msg']} "
            f"(the MVP loads only demo-provenance rule sets with DEMO- ids)"
        ) from None
    return SetbackRuleSet(**parsed.model_dump())


def load_default_setback_rules() -> SetbackRuleSet:
    """Load the demo rule set shipped inside the package (works when installed)."""
    resource = files("saudi_plot_design").joinpath("data/demo/demo_setback_rules.json")
    with as_file(resource) as path:
        return load_setback_rules(path)


def compute_envelope(plot: PlotModel, rules: SetbackRuleSet) -> BuildableEnvelope:
    """Inset the plot polygon by the per-edge setbacks and validate the result."""
    region = Polygon(plot.corners)
    roles = edge_roles(plot.edges)
    for i, role in enumerate(roles):
        region = region.difference(_edge_strip(plot, i, rules.distance_for(role)))
    if region.is_empty:
        raise SpdInputError(
            f"setbacks of rule set {rules.id} leave no buildable area on this plot (empty envelope)"
        )
    if region.geom_type != "Polygon":
        raise SpdInputError(
            f"setbacks of rule set {rules.id} fragment the buildable area into "
            f"multiple pieces ({region.geom_type}) - not usable for planning"
        )
    if not region.is_valid:
        raise SpdInputError(f"buildable envelope is geometrically invalid ({rules.id})")
    if region.area < MIN_ENVELOPE_AREA_M2:
        raise SpdInputError(
            f"buildable envelope area {region.area:.1f} m2 is below the minimum "
            f"plannable area {MIN_ENVELOPE_AREA_M2:g} m2 - setbacks are implausible "
            f"for this plot"
        )
    oriented = orient(region, sign=1.0)
    corners = tuple(oriented.exterior.coords)[:-1]
    width, depth = _street_aligned_extents(plot, corners)
    return BuildableEnvelope(
        corners=tuple((float(x), float(y)) for x, y in corners),
        area_m2=region.area,
        width_m=width,
        depth_m=depth,
    )


def _edge_strip(plot: PlotModel, edge_index: int, distance: float) -> Polygon:
    """A strip covering everything within ``distance`` inward of the given edge.

    The strip is extended past both edge endpoints so adjacent strips overlap
    cleanly at corners.
    """
    (x1, y1), (x2, y2) = plot.edge_corners(edge_index)
    length = plot.edge_length(edge_index)
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    # Interior lies to the left of each directed edge of a CCW polygon.
    nx, ny = -uy, ux
    ext = _STRIP_EXTENSION_M
    a = (x1 - ux * ext, y1 - uy * ext)
    b = (x2 + ux * ext, y2 + uy * ext)
    return Polygon(
        [
            a,
            b,
            (b[0] + nx * distance, b[1] + ny * distance),
            (a[0] + nx * distance, a[1] + ny * distance),
        ]
    )


def _street_aligned_extents(plot: PlotModel, corners: tuple[Corner, ...]) -> tuple[float, float]:
    """Envelope extents parallel (width) and perpendicular (depth) to the street edge."""
    (x1, y1), (x2, y2) = plot.edge_corners(plot.street_edge_index)
    length = plot.edge_length(plot.street_edge_index)
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    nx, ny = -uy, ux
    along = [x * ux + y * uy for x, y in corners]
    across = [x * nx + y * ny for x, y in corners]
    return max(along) - min(along), max(across) - min(across)
