"""Compact 3BR planner runtime (PRD.md FR-5).

Places the single authored skeleton inside the buildable envelope. The only
runtime freedoms are the approved transform set: placement, orientation
derived from the street edge, mirroring, and bounded per-axis scaling. There
is no search: if the skeleton cannot fit validly, the planner returns an
honest structured rejection (a ``Concept`` with ``rejection_reasons``).
"""

from __future__ import annotations

from shapely.affinity import translate
from shapely.geometry import Point, Polygon
from shapely.ops import nearest_points

from saudi_plot_design.model import (
    EXTERIOR,
    BuildableEnvelope,
    Concept,
    Corner,
    Door,
    PlotModel,
    Rect,
    Room,
    Wall,
    Window,
)
from saudi_plot_design.planner import skeleton as sk
from saudi_plot_design.planner.validation import validate_concept

_TOL = 1e-6


def plan_compact_3br(
    plot: PlotModel,
    envelope: BuildableEnvelope,
    *,
    mirrored: bool = False,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> Concept:
    """Place the Compact 3BR skeleton and return a validated (or rejected) concept."""
    rejections: list[str] = []
    if not (sk.SCALE_X_MIN <= scale_x <= sk.SCALE_X_MAX):
        rejections.append(
            f"scale_x {scale_x:g} outside authored limits [{sk.SCALE_X_MIN:g}, {sk.SCALE_X_MAX:g}]"
        )
    if not (sk.SCALE_Y_MIN <= scale_y <= sk.SCALE_Y_MAX):
        rejections.append(
            f"scale_y {scale_y:g} outside authored limits [{sk.SCALE_Y_MIN:g}, {sk.SCALE_Y_MAX:g}]"
        )

    width = sk.BASE_WIDTH_M * scale_x
    depth = sk.BASE_DEPTH_M * scale_y
    if width > envelope.width_m + _TOL:
        rejections.append(
            f"skeleton width {width:.2f} m exceeds buildable envelope width "
            f"{envelope.width_m:.2f} m"
        )
    if depth > envelope.depth_m + _TOL:
        rejections.append(
            f"skeleton depth {depth:.2f} m exceeds buildable envelope depth "
            f"{envelope.depth_m:.2f} m"
        )

    orientation = _orientation_from_street(plot)
    plot_id = _plot_id(plot)
    concept_id = (
        f"{sk.SKELETON_ID}-v{sk.SKELETON_VERSION}-o{orientation}"
        f"-m{int(mirrored)}-s{scale_x:g}x{scale_y:g}"
    )

    if rejections:
        return Concept(
            concept_id=concept_id,
            plot_id=plot_id,
            skeleton_id=sk.SKELETON_ID,
            skeleton_version=sk.SKELETON_VERSION,
            footprint=None,
            orientation_deg=orientation,
            mirrored=mirrored,
            scale_x=scale_x,
            scale_y=scale_y,
            assumptions=sk.ASSUMPTIONS,
            rejection_reasons=tuple(rejections),
        )

    transform = _Transform(plot, envelope, orientation, mirrored, scale_x, scale_y)

    # The desired position uses the envelope's bounding box, but the real
    # envelope of a slightly skewed plot (within M1 tolerances) is not
    # axis-aligned. Placement is an approved runtime freedom: snap to the
    # nearest position where the whole footprint lies inside the actual
    # envelope polygon (exact erosion - deterministic, no search), and reject
    # only if no such position exists.
    origin = _feasible_origin(
        envelope, transform.width, transform.depth, (transform.fp_min_x, transform.fp_min_y)
    )
    if origin is None:
        return Concept(
            concept_id=concept_id,
            plot_id=plot_id,
            skeleton_id=sk.SKELETON_ID,
            skeleton_version=sk.SKELETON_VERSION,
            footprint=None,
            orientation_deg=orientation,
            mirrored=mirrored,
            scale_x=scale_x,
            scale_y=scale_y,
            assumptions=sk.ASSUMPTIONS,
            rejection_reasons=(
                "the skeleton footprint does not fit inside the actual buildable "
                "envelope polygon at any position",
            ),
        )
    transform.fp_min_x, transform.fp_min_y = origin
    footprint = transform.footprint_world()

    local_rooms = {spec.id: _scaled_rect(spec.rect, scale_x, scale_y) for spec in sk.ROOMS}
    local_walls = _derive_walls(local_rooms, width, depth)
    doors = _place_doors(local_walls, width, depth)
    windows = _place_windows(local_walls, width, depth)

    world_walls, world_openings = _transform_walls(local_walls, doors, windows, transform)
    rooms = tuple(_build_room(spec, transform.rect(local_rooms[spec.id])) for spec in sk.ROOMS)

    concept = Concept(
        concept_id=concept_id,
        plot_id=plot_id,
        skeleton_id=sk.SKELETON_ID,
        skeleton_version=sk.SKELETON_VERSION,
        footprint=footprint,
        orientation_deg=orientation,
        mirrored=mirrored,
        scale_x=scale_x,
        scale_y=scale_y,
        rooms=rooms,
        walls=world_walls,
        doors=world_openings[0],
        windows=world_openings[1],
        total_room_area_m2=round(sum(r.area_m2 for r in rooms), 3),
        assumptions=sk.ASSUMPTIONS,
    )
    report = validate_concept(concept)
    if not report.passed:
        # A failed livability check is a structured rejection too; the
        # geometry and full report are retained for inspection.
        return concept.model_copy(
            update={
                "validation": report,
                "rejection_reasons": tuple(
                    f"validation {c.id} failed: {c.details}" for c in report.failures()
                ),
            }
        )
    return concept.model_copy(update={"validation": report})


def _orientation_from_street(plot: PlotModel) -> int:
    """Approved orientations: skeleton front faces the street edge (0 or 180 deg)."""
    idx = plot.street_edge_index
    if idx == 0:
        return 0
    if idx == 2:
        return 180
    # The M1 gate restricts the street to a 20 m frontage edge (index 0 or 2
    # for the reference corner order); anything else is unreachable here.
    raise AssertionError(f"unsupported street edge index {idx} passed the input gate")


def _plot_id(plot: PlotModel) -> str:
    return plot.plot_id


def _feasible_origin(
    envelope: BuildableEnvelope,
    width: float,
    depth: float,
    desired: Corner,
) -> Corner | None:
    """Nearest valid position for the footprint's min corner, or None.

    The feasible set is the envelope polygon eroded by the footprint
    rectangle, computed exactly as the intersection of the envelope translated
    by minus each footprint corner offset (the envelope is convex). The
    desired position is kept when feasible; otherwise the nearest feasible
    point is chosen - deterministic geometry, no search.
    """
    env = Polygon(envelope.corners)
    feasible = None
    for ox, oy in ((0.0, 0.0), (width, 0.0), (width, depth), (0.0, depth)):
        shifted = translate(env, xoff=-ox, yoff=-oy)
        feasible = shifted if feasible is None else feasible.intersection(shifted)
    if feasible.is_empty:
        return None
    point = Point(desired)
    if feasible.buffer(_TOL).covers(point):
        return desired
    nearest = nearest_points(feasible, point)[0]
    return (round(nearest.x, 6), round(nearest.y, 6))


def _scaled_rect(rect: tuple[float, float, float, float], sx: float, sy: float) -> Rect:
    x1, y1, x2, y2 = rect
    return Rect(min_x=x1 * sx, min_y=y1 * sy, max_x=x2 * sx, max_y=y2 * sy)


class _Transform:
    """Local skeleton frame -> world plot frame for the approved orientations."""

    def __init__(
        self,
        plot: PlotModel,
        envelope: BuildableEnvelope,
        orientation: int,
        mirrored: bool,
        sx: float,
        sy: float,
    ) -> None:
        self.orientation = orientation
        self.mirrored = mirrored
        self.width = sk.BASE_WIDTH_M * sx
        self.depth = sk.BASE_DEPTH_M * sy
        env_xs = [c[0] for c in envelope.corners]
        env_ys = [c[1] for c in envelope.corners]
        self.env = Rect(min_x=min(env_xs), min_y=min(env_ys), max_x=max(env_xs), max_y=max(env_ys))
        margin = (self.env.width - self.width) / 2.0
        self.fp_min_x = self.env.min_x + margin
        # The footprint front sits on the envelope edge nearest the street.
        if orientation == 0:  # street at plot min_y
            self.fp_min_y = self.env.min_y
        else:  # 180: street at plot max_y
            self.fp_min_y = self.env.max_y - self.depth

    def footprint_world(self) -> Rect:
        return Rect(
            min_x=self.fp_min_x,
            min_y=self.fp_min_y,
            max_x=self.fp_min_x + self.width,
            max_y=self.fp_min_y + self.depth,
        )

    def point(self, p: Corner) -> Corner:
        x, y = p
        if self.mirrored:
            x = self.width - x
        if self.orientation == 0:
            return (self.fp_min_x + x, self.fp_min_y + y)
        # 180 deg rotation about the footprint center.
        return (self.fp_min_x + self.width - x, self.fp_min_y + self.depth - y)

    def rect(self, r: Rect) -> Rect:
        (x1, y1) = self.point((r.min_x, r.min_y))
        (x2, y2) = self.point((r.max_x, r.max_y))
        return Rect(min_x=min(x1, x2), min_y=min(y1, y2), max_x=max(x1, x2), max_y=max(y1, y2))

    def side(self, local_side: str) -> str:
        """Map a local side (S front / N rear / W / E) to a world side."""
        side = local_side
        if self.mirrored:
            side = {"W": "E", "E": "W"}.get(side, side)
        if self.orientation == 180:
            side = {"S": "N", "N": "S", "W": "E", "E": "W"}[side]
        return side


class _LocalWall:
    """A wall in the local frame: an interval on an axis-aligned line."""

    def __init__(
        self,
        axis: str,  # "v" (vertical, fixed x) or "h" (horizontal, fixed y)
        level: float,
        lo: float,
        hi: float,
        rooms: tuple[str, ...],
        is_external: bool,
    ) -> None:
        self.axis = axis
        self.level = level
        self.lo = lo
        self.hi = hi
        self.rooms = rooms
        self.is_external = is_external
        self.openings: list[tuple[str, str, float, float]] = []  # kind, id, center, width

    @property
    def length(self) -> float:
        return self.hi - self.lo

    def start_end(self) -> tuple[Corner, Corner]:
        if self.axis == "v":
            return (self.level, self.lo), (self.level, self.hi)
        return (self.lo, self.level), (self.hi, self.level)


def _derive_walls(rooms: dict[str, Rect], width: float, depth: float) -> list[_LocalWall]:
    """Derive deduplicated walls from the room tiling.

    Every atomic boundary interval is either shared by exactly two rooms
    (internal wall) or lies on the footprint boundary (external wall). Any
    other situation is an authored-tiling defect and raises.
    """
    walls: list[_LocalWall] = []
    walls += _derive_axis(rooms, vertical=True, boundary=(0.0, width))
    walls += _derive_axis(rooms, vertical=False, boundary=(0.0, depth))
    walls.sort(key=lambda w: (w.axis, round(w.level, 6), round(w.lo, 6)))
    return walls


def _derive_axis(
    rooms: dict[str, Rect], *, vertical: bool, boundary: tuple[float, float]
) -> list[_LocalWall]:
    # Collect room edges per line level: (level, lo, hi, room, on_low_side).
    edges: dict[float, list[tuple[float, float, str, bool]]] = {}
    for rid, r in rooms.items():
        if vertical:
            entries = [
                (r.min_x, r.min_y, r.max_y, rid, False),
                (r.max_x, r.min_y, r.max_y, rid, True),
            ]
        else:
            entries = [
                (r.min_y, r.min_x, r.max_x, rid, False),
                (r.max_y, r.min_x, r.max_x, rid, True),
            ]
        for level, lo, hi, room, low_side in entries:
            edges.setdefault(round(level, 6), []).append((lo, hi, room, low_side))
    walls: list[_LocalWall] = []
    axis = "v" if vertical else "h"
    for level, items in edges.items():
        cuts = sorted({round(v, 6) for lo, hi, _, _ in items for v in (lo, hi)})
        segments: list[tuple[float, float, tuple[str, ...], bool]] = []
        for lo, hi in zip(cuts, cuts[1:]):
            below = [
                r for slo, shi, r, low in items if low and slo <= lo + _TOL and shi >= hi - _TOL
            ]
            above = [
                r for slo, shi, r, low in items if not low and slo <= lo + _TOL and shi >= hi - _TOL
            ]
            if len(below) > 1 or len(above) > 1:
                raise AssertionError(f"tiling defect: multiple rooms on one side at {axis}={level}")
            if below and above:
                segments.append((lo, hi, (below[0], above[0]), False))
            elif below or above:
                if abs(level - boundary[0]) > _TOL and abs(level - boundary[1]) > _TOL:
                    raise AssertionError(
                        f"tiling defect: unmatched interior edge at {axis}={level}, [{lo}, {hi}]"
                    )
                segments.append((lo, hi, ((below or above)[0],), True))
        # Merge consecutive segments with identical room pairing.
        for lo, hi, room_pair, external in segments:
            prev = walls[-1] if walls else None
            if (
                prev is not None
                and prev.axis == axis
                and abs(prev.level - level) <= _TOL
                and abs(prev.hi - lo) <= _TOL
                and prev.rooms == room_pair
                and prev.is_external == external
            ):
                prev.hi = hi
            else:
                walls.append(_LocalWall(axis, level, lo, hi, room_pair, external))
    return walls


def _place_doors(
    walls: list[_LocalWall], width: float, depth: float
) -> list[tuple[str, sk.DoorSpec, _LocalWall, float]]:
    placed = []
    for spec in sk.DOORS:
        if spec.from_space == EXTERIOR or spec.to_space == EXTERIOR:
            room_id = spec.to_space if spec.from_space == EXTERIOR else spec.from_space
            candidates = [
                w
                for w in walls
                if w.is_external
                and w.rooms == (room_id,)
                and _local_wall_side(w, width, depth) == spec.side
            ]
        else:
            pair = frozenset((spec.from_space, spec.to_space))
            candidates = [w for w in walls if not w.is_external and frozenset(w.rooms) == pair]
        if not candidates:
            raise AssertionError(f"authored door {spec.id} has no host wall")
        wall = max(candidates, key=lambda w: w.length)
        center = wall.lo + spec.fraction * wall.length
        wall.openings.append(("door", spec.id, center, spec.width_m))
        placed.append((spec.id, spec, wall, center))
    return placed


def _place_windows(
    walls: list[_LocalWall], width: float, depth: float
) -> list[tuple[str, sk.WindowSpec, _LocalWall, float]]:
    placed = []
    for spec in sk.WINDOWS:
        candidates = [
            w
            for w in walls
            if w.is_external
            and w.rooms == (spec.room_id,)
            and _local_wall_side(w, width, depth) == spec.side
        ]
        if not candidates:
            raise AssertionError(f"authored window {spec.id} has no host wall")
        wall = max(candidates, key=lambda w: w.length)
        center = wall.lo + spec.fraction * wall.length
        wall.openings.append(("window", spec.id, center, spec.width_m))
        placed.append((spec.id, spec, wall, center))
    return placed


def _local_wall_side(wall: _LocalWall, width: float, depth: float) -> str | None:
    if wall.axis == "v":
        if abs(wall.level) <= _TOL:
            return "W"
        if abs(wall.level - width) <= _TOL:
            return "E"
    else:
        if abs(wall.level) <= _TOL:
            return "S"
        if abs(wall.level - depth) <= _TOL:
            return "N"
    return None


def _transform_walls(
    local_walls: list[_LocalWall],
    doors: list[tuple[str, sk.DoorSpec, _LocalWall, float]],
    windows: list[tuple[str, sk.WindowSpec, _LocalWall, float]],
    transform: _Transform,
) -> tuple[tuple[Wall, ...], tuple[tuple[Door, ...], tuple[Window, ...]]]:
    wall_models: dict[int, Wall] = {}
    for n, lw in enumerate(local_walls, start=1):
        start_l, end_l = lw.start_end()
        p1, p2 = transform.point(start_l), transform.point(end_l)
        start, end = sorted([p1, p2])
        wall_models[id(lw)] = Wall(
            id=f"W{n:02d}",
            start=(round(start[0], 6), round(start[1], 6)),
            end=(round(end[0], 6), round(end[1], 6)),
            thickness_m=sk.EXTERNAL_WALL_THICKNESS_M
            if lw.is_external
            else sk.INTERNAL_WALL_THICKNESS_M,
            height_m=sk.WALL_HEIGHT_PLACEHOLDER_M,
            is_external=lw.is_external,
            room_ids=lw.rooms,
        )

    def position_on(lw: _LocalWall, center_local: float, opening_width: float) -> float:
        wall = wall_models[id(lw)]
        center_pt_local: Corner = (
            (lw.level, center_local) if lw.axis == "v" else (center_local, lw.level)
        )
        cw = transform.point(center_pt_local)
        along = (cw[0] - wall.start[0]) + (
            cw[1] - wall.start[1]
        )  # one term is zero on axis-aligned walls
        return round(along - opening_width / 2.0, 6)

    door_models = tuple(
        Door(
            id=spec.id,
            wall_id=wall_models[id(lw)].id,
            from_space=spec.from_space,
            to_space=spec.to_space,
            position_m=position_on(lw, center, spec.width_m),
            width_m=spec.width_m,
            entrance_type=spec.entrance_type,
        )
        for _, spec, lw, center in doors
    )
    window_models = tuple(
        Window(
            id=spec.id,
            wall_id=wall_models[id(lw)].id,
            room_id=spec.room_id,
            position_m=position_on(lw, center, spec.width_m),
            width_m=spec.width_m,
            sill_height_m=sk.WINDOW_SILL_M,
            head_height_m=sk.WINDOW_HEAD_M,
        )
        for _, spec, lw, center in windows
    )
    return tuple(wall_models.values()), (door_models, window_models)


def _build_room(spec: sk.RoomSpec, rect: Rect) -> Room:
    return Room(
        id=spec.id,
        type=spec.type,
        name=spec.name,
        rect=rect,
        zone=spec.zone,
        priority=spec.priority,
        habitable=spec.habitable,
        wet=spec.wet,
        requires_external_wall=spec.requires_external_wall,
        requires_window=spec.requires_window,
        access_via_room=spec.access_via_room,
        width_m=round(rect.width, 6),
        length_m=round(rect.height, 6),
        area_m2=round(rect.area, 6),
    )
