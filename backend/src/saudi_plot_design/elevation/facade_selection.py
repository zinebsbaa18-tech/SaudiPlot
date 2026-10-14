"""Primary facade selection: confirmed street boundary -> facing building wall.

The facing relationship is computed geometrically (wall orientation, outward
normal, projection overlap onto the street edge) - never from wall names and
never from nearest-midpoint alone (PRD FR-6 / M4 selection rules).
"""

from __future__ import annotations

import math

from saudi_plot_design.elevation.models import PrimaryFacadeSelection
from saudi_plot_design.model import Concept, Corner, EdgeClass, PlotModel, SpdInputError, Wall

_TOL = 1e-6
# Angular parallel tolerance consistent with the M1 plot gate (0.5 deg corner
# tolerance): |cross| of unit vectors = sin(angle). 1 deg covers accepted
# skews while still rejecting genuinely non-parallel walls.
_PARALLEL_TOL = math.sin(math.radians(1.0))


def boundary_id(edge_index: int) -> str:
    return f"plot-edge-{edge_index + 1}"


def select_primary_facade(
    plot: PlotModel,
    concept: Concept,
    boundary_edge_index: int,
    *,
    user_confirmed: bool,
    confirmation_timestamp: str | None = None,
) -> PrimaryFacadeSelection:
    """Match the confirmed street boundary to the building walls facing it.

    Raises SpdInputError for a non-street boundary. Returns a selection with
    empty wall ids (and a warning) when no building wall faces the street -
    the generator turns that into a structured rejection, never a fabricated
    elevation.
    """
    if not (0 <= boundary_edge_index < len(plot.edges)):
        raise SpdInputError(
            f"plot boundary index must be 1..{len(plot.edges)}, got {boundary_edge_index + 1}"
        )
    if plot.edges[boundary_edge_index] is not EdgeClass.STREET:
        raise SpdInputError(
            f"primary facade boundary must be classified 'street'; plot edge "
            f"{boundary_edge_index + 1} is '{plot.edges[boundary_edge_index].value}'"
        )

    facing = facing_walls(plot, concept, boundary_edge_index)
    warnings: list[str] = []
    if not facing:
        warnings.append(
            "no building exterior wall geometrically faces the selected street "
            "boundary; facade generation will be rejected"
        )
    return PrimaryFacadeSelection(
        project_id=plot.plot_id,
        concept_id=concept.concept_id,
        plot_fingerprint=plot.fingerprint,
        concept_fingerprint=concept.fingerprint,
        selected_plot_boundary_id=boundary_id(boundary_edge_index),
        selected_building_wall_ids=tuple(sorted(w.id for w in facing)),
        selection_method="geometric_facing_match",
        user_confirmed=user_confirmed,
        confirmation_timestamp=confirmation_timestamp,
        assumptions=(
            "the facade spans all collinear external wall segments facing the "
            "confirmed street (the plan derives one segment per fronting room)",
        ),
        warnings=tuple(warnings),
    )


def facing_walls(plot: PlotModel, concept: Concept, boundary_edge_index: int) -> list[Wall]:
    """External walls that genuinely face the given plot edge.

    A wall faces the street when: it is external, parallel to the street edge,
    its outward normal (away from the footprint interior) points toward the
    street edge line, and its projection onto the street edge overlaps it.
    """
    if concept.footprint is None:
        return []
    (e1, e2) = plot.edge_corners(boundary_edge_index)
    edge_dir = _unit((e2[0] - e1[0], e2[1] - e1[1]))
    fp = concept.footprint
    fp_center = ((fp.min_x + fp.max_x) / 2.0, (fp.min_y + fp.max_y) / 2.0)

    result: list[Wall] = []
    for wall in concept.walls:
        if not wall.is_external:
            continue
        wall_vec = (wall.end[0] - wall.start[0], wall.end[1] - wall.start[1])
        wall_dir = _unit(wall_vec)
        if abs(_cross(edge_dir, wall_dir)) > _PARALLEL_TOL:
            continue  # not parallel to the street edge
        midpoint = (
            (wall.start[0] + wall.end[0]) / 2.0,
            (wall.start[1] + wall.end[1]) / 2.0,
        )
        outward = _unit((midpoint[0] - fp_center[0], midpoint[1] - fp_center[1]))
        # Outward must be perpendicular-ish to the wall (reject walls whose
        # center-offset is along their own direction).
        normal = _wall_normal(wall_dir, outward)
        if normal is None:
            continue
        to_edge = _point_to_line_vector(midpoint, e1, edge_dir)
        distance = math.hypot(*to_edge)
        if distance <= _TOL:
            continue
        toward_street = (to_edge[0] / distance, to_edge[1] / distance)
        # The outward normal must point toward the street (0.99 tolerates the
        # slight skews M1 accepts while rejecting sideways/away-facing walls).
        if _dot(normal, toward_street) < 0.99:
            continue
        if _projection_overlap(wall, e1, e2, edge_dir) <= _TOL:
            continue
        result.append(wall)
    return result


def outward_normal(plot: PlotModel, concept: Concept, wall: Wall) -> Corner:
    """The wall's outward unit normal (away from the footprint interior)."""
    fp = concept.footprint
    fp_center = ((fp.min_x + fp.max_x) / 2.0, (fp.min_y + fp.max_y) / 2.0)
    wall_dir = _unit((wall.end[0] - wall.start[0], wall.end[1] - wall.start[1]))
    midpoint = ((wall.start[0] + wall.end[0]) / 2.0, (wall.start[1] + wall.end[1]) / 2.0)
    outward = _unit((midpoint[0] - fp_center[0], midpoint[1] - fp_center[1]))
    normal = _wall_normal(wall_dir, outward)
    if normal is None:
        raise SpdInputError(f"wall '{wall.id}' has no well-defined outward normal")
    return normal


def _wall_normal(wall_dir: Corner, outward_hint: Corner) -> Corner | None:
    """Choose the wall normal (+/-90 deg of wall_dir) matching the hint."""
    n1 = (-wall_dir[1], wall_dir[0])
    n2 = (wall_dir[1], -wall_dir[0])
    d1, d2 = _dot(n1, outward_hint), _dot(n2, outward_hint)
    if abs(d1) < 0.5 and abs(d2) < 0.5:
        return None
    return n1 if d1 > d2 else n2


def _point_to_line_vector(point: Corner, line_point: Corner, line_dir: Corner) -> Corner:
    """Shortest vector from point to the infinite line."""
    rel = (line_point[0] - point[0], line_point[1] - point[1])
    along = _dot(rel, line_dir)
    return (rel[0] - along * line_dir[0], rel[1] - along * line_dir[1])


def _projection_overlap(wall: Wall, e1: Corner, e2: Corner, edge_dir: Corner) -> float:
    edge_len = math.hypot(e2[0] - e1[0], e2[1] - e1[1])
    t1 = _dot((wall.start[0] - e1[0], wall.start[1] - e1[1]), edge_dir)
    t2 = _dot((wall.end[0] - e1[0], wall.end[1] - e1[1]), edge_dir)
    lo, hi = min(t1, t2), max(t1, t2)
    return min(hi, edge_len) - max(lo, 0.0)


def _unit(v: Corner) -> Corner:
    length = math.hypot(*v)
    if length <= _TOL:
        return (0.0, 0.0)
    return (v[0] / length, v[1] / length)


def _dot(a: Corner, b: Corner) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Corner, b: Corner) -> float:
    return a[0] * b[1] - a[1] * b[0]
