"""Canonical geometry reconstruction and proof checks for M6.2 candidates."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace

from shapely.geometry import box
from shapely.ops import unary_union

from saudi_plot_design.model import Concept, Door, EXTERIOR, Rect, Room, Wall, Window
from saudi_plot_design.planner import skeleton as sk
from saudi_plot_design.planner.compact_3br import _derive_walls
from saudi_plot_design.planner.validation import validate_concept

_TOL = 1e-6


class LayoutGeometryError(ValueError):
    """Deterministic candidate rejection caused by invalid layout geometry."""


@dataclass(frozen=True)
class OpeningIntent:
    kind: str
    id: str
    from_space: str | None = None
    to_space: str | None = None
    room_id: str | None = None
    external_side: str | None = None
    center_fraction: float = 0.5
    width_m: float = 0.0
    entrance_type: str | None = None
    sill_height_m: float | None = None
    head_height_m: float | None = None


def opening_intents(concept: Concept) -> tuple[OpeningIntent, ...]:
    walls = {wall.id: wall for wall in concept.walls}
    intents: list[OpeningIntent] = []
    for door in sorted(concept.doors, key=lambda item: item.id):
        wall = walls[door.wall_id]
        external = EXTERIOR in (door.from_space, door.to_space)
        intents.append(
            OpeningIntent(
                kind="door",
                id=door.id,
                from_space=door.from_space,
                to_space=door.to_space,
                external_side=_wall_side(wall, concept.footprint) if external else None,
                center_fraction=(door.position_m + door.width_m / 2.0) / wall.length_m,
                width_m=door.width_m,
                entrance_type=door.entrance_type,
            )
        )
    for window in sorted(concept.windows, key=lambda item: item.id):
        wall = walls[window.wall_id]
        intents.append(
            OpeningIntent(
                kind="window",
                id=window.id,
                room_id=window.room_id,
                external_side=_wall_side(wall, concept.footprint),
                center_fraction=(window.position_m + window.width_m / 2.0) / wall.length_m,
                width_m=window.width_m,
                sill_height_m=window.sill_height_m,
                head_height_m=window.head_height_m,
            )
        )
    return tuple(intents)


def replace_intent(
    intents: tuple[OpeningIntent, ...], opening_id: str, **changes
) -> tuple[OpeningIntent, ...]:
    found = False
    result: list[OpeningIntent] = []
    for intent in intents:
        if intent.id == opening_id:
            result.append(replace(intent, **changes))
            found = True
        else:
            result.append(intent)
    if not found:
        raise LayoutGeometryError(f"opening '{opening_id}' does not exist")
    return tuple(result)


def world_rect_to_local(concept: Concept, rect: Rect) -> Rect:
    if concept.footprint is None:
        raise LayoutGeometryError("candidate has no footprint")

    def point(x: float, y: float) -> tuple[float, float]:
        lx = x - concept.footprint.min_x
        ly = y - concept.footprint.min_y
        if concept.orientation_deg == 180:
            lx = concept.footprint.width - lx
            ly = concept.footprint.height - ly
        if concept.mirrored:
            lx = concept.footprint.width - lx
        return lx / concept.scale_x, ly / concept.scale_y

    points = [point(rect.min_x, rect.min_y), point(rect.max_x, rect.max_y)]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return Rect(min_x=min(xs), min_y=min(ys), max_x=max(xs), max_y=max(ys))


def local_rect_to_world(concept: Concept, rect: Rect) -> Rect:
    if concept.footprint is None:
        raise LayoutGeometryError("candidate has no footprint")

    def point(x: float, y: float) -> tuple[float, float]:
        lx, ly = x * concept.scale_x, y * concept.scale_y
        if concept.mirrored:
            lx = concept.footprint.width - lx
        if concept.orientation_deg == 180:
            lx = concept.footprint.width - lx
            ly = concept.footprint.height - ly
        return concept.footprint.min_x + lx, concept.footprint.min_y + ly

    points = [point(rect.min_x, rect.min_y), point(rect.max_x, rect.max_y)]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return Rect(
        min_x=round(min(xs), 6),
        min_y=round(min(ys), 6),
        max_x=round(max(xs), 6),
        max_y=round(max(ys), 6),
    )


def world_side_from_local(concept: Concept, side: str) -> str:
    mapped = side
    if concept.mirrored:
        mapped = {"W": "E", "E": "W"}.get(mapped, mapped)
    if concept.orientation_deg == 180:
        mapped = {"S": "N", "N": "S", "W": "E", "E": "W"}[mapped]
    return mapped


def rebuild_concept(
    baseline: Concept,
    room_rects: dict[str, Rect],
    intents: tuple[OpeningIntent, ...],
    *,
    concept_id: str,
) -> Concept:
    """Rebuild every derived field from canonical rectangles and opening intents."""
    if baseline.footprint is None:
        raise LayoutGeometryError("baseline concept has no footprint")
    _prove_program(baseline, room_rects)
    _prove_exact_tiling(baseline.footprint, room_rects)

    fp = baseline.footprint
    local_rooms = {
        room_id: Rect(
            min_x=round(rect.min_x - fp.min_x, 6),
            min_y=round(rect.min_y - fp.min_y, 6),
            max_x=round(rect.max_x - fp.min_x, 6),
            max_y=round(rect.max_y - fp.min_y, 6),
        )
        for room_id, rect in room_rects.items()
    }
    try:
        local_walls = _derive_walls(local_rooms, fp.width, fp.height)
    except AssertionError as exc:
        raise LayoutGeometryError(str(exc)) from exc

    wall_models: list[Wall] = []
    for index, local_wall in enumerate(local_walls, start=1):
        start, end = local_wall.start_end()
        start_w = (round(start[0] + fp.min_x, 6), round(start[1] + fp.min_y, 6))
        end_w = (round(end[0] + fp.min_x, 6), round(end[1] + fp.min_y, 6))
        start_w, end_w = sorted((start_w, end_w))
        model = Wall(
            id=f"W{index:02d}",
            start=start_w,
            end=end_w,
            thickness_m=(
                sk.EXTERNAL_WALL_THICKNESS_M
                if local_wall.is_external
                else sk.INTERNAL_WALL_THICKNESS_M
            ),
            height_m=sk.WALL_HEIGHT_PLACEHOLDER_M,
            is_external=local_wall.is_external,
            room_ids=local_wall.rooms,
        )
        wall_models.append(model)
    _prove_wall_boundaries(fp, room_rects, tuple(wall_models))

    doors: list[Door] = []
    windows: list[Window] = []
    for intent in sorted(intents, key=lambda item: (item.kind, item.id)):
        host = _select_host(intent, tuple(wall_models), fp)
        if not math.isfinite(intent.center_fraction) or not 0 <= intent.center_fraction <= 1:
            raise LayoutGeometryError(
                f"opening '{intent.id}' has invalid center fraction {intent.center_fraction}"
            )
        position = round(intent.center_fraction * host.length_m - intent.width_m / 2.0, 6)
        if intent.kind == "door":
            doors.append(
                Door(
                    id=intent.id,
                    wall_id=host.id,
                    from_space=str(intent.from_space),
                    to_space=str(intent.to_space),
                    position_m=position,
                    width_m=intent.width_m,
                    entrance_type=intent.entrance_type,
                )
            )
        elif intent.kind == "window":
            windows.append(
                Window(
                    id=intent.id,
                    wall_id=host.id,
                    room_id=str(intent.room_id),
                    position_m=position,
                    width_m=intent.width_m,
                    sill_height_m=float(intent.sill_height_m),
                    head_height_m=float(intent.head_height_m),
                )
            )
        else:
            raise LayoutGeometryError(f"opening '{intent.id}' has unsupported kind '{intent.kind}'")

    baseline_rooms = {room.id: room for room in baseline.rooms}
    rooms = tuple(
        _canonical_room(baseline_rooms[room_id], room_rects[room_id])
        for room_id in sorted(room_rects)
    )
    concept = baseline.model_copy(
        update={
            "concept_id": concept_id,
            "rooms": rooms,
            "walls": tuple(wall_models),
            "doors": tuple(sorted(doors, key=lambda item: item.id)),
            "windows": tuple(sorted(windows, key=lambda item: item.id)),
            "total_room_area_m2": round(sum(room.rect.area for room in rooms), 6),
            "validation": None,
            "rejection_reasons": (),
        }
    )
    _prove_canonical_metrics(concept)
    validation = validate_concept(concept)
    if not validation.passed:
        reasons = tuple(
            f"validation {check.id} failed: {check.details}" for check in validation.failures()
        )
        return concept.model_copy(update={"validation": validation, "rejection_reasons": reasons})
    return concept.model_copy(update={"validation": validation})


def geometry_fingerprint(concept: Concept) -> str:
    payload = {
        "footprint": concept.footprint.model_dump(mode="json") if concept.footprint else None,
        "rooms": [
            room.model_dump(mode="json") for room in sorted(concept.rooms, key=lambda r: r.id)
        ],
        "walls": [
            wall.model_dump(mode="json") for wall in sorted(concept.walls, key=lambda w: w.id)
        ],
        "doors": [
            door.model_dump(mode="json") for door in sorted(concept.doors, key=lambda d: d.id)
        ],
        "windows": [
            window.model_dump(mode="json") for window in sorted(concept.windows, key=lambda w: w.id)
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_room(source: Room, rect: Rect) -> Room:
    return source.model_copy(
        update={
            "rect": rect,
            "width_m": round(rect.width, 6),
            "length_m": round(rect.height, 6),
            "area_m2": round(rect.area, 6),
        }
    )


def _prove_canonical_metrics(concept: Concept) -> None:
    for room in concept.rooms:
        expected = (round(room.rect.width, 6), round(room.rect.height, 6), round(room.rect.area, 6))
        actual = (room.width_m, room.length_m, room.area_m2)
        if actual != expected:
            raise LayoutGeometryError(
                f"room '{room.id}' stored dimensions {actual} disagree with rectangle {expected}"
            )


def _prove_program(baseline: Concept, room_rects: dict[str, Rect]) -> None:
    required = tuple(sorted(sk.REQUIRED_ROOM_IDS))
    actual = tuple(sorted(room_rects))
    baseline_ids = tuple(sorted(room.id for room in baseline.rooms))
    if actual != required or baseline_ids != required:
        raise LayoutGeometryError(
            f"required Compact 3BR program mismatch: expected {required}, got {actual}"
        )


def _prove_exact_tiling(footprint: Rect, rooms: dict[str, Rect]) -> None:
    polygons = []
    for room_id, rect in sorted(rooms.items()):
        if (
            not all(
                math.isfinite(value) for value in (rect.min_x, rect.min_y, rect.max_x, rect.max_y)
            )
            or rect.width <= _TOL
            or rect.height <= _TOL
        ):
            raise LayoutGeometryError(f"room '{room_id}' has invalid rectangle")
        if not footprint.contains(rect, tol=_TOL):
            raise LayoutGeometryError(f"room '{room_id}' extends outside the footprint")
        polygons.append(box(rect.min_x, rect.min_y, rect.max_x, rect.max_y))
    for index, (room_id, rect) in enumerate(sorted(rooms.items())):
        for other_id, other in sorted(rooms.items())[index + 1 :]:
            if rect.overlap_area(other) > _TOL:
                raise LayoutGeometryError(f"rooms '{room_id}' and '{other_id}' overlap")
    footprint_polygon = box(footprint.min_x, footprint.min_y, footprint.max_x, footprint.max_y)
    difference_area = unary_union(polygons).symmetric_difference(footprint_polygon).area
    if difference_area > _TOL:
        raise LayoutGeometryError(
            f"room union does not exactly tile the footprint (difference {difference_area:.6f} m2)"
        )


def _prove_wall_boundaries(
    footprint: Rect, rooms: dict[str, Rect], walls: tuple[Wall, ...]
) -> None:
    for wall in walls:
        if wall.is_external:
            if len(wall.room_ids) != 1 or _wall_side(wall, footprint) is None:
                raise LayoutGeometryError(
                    f"external wall '{wall.id}' is not on the footprint boundary"
                )
            room = rooms[wall.room_ids[0]]
            if not _wall_on_room_boundary(wall, room):
                raise LayoutGeometryError(
                    f"external wall '{wall.id}' is not on room '{wall.room_ids[0]}' boundary"
                )
        else:
            if len(wall.room_ids) != 2:
                raise LayoutGeometryError(f"internal wall '{wall.id}' does not separate two rooms")
            first, second = (rooms[room_id] for room_id in wall.room_ids)
            if not (_wall_on_room_boundary(wall, first) and _wall_on_room_boundary(wall, second)):
                raise LayoutGeometryError(
                    f"internal wall '{wall.id}' is not a canonical shared-room boundary"
                )


def _wall_on_room_boundary(wall: Wall, room: Rect) -> bool:
    (x1, y1), (x2, y2) = wall.start, wall.end
    if abs(x1 - x2) <= _TOL:
        return (
            (abs(x1 - room.min_x) <= _TOL or abs(x1 - room.max_x) <= _TOL)
            and min(y1, y2) >= room.min_y - _TOL
            and max(y1, y2) <= room.max_y + _TOL
        )
    if abs(y1 - y2) <= _TOL:
        return (
            (abs(y1 - room.min_y) <= _TOL or abs(y1 - room.max_y) <= _TOL)
            and min(x1, x2) >= room.min_x - _TOL
            and max(x1, x2) <= room.max_x + _TOL
        )
    return False


def _select_host(intent: OpeningIntent, walls: tuple[Wall, ...], footprint: Rect) -> Wall:
    if intent.kind == "door":
        if EXTERIOR in (intent.from_space, intent.to_space):
            room_id = intent.to_space if intent.from_space == EXTERIOR else intent.from_space
            candidates = [
                wall
                for wall in walls
                if wall.is_external
                and wall.room_ids == (room_id,)
                and _wall_side(wall, footprint) == intent.external_side
            ]
        else:
            pair = frozenset((str(intent.from_space), str(intent.to_space)))
            candidates = [
                wall for wall in walls if not wall.is_external and frozenset(wall.room_ids) == pair
            ]
    else:
        candidates = [
            wall
            for wall in walls
            if wall.is_external
            and wall.room_ids == (intent.room_id,)
            and _wall_side(wall, footprint) == intent.external_side
        ]
    if not candidates:
        raise LayoutGeometryError(
            f"opening '{intent.id}' has no real host wall matching its topology and side"
        )
    return sorted(candidates, key=lambda wall: (-wall.length_m, wall.id))[0]


def _wall_side(wall: Wall, footprint: Rect | None) -> str | None:
    if footprint is None:
        return None
    (x1, y1), (x2, y2) = wall.start, wall.end
    if abs(x1 - x2) <= _TOL:
        if abs(x1 - footprint.min_x) <= _TOL:
            return "W"
        if abs(x1 - footprint.max_x) <= _TOL:
            return "E"
    elif abs(y1 - y2) <= _TOL:
        if abs(y1 - footprint.min_y) <= _TOL:
            return "S"
        if abs(y1 - footprint.max_y) <= _TOL:
            return "N"
    return None


__all__ = [
    "LayoutGeometryError",
    "OpeningIntent",
    "geometry_fingerprint",
    "local_rect_to_world",
    "opening_intents",
    "rebuild_concept",
    "replace_intent",
    "world_rect_to_local",
    "world_side_from_local",
]
