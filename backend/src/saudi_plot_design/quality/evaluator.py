"""Evidence-based, deterministic M6.1 architectural-quality evaluator."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from itertools import combinations

from shapely.geometry import Polygon, box

from saudi_plot_design.model import EXTERIOR, BuildableEnvelope, Concept, Room, Zone
from saudi_plot_design.quality.criteria import load_criteria_profile
from saudi_plot_design.quality.models import (
    ArchitecturalQualityAssessment,
    CRITICAL_QUALITY_CATEGORIES,
    CategoryFloorFailure,
    CategoryScore,
    CoverageStatus,
    CriteriaProfile,
    FindingSeverity,
    FindingStatus,
    PlanMetrics,
    QualityCategory,
    QualityFinding,
    RoomAssessment,
    ScoreStatus,
    StatusConstraint,
)
from saudi_plot_design.route_semantics import (
    EXTERNAL_PATH_NODE,
    EntranceInventoryItem,
    EntranceType,
    RouteType,
    analyze_room_route,
    classify_entrances,
    entrance_separation_evidence,
    reachable_rooms_from_external_doors,
    route_from_entrance,
)

ASSESSMENT_VERSION = "1.3.0"
_TOL = 1e-6


@dataclass(frozen=True)
class _Context:
    concept: Concept
    envelope: BuildableEnvelope
    profile: CriteriaProfile
    rooms: dict[str, Room]
    door_graph: dict[str, set[str]]
    wall_graph: dict[str, set[str]]
    combined_graph: dict[str, set[str]]
    entrances: tuple[EntranceInventoryItem, ...]
    reachable_rooms: frozenset[str]
    external_wall_rooms: frozenset[str]
    external_opening_rooms: frozenset[str]
    invalid_topology_references: tuple[str, ...]


@dataclass(frozen=True)
class _ScoringResult:
    category_scores: dict[QualityCategory, CategoryScore]
    raw_weighted_score: float | None
    coverage_adjusted_score: float | None
    overall_score: float | None
    score_status: ScoreStatus
    evidence_coverage: float
    evaluated_weight: float
    status_constraints: tuple[StatusConstraint, ...]
    category_floor_failures: tuple[CategoryFloorFailure, ...]


def _graph(nodes: tuple[str, ...]) -> dict[str, set[str]]:
    return {node: set() for node in nodes}


def _add_edge(graph: dict[str, set[str]], a: str, b: str) -> None:
    graph.setdefault(a, set()).add(b)
    graph.setdefault(b, set()).add(a)


def _build_context(
    concept: Concept, envelope: BuildableEnvelope, profile: CriteriaProfile
) -> _Context:
    rooms = {room.id: room for room in concept.rooms}
    nodes = tuple(sorted(rooms))
    door_graph = _graph(nodes)
    wall_graph = _graph(tuple(sorted(rooms)))
    invalid: list[str] = []

    walls = {wall.id: wall for wall in concept.walls}
    for wall in sorted(concept.walls, key=lambda item: item.id):
        unknown = sorted(room_id for room_id in wall.room_ids if room_id not in rooms)
        if unknown:
            invalid.append(f"wall {wall.id} references unknown rooms {','.join(unknown)}")
        valid = sorted(room_id for room_id in wall.room_ids if room_id in rooms)
        if len(valid) == 2:
            _add_edge(wall_graph, valid[0], valid[1])

    for door in sorted(concept.doors, key=lambda item: item.id):
        endpoints = (door.from_space, door.to_space)
        if any(endpoint not in rooms and endpoint != EXTERIOR for endpoint in endpoints):
            invalid.append(f"door {door.id} has unknown endpoint")
            continue
        if door.wall_id not in walls:
            invalid.append(f"door {door.id} references missing wall {door.wall_id}")
            continue
        if EXTERIOR not in endpoints:
            _add_edge(door_graph, *endpoints)

    for window in sorted(concept.windows, key=lambda item: item.id):
        if window.room_id not in rooms:
            invalid.append(f"window {window.id} references unknown room {window.room_id}")
        if window.wall_id not in walls:
            invalid.append(f"window {window.id} references missing wall {window.wall_id}")

    combined_graph = _graph(tuple(sorted(rooms)))
    for graph in (door_graph, wall_graph):
        for node in sorted(rooms):
            for neighbor in graph.get(node, set()):
                if neighbor in rooms:
                    _add_edge(combined_graph, node, neighbor)

    external_wall_rooms = frozenset(
        room_id
        for wall in concept.walls
        if wall.is_external
        for room_id in wall.room_ids
        if room_id in rooms
    )
    external_opening_rooms = {
        window.room_id
        for window in concept.windows
        if window.room_id in rooms
        and window.wall_id in walls
        and walls[window.wall_id].is_external
        and window.room_id in walls[window.wall_id].room_ids
    }
    for door in concept.doors:
        if (
            EXTERIOR in (door.from_space, door.to_space)
            and door.wall_id in walls
            and walls[door.wall_id].is_external
        ):
            room_id = door.to_space if door.from_space == EXTERIOR else door.from_space
            if room_id in rooms and room_id in walls[door.wall_id].room_ids:
                external_opening_rooms.add(room_id)

    return _Context(
        concept=concept,
        envelope=envelope,
        profile=profile,
        rooms=rooms,
        door_graph=door_graph,
        wall_graph=wall_graph,
        combined_graph=combined_graph,
        entrances=classify_entrances(concept),
        reachable_rooms=reachable_rooms_from_external_doors(concept),
        external_wall_rooms=external_wall_rooms,
        external_opening_rooms=frozenset(external_opening_rooms),
        invalid_topology_references=tuple(sorted(set(invalid))),
    )


def _shortest_path(
    graph: dict[str, set[str]],
    start: str,
    target: str,
    *,
    forbidden: frozenset[str] = frozenset(),
) -> tuple[str, ...] | None:
    if start not in graph or target not in graph or start in forbidden or target in forbidden:
        return None
    queue: deque[tuple[str, tuple[str, ...]]] = deque([(start, (start,))])
    visited = {start}
    while queue:
        node, path = queue.popleft()
        if node == target:
            return path
        for neighbor in sorted(graph.get(node, ())):
            if neighbor not in visited and neighbor not in forbidden:
                visited.add(neighbor)
                queue.append((neighbor, path + (neighbor,)))
    return None


def _distance(graph: dict[str, set[str]], a: str, b: str) -> int | None:
    path = _shortest_path(graph, a, b)
    return None if path is None else len(path) - 1


def _components(graph: dict[str, set[str]], nodes: set[str]) -> tuple[tuple[str, ...], ...]:
    remaining = set(nodes)
    result: list[tuple[str, ...]] = []
    while remaining:
        start = min(remaining)
        queue = [start]
        reached = {start}
        while queue:
            node = queue.pop(0)
            for neighbor in sorted(graph.get(node, ())):
                if neighbor in remaining and neighbor not in reached:
                    reached.add(neighbor)
                    queue.append(neighbor)
        remaining -= reached
        result.append(tuple(sorted(reached)))
    return tuple(result)


def _interval_covered(intervals: list[tuple[float, float]], start: float, end: float) -> bool:
    cursor = start
    for low, high in sorted(intervals):
        low = max(start, low)
        high = min(end, high)
        if high <= low:
            continue
        if low > cursor + _TOL:
            return False
        cursor = max(cursor, high)
        if cursor >= end - _TOL:
            return True
    return cursor >= end - _TOL


def _missing_room_sides(ctx: _Context, room: Room) -> tuple[str, ...]:
    rect = room.rect
    sides: dict[str, list[tuple[float, float]]] = {
        "south": [],
        "east": [],
        "north": [],
        "west": [],
    }
    for wall in ctx.concept.walls:
        if room.id not in wall.room_ids:
            continue
        (x1, y1), (x2, y2) = wall.start, wall.end
        if abs(y1 - y2) <= _TOL:
            interval = (min(x1, x2), max(x1, x2))
            if abs(y1 - rect.min_y) <= _TOL:
                sides["south"].append(interval)
            if abs(y1 - rect.max_y) <= _TOL:
                sides["north"].append(interval)
        if abs(x1 - x2) <= _TOL:
            interval = (min(y1, y2), max(y1, y2))
            if abs(x1 - rect.min_x) <= _TOL:
                sides["west"].append(interval)
            if abs(x1 - rect.max_x) <= _TOL:
                sides["east"].append(interval)
    covered = {
        "south": _interval_covered(sides["south"], rect.min_x, rect.max_x),
        "north": _interval_covered(sides["north"], rect.min_x, rect.max_x),
        "west": _interval_covered(sides["west"], rect.min_y, rect.max_y),
        "east": _interval_covered(sides["east"], rect.min_y, rect.max_y),
    }
    return tuple(side for side in ("south", "east", "north", "west") if not covered[side])


def _finite(*values: float) -> bool:
    return all(math.isfinite(value) for value in values)


def _room_dimensions(room: Room) -> tuple[float, float, float | None]:
    # Planner/layout geometry is canonical to six decimals. Round subtraction
    # results to that same precision so an equivalent 180-degree transform
    # cannot turn 2.70 m into 2.6999999999999993 at a quality threshold.
    width = round(room.rect.width, 6)
    height = round(room.rect.height, 6)
    clear = min(width, height)
    aspect = None
    if _finite(width, height) and clear > 0:
        aspect = max(width, height) / clear
    return clear, width * height, aspect


def _finding(
    ctx: _Context,
    rule_id: str,
    status: FindingStatus,
    *,
    affected: tuple[str, ...] = (),
    explanation: str,
    evidence: tuple[str, ...],
    measured,
    expected,
    recommendation: str,
    confidence: float = 1.0,
    source_method: str,
) -> QualityFinding:
    rule = ctx.profile.rule(rule_id)
    return QualityFinding(
        rule_id=rule_id,
        category=rule.category,
        severity=rule.severity,
        status=status,
        affected_object_ids=tuple(sorted(set(affected))),
        title=rule.title,
        explanation=explanation,
        evidence=evidence,
        measured_value=measured,
        expected_value=expected,
        recommendation=recommendation,
        confidence=confidence,
        source_method=source_method,
    )


def _threshold_status(
    measured: float, target: float, near_ratio: float, *, higher_is_better: bool
) -> FindingStatus:
    if higher_is_better:
        if measured >= target:
            return FindingStatus.PASS
        return FindingStatus.WARNING if measured >= target * near_ratio else FindingStatus.FAIL
    if measured <= target:
        return FindingStatus.PASS
    return FindingStatus.WARNING if measured <= target / near_ratio else FindingStatus.FAIL


def _room_rule_values(ctx: _Context, attribute: str) -> tuple[list[tuple[Room, float, float]], int]:
    values: list[tuple[Room, float, float]] = []
    unknown = 0
    for room in sorted(ctx.rooms.values(), key=lambda item: item.id):
        criterion = ctx.profile.room_type_criteria.get(room.type)
        if criterion is None:
            unknown += 1
            continue
        clear, area, aspect = _room_dimensions(room)
        measured = {"area": area, "clear": clear, "aspect": aspect}[attribute]
        expected = {
            "area": criterion.min_area_m2,
            "clear": criterion.min_clear_dimension_m,
            "aspect": criterion.max_aspect_ratio,
        }[attribute]
        if measured is not None:
            values.append((room, measured, expected))
    return values, unknown


def _types(ctx: _Context, *room_types: str) -> tuple[Room, ...]:
    wanted = set(room_types)
    return tuple(
        sorted((room for room in ctx.rooms.values() if room.type in wanted), key=lambda r: r.id)
    )


def _program_finding(
    ctx: _Context,
    rule_id: str,
    rooms: tuple[Room, ...],
    expected_count: int,
    label: str,
) -> QualityFinding:
    count = len(rooms)
    status = FindingStatus.PASS if count >= expected_count else FindingStatus.FAIL
    return _finding(
        ctx,
        rule_id,
        status,
        affected=tuple(room.id for room in rooms),
        explanation=f"The canonical program declares {count} {label} space(s).",
        evidence=(f"matched room ids: {', '.join(room.id for room in rooms) or 'none'}",),
        measured=count,
        expected={"minimum_count": expected_count},
        recommendation=(
            "Retain this program component."
            if status is FindingStatus.PASS
            else f"Revise the authored program to provide the missing {label}; do not infer it from names alone."
        ),
        source_method="canonical_room_type_count",
    )


def _evaluate_rule(ctx: _Context, rule_id: str) -> QualityFinding:  # noqa: C901, PLR0915
    profile = ctx.profile
    near = profile.thresholds["near_threshold_ratio"]
    rooms = tuple(sorted(ctx.rooms.values(), key=lambda item: item.id))
    walls = {wall.id: wall for wall in ctx.concept.walls}

    if rule_id == "GEO-001":
        overlaps = [
            (a.id, b.id, round(a.rect.overlap_area(b.rect), 4))
            for a, b in combinations(rooms, 2)
            if a.rect.overlap_area(b.rect) > _TOL
        ]
        affected = tuple(item for overlap in overlaps for item in overlap[:2])
        return _finding(
            ctx,
            rule_id,
            FindingStatus.FAIL if overlaps else FindingStatus.PASS,
            affected=affected,
            explanation="Room rectangles were pairwise intersected in the canonical local-meter frame.",
            evidence=tuple(f"{a}/{b}: {area:.4f} m2" for a, b, area in overlaps)
            or ("no positive-area room intersections",),
            measured=[{"rooms": [a, b], "overlap_m2": area} for a, b, area in overlaps],
            expected={"maximum_overlap_m2": 0.0},
            recommendation="Remove positive-area room intersections before further design development.",
            source_method="axis_aligned_rectangle_pair_intersection",
        )

    if rule_id == "GEO-002":
        polygon = Polygon(ctx.envelope.corners).buffer(_TOL)
        outside = []
        for room in rooms:
            r = room.rect
            if _finite(r.min_x, r.min_y, r.max_x, r.max_y) and r.width > 0 and r.height > 0:
                if not polygon.covers(box(r.min_x, r.min_y, r.max_x, r.max_y)):
                    outside.append(room.id)
        return _finding(
            ctx,
            rule_id,
            FindingStatus.FAIL if outside else FindingStatus.PASS,
            affected=tuple(outside),
            explanation="Each valid room rectangle was tested against the actual buildable-envelope polygon.",
            evidence=(f"outside rooms: {', '.join(outside) or 'none'}",),
            measured=len(outside),
            expected={"maximum_outside_rooms": 0},
            recommendation="Move affected room geometry fully inside the buildable envelope.",
            source_method="shapely_polygon_covers_room_rectangle",
        )

    if rule_id == "GEO-003":
        invalid = []
        for room in rooms:
            clear, area, _ = _room_dimensions(room)
            if (
                not _finite(
                    room.rect.min_x, room.rect.min_y, room.rect.max_x, room.rect.max_y, area
                )
                or clear <= 0
                or area <= 0
            ):
                invalid.append(room.id)
        return _finding(
            ctx,
            rule_id,
            FindingStatus.FAIL if invalid else FindingStatus.PASS,
            affected=tuple(invalid),
            explanation="Room rectangle coordinates, clear dimensions, and derived areas must be finite and positive.",
            evidence=(f"invalid rooms: {', '.join(invalid) or 'none'}",),
            measured=len(invalid),
            expected={"maximum_invalid_rooms": 0},
            recommendation="Correct invalid or zero-area canonical room geometry.",
            source_method="finite_positive_rectangle_dimensions",
        )

    if rule_id == "GEO-004":
        minimum = profile.thresholds["absolute_min_room_dimension_m"]
        values = [
            (room, _room_dimensions(room)[0])
            for room in rooms
            if _finite(_room_dimensions(room)[0]) and _room_dimensions(room)[0] > 0
        ]
        bad = [
            (
                room.id,
                measured,
                _threshold_status(measured, minimum, near, higher_is_better=True),
            )
            for room, measured in values
            if measured < minimum
        ]
        status = (
            FindingStatus.FAIL
            if any(item[2] is FindingStatus.FAIL for item in bad)
            else (FindingStatus.WARNING if bad else FindingStatus.PASS)
        )
        return _finding(
            ctx,
            rule_id,
            status,
            affected=tuple(item[0] for item in bad),
            explanation="The smaller room dimension was checked against the profile's absolute unusable-geometry threshold, separate from room-type usability targets.",
            evidence=tuple(
                f"{room_id}: {value:.2f} m below {minimum:.2f} m" for room_id, value, _ in bad
            )
            or ("no valid room falls below the absolute dimension threshold",),
            measured={"below_absolute_threshold": len(bad)},
            expected={"absolute_minimum_dimension_m": minimum},
            recommendation="Correct geometrically unusable narrow rooms before detailed planning.",
            confidence=len(values) / len(rooms) if rooms else 0.0,
            source_method="room_rectangle_absolute_min_dimension",
        )

    if rule_id == "USE-002":
        values, unknown = _room_rule_values(ctx, "clear")
        bad: list[tuple[str, float, float, FindingStatus]] = []
        for room, measured, expected in values:
            status = _threshold_status(measured, expected, near, higher_is_better=True)
            if status is not FindingStatus.PASS:
                bad.append((room.id, measured, expected, status))
        status = (
            FindingStatus.FAIL
            if any(item[3] is FindingStatus.FAIL for item in bad)
            else (FindingStatus.WARNING if bad else FindingStatus.PASS)
        )
        return _finding(
            ctx,
            rule_id,
            status,
            affected=tuple(item[0] for item in bad),
            explanation="The smaller rectangle dimension was compared with the configured room-type clear-dimension heuristic.",
            evidence=tuple(
                f"{room_id}: {value:.2f} m vs {target:.2f} m" for room_id, value, target, _ in bad
            )
            or ("all configured room types meet their clear-dimension heuristic",),
            measured={"below_target": len(bad), "unconfigured_room_types": unknown},
            expected={
                "minimum_by_room_type_m": {
                    key: value.min_clear_dimension_m
                    for key, value in profile.room_type_criteria.items()
                }
            },
            recommendation="Increase affected room clear dimensions or obtain architect review of the heuristic exception.",
            confidence=len(values) / len(rooms) if rooms else 0.0,
            source_method="room_rectangle_min_dimension_vs_profile",
        )

    if rule_id == "GEO-005":
        maximum = profile.thresholds["absolute_max_room_aspect_ratio"]
        values = [
            (room, _room_dimensions(room)[2])
            for room in rooms
            if _room_dimensions(room)[2] is not None
        ]
        bad = [
            (
                room.id,
                measured,
                _threshold_status(measured, maximum, near, higher_is_better=False),
            )
            for room, measured in values
            if measured > maximum
        ]
        status = (
            FindingStatus.FAIL
            if any(item[2] is FindingStatus.FAIL for item in bad)
            else (FindingStatus.WARNING if bad else FindingStatus.PASS)
        )
        return _finding(
            ctx,
            rule_id,
            status,
            affected=tuple(item[0] for item in bad),
            explanation="Room proportions were checked against the profile's absolute excessive-aspect threshold, separate from room-type usability targets.",
            evidence=tuple(
                f"{room_id}: {value:.2f} above {maximum:.2f}" for room_id, value, _ in bad
            )
            or ("no valid room exceeds the absolute aspect threshold",),
            measured={"above_absolute_threshold": len(bad)},
            expected={"absolute_maximum_aspect_ratio": maximum},
            recommendation="Correct geometrically extreme room proportions before detailed planning.",
            confidence=len(values) / len(rooms) if rooms else 0.0,
            source_method="room_rectangle_absolute_aspect_ratio",
        )

    if rule_id == "USE-003":
        values, unknown = _room_rule_values(ctx, "aspect")
        bad: list[tuple[str, float, float, FindingStatus]] = []
        for room, measured, expected in values:
            status = _threshold_status(measured, expected, near, higher_is_better=False)
            if status is not FindingStatus.PASS:
                bad.append((room.id, measured, expected, status))
        status = (
            FindingStatus.FAIL
            if any(item[3] is FindingStatus.FAIL for item in bad)
            else (FindingStatus.WARNING if bad else FindingStatus.PASS)
        )
        return _finding(
            ctx,
            rule_id,
            status,
            affected=tuple(item[0] for item in bad),
            explanation="Rectangle long-side/short-side ratios were compared with configured room-type proportion heuristics.",
            evidence=tuple(
                f"{room_id}: {value:.2f} vs maximum {target:.2f}"
                for room_id, value, target, _ in bad
            )
            or ("all configured room types meet their aspect heuristic",),
            measured={"above_target": len(bad), "unconfigured_room_types": unknown},
            expected={
                "maximum_by_room_type": {
                    key: value.max_aspect_ratio for key, value in profile.room_type_criteria.items()
                }
            },
            recommendation="Re-proportion affected rectangles; confirm actual furniture layouts in M6.2 before accepting an exception.",
            confidence=len(values) / len(rooms) if rooms else 0.0,
            source_method="room_rectangle_aspect_ratio_vs_profile",
        )

    if rule_id == "GEO-006":
        missing_sides = {
            room.id: _missing_room_sides(ctx, room)
            for room in rooms
            if _finite(room.rect.width, room.rect.height)
            and room.rect.width > 0
            and room.rect.height > 0
        }
        missing = sorted(room_id for room_id, sides in missing_sides.items() if sides)
        return _finding(
            ctx,
            rule_id,
            FindingStatus.FAIL if missing else FindingStatus.PASS,
            affected=tuple(missing),
            explanation="Each full rectangle side must be covered by explicit collinear canonical wall segments; boundaries are not inferred.",
            evidence=tuple(
                f"{room_id}: missing {', '.join(missing_sides[room_id])}" for room_id in missing
            )
            or ("all four sides of every valid room have explicit wall coverage",),
            measured={room_id: list(missing_sides[room_id]) for room_id in missing},
            expected={"required_covered_sides": ["south", "east", "north", "west"]},
            recommendation="Restore explicit canonical boundary-wall associations for affected rooms.",
            source_method="canonical_collinear_wall_interval_coverage",
        )

    if rule_id == "GEO-007":
        issues = list(ctx.invalid_topology_references)
        affected: set[str] = set()
        for door in sorted(ctx.concept.doors, key=lambda item: item.id):
            wall = walls.get(door.wall_id)
            endpoints = {door.from_space, door.to_space}
            if wall is None:
                affected.add(door.id)
                continue
            hosted = set(wall.room_ids)
            expected = hosted | ({EXTERIOR} if wall.is_external else set())
            if (
                endpoints != expected
                or not _finite(door.position_m, door.width_m)
                or door.width_m <= 0
                or door.position_m < -_TOL
                or door.position_m + door.width_m > wall.length_m + _TOL
            ):
                issues.append(f"door {door.id} is inconsistent with wall {wall.id}")
                affected.add(door.id)
        for window in sorted(ctx.concept.windows, key=lambda item: item.id):
            wall = walls.get(window.wall_id)
            if wall is None:
                affected.add(window.id)
                continue
            if (
                window.room_id not in wall.room_ids
                or not wall.is_external
                or not _finite(
                    window.position_m, window.width_m, window.sill_height_m, window.head_height_m
                )
                or window.width_m <= 0
                or window.position_m < -_TOL
                or window.position_m + window.width_m > wall.length_m + _TOL
                or window.head_height_m <= window.sill_height_m
            ):
                issues.append(f"window {window.id} is inconsistent with wall {wall.id}")
                affected.add(window.id)
        issues = sorted(set(issues))
        return _finding(
            ctx,
            rule_id,
            FindingStatus.FAIL if issues else FindingStatus.PASS,
            affected=tuple(affected),
            explanation="Door/window host references, endpoints, offsets, widths, and available heights were checked without inventing swing geometry.",
            evidence=tuple(issues) or ("all canonical openings are host-consistent",),
            measured=len(issues),
            expected={"maximum_opening_geometry_issues": 0},
            recommendation="Correct host references and opening extents before export.",
            source_method="canonical_opening_host_and_extent_validation",
        )

    if rule_id == "PRO-001":
        return _program_finding(
            ctx,
            rule_id,
            _types(ctx, "bedroom", "master_bedroom"),
            int(profile.thresholds["minimum_bedroom_count"]),
            "bedroom",
        )
    if rule_id == "PRO-002":
        return _program_finding(
            ctx,
            rule_id,
            _types(ctx, "master_bedroom"),
            int(profile.thresholds["minimum_primary_bedroom_count"]),
            "primary bedroom",
        )
    if rule_id == "PRO-003":
        return _program_finding(
            ctx,
            rule_id,
            _types(ctx, "guest_wc", "shared_bath", "master_bath"),
            int(profile.thresholds["minimum_bathroom_count"]),
            "bathroom/WC",
        )
    if rule_id == "PRO-004":
        return _program_finding(
            ctx,
            rule_id,
            _types(ctx, "family_living"),
            int(profile.thresholds["minimum_family_living_count"]),
            "family living",
        )
    if rule_id == "PRO-005":
        return _program_finding(
            ctx,
            rule_id,
            _types(ctx, "majlis"),
            int(profile.thresholds["minimum_majlis_count"]),
            "majlis",
        )
    if rule_id == "PRO-006":
        return _program_finding(
            ctx,
            rule_id,
            _types(ctx, "kitchen"),
            int(profile.thresholds["minimum_kitchen_count"]),
            "kitchen",
        )
    if rule_id == "PRO-007":
        return _program_finding(
            ctx,
            rule_id,
            _types(ctx, "corridor"),
            int(profile.thresholds["minimum_circulation_count"]),
            "circulation",
        )
    if rule_id == "PRO-008":
        return _program_finding(
            ctx,
            rule_id,
            _types(ctx, "entry"),
            int(profile.thresholds["minimum_entry_count"]),
            "entrance-related",
        )

    if rule_id == "USE-001":
        values, unknown = _room_rule_values(ctx, "area")
        bad: list[tuple[str, float, float, FindingStatus]] = []
        for room, measured, expected in values:
            status = _threshold_status(measured, expected, near, higher_is_better=True)
            if status is not FindingStatus.PASS:
                bad.append((room.id, measured, expected, status))
        status = (
            FindingStatus.FAIL
            if any(item[3] is FindingStatus.FAIL for item in bad)
            else (FindingStatus.WARNING if bad else FindingStatus.PASS)
        )
        return _finding(
            ctx,
            rule_id,
            status,
            affected=tuple(item[0] for item in bad),
            explanation="Derived rectangle areas were compared with explicit non-regulatory room-type heuristics.",
            evidence=tuple(
                f"{room_id}: {value:.2f} m2 vs {target:.2f} m2" for room_id, value, target, _ in bad
            )
            or ("all configured room types meet their area heuristic",),
            measured={"below_target": len(bad), "unconfigured_room_types": unknown},
            expected={
                "minimum_by_room_type_m2": {
                    key: value.min_area_m2 for key, value in profile.room_type_criteria.items()
                }
            },
            recommendation="Review affected room area and program trade-offs with an architect before geometry revision.",
            confidence=len(values) / len(rooms) if rooms else 0.0,
            source_method="room_rectangle_area_vs_profile",
        )

    if rule_id in {"USE-004", "USE-005"}:
        subject = (
            "furniture placement and clearances"
            if rule_id == "USE-004"
            else "door leaves, swing arcs, and maneuvering clearances"
        )
        return _finding(
            ctx,
            rule_id,
            FindingStatus.NOT_EVALUABLE,
            affected=tuple(room.id for room in rooms),
            explanation=f"The canonical model does not contain {subject}, so the conclusion is deliberately withheld.",
            evidence=(f"missing source data: {subject}",),
            measured=None,
            expected={"required_source_data": subject},
            recommendation="Add explicit review geometry in M6.2 before evaluating this criterion.",
            confidence=0.0,
            source_method="unsupported_by_canonical_plan_model",
        )

    if rule_id == "ADJ-001":
        kitchens = _types(ctx, "kitchen")
        targets = _types(ctx, "dining", "family_living")
        distances = [
            (_distance(ctx.combined_graph, k.id, t.id), k.id, t.id)
            for k in kitchens
            for t in targets
        ]
        finite = [item for item in distances if item[0] is not None]
        best = min(finite) if finite else None
        preferred = int(profile.thresholds["preferred_function_topology_steps"])
        warning = int(profile.thresholds["warning_function_topology_steps"])
        status = (
            FindingStatus.PASS
            if best and best[0] <= preferred
            else (FindingStatus.WARNING if best and best[0] <= warning else FindingStatus.FAIL)
        )
        return _finding(
            ctx,
            rule_id,
            status,
            affected=tuple(sorted({item for value in finite for item in value[1:]})),
            explanation="Kitchen proximity uses door and shared-wall topology, not center-point distance.",
            evidence=(
                (f"best relationship: {best[1]} to {best[2]} at {best[0]} topology step(s)",)
                if best
                else ("no connected kitchen-to-dining/living relationship",)
            ),
            measured=None if best is None else best[0],
            expected={
                "preferred_max_topology_steps": preferred,
                "warning_max": warning,
            },
            recommendation="Prefer a direct kitchen relationship to dining or family living while preserving service privacy.",
            source_method="combined_door_and_shared_wall_shortest_path",
        )

    if rule_id in {"ADJ-002", "SAU-003"}:
        majlis = _types(ctx, "majlis")
        toilets = _types(ctx, "guest_wc")
        analyses = [
            analyze_room_route(ctx.concept, m.id, t.id, RouteType.GUEST_WC)
            for m in majlis
            for t in toilets
        ]
        routes = [analysis.preferred_route for analysis in analyses]
        available = [route for route in routes if route.available]
        best = (
            min(
                available,
                key=lambda route: (
                    route.total_cost if route.total_cost is not None else 10**9,
                    route.door_ids,
                ),
            )
            if available
            else None
        )
        steps = best.total_cost if best else None
        preferred = int(profile.thresholds["preferred_guest_wc_door_steps"])
        maximum = int(profile.thresholds["max_guest_wc_door_steps"])
        status = (
            FindingStatus.PASS
            if best and best.allowed and not best.uses_external_path and steps <= preferred
            else (
                FindingStatus.WARNING
                if best and best.allowed and not best.uses_external_path and steps <= maximum
                else FindingStatus.FAIL
            )
        )
        route_evidence = (
            " -> ".join(best.display_sequence) if best else "no explicit guest-WC route"
        )
        return _finding(
            ctx,
            rule_id,
            status,
            affected=(
                tuple(
                    sorted(
                        {
                            *(node for node in best.room_sequence if node != EXTERNAL_PATH_NODE),
                            *best.door_ids,
                        }
                    )
                )
                if best
                else ()
            ),
            explanation=(
                "Guest-WC access uses internal doors only for preferred credit. Explicit "
                "exit/re-entry evidence is retained but cannot substitute for guest-zone access."
            ),
            evidence=(
                f"route: {route_evidence}",
                *(() if best is None else best.evidence),
                *(() if best is None else best.reasons),
            ),
            measured=steps,
            expected={"preferred_max_door_steps": preferred, "warning_max": maximum},
            recommendation="Keep the guest WC directly accessible to the guest route without entering private rooms.",
            source_method="explicit_internal_or_door_pair_route_policy",
        )

    if rule_id == "ADJ-003":
        baths = _types(ctx, "shared_bath", "master_bath")
        bedrooms = _types(ctx, "bedroom", "master_bedroom")
        preferred = int(profile.thresholds["preferred_bathroom_bedroom_steps"])
        distant = []
        measurements = []
        for bath in baths:
            distances = [
                (_distance(ctx.combined_graph, bath.id, bed.id), bed.id) for bed in bedrooms
            ]
            finite = [item for item in distances if item[0] is not None]
            best = min(finite) if finite else None
            measurements.append(
                {
                    "bathroom": bath.id,
                    "nearest_bedroom": best[1] if best else None,
                    "steps": best[0] if best else None,
                }
            )
            if best is None or best[0] > preferred:
                distant.append(bath.id)
        status = FindingStatus.PASS if not distant else FindingStatus.WARNING
        return _finding(
            ctx,
            rule_id,
            status,
            affected=tuple(distant),
            explanation="Bedroom-bathroom relationships use door/shared-wall topology and do not infer plumbing performance.",
            evidence=tuple(
                f"{item['bathroom']} -> {item['nearest_bedroom']}: {item['steps']} step(s)"
                for item in measurements
            )
            or ("no bedroom-related bathrooms modeled",),
            measured=measurements,
            expected={"preferred_max_topology_steps": preferred},
            recommendation="Keep bedroom-serving bathrooms directly accessible or spatially adjacent to sleeping zones.",
            source_method="combined_topology_nearest_function",
        )

    if rule_id == "ADJ-004":
        primary = _types(ctx, "master_bedroom")
        routes = [
            route_from_entrance(ctx.concept, EntranceType.FAMILY_MAIN, room.id, RouteType.FAMILY)
            for room in primary
        ]
        available = [route for route in routes if route.available]
        best = (
            min(available, key=lambda route: (route.total_cost or 10**9, route.door_ids))
            if available
            else None
        )
        unknown_entrances = tuple(
            item.door_id for item in ctx.entrances if item.entrance_type is EntranceType.UNKNOWN
        )
        if best is None and unknown_entrances:
            return _finding(
                ctx,
                rule_id,
                FindingStatus.NOT_EVALUABLE,
                affected=unknown_entrances,
                explanation=(
                    "Primary-bedroom privacy depth requires a supported family entrance; "
                    "unknown entrance intent cannot supply that origin."
                ),
                evidence=(
                    "unknown entrance doors requiring review: " + ", ".join(unknown_entrances),
                ),
                measured=None,
                expected={"supported_family_entrance": True},
                recommendation="Review and author family-entrance intent before evaluation.",
                confidence=0.0,
                source_method="unknown_family_entrance_requires_review",
            )
        steps = best.total_cost if best else None
        target = int(profile.thresholds["preferred_primary_privacy_door_steps"])
        status = (
            FindingStatus.PASS
            if steps is not None and steps >= target
            else (FindingStatus.WARNING if steps == target - 1 else FindingStatus.FAIL)
        )
        return _finding(
            ctx,
            rule_id,
            status,
            affected=(tuple(best.room_sequence) if best else tuple(room.id for room in primary)),
            explanation=(
                "Privacy depth is a door-step proxy from the classified family entrance, "
                "not from guest/service doors and not a sightline or acoustic conclusion."
            ),
            evidence=(
                (f"family route: {' -> '.join(best.display_sequence)}",)
                if best
                else ("primary bedroom is unreachable from a supported family entrance",)
            ),
            measured=steps,
            expected={"preferred_minimum_door_steps": target},
            recommendation="Maintain a circulation buffer between entrances/public rooms and the primary bedroom.",
            source_method="classified_family_entrance_internal_route_depth",
        )

    if rule_id in {"ADJ-005", "PRI-002"}:
        conflicts = []
        bedroom_ids = {room.id for room in _types(ctx, "bedroom", "master_bedroom")}
        public_ids = {room.id for room in rooms if room.zone is Zone.PUBLIC}
        for door in sorted(ctx.concept.doors, key=lambda item: item.id):
            endpoints = {door.from_space, door.to_space}
            if endpoints & bedroom_ids and endpoints & public_ids:
                conflicts.append(door.id)
        return _finding(
            ctx,
            rule_id,
            FindingStatus.FAIL if conflicts else FindingStatus.PASS,
            affected=tuple(conflicts),
            explanation="Only explicit direct door connections between declared public rooms and bedrooms are treated as exposure.",
            evidence=(f"conflicting doors: {', '.join(conflicts) or 'none'}",),
            measured=len(conflicts),
            expected={"maximum_direct_public_bedroom_doors": 0},
            recommendation="Insert circulation/privacy buffering; do not connect public guest rooms directly to bedrooms.",
            source_method="door_endpoint_zone_and_room_type_match",
        )

    if rule_id == "ADJ-006":
        analysis = analyze_room_route(ctx.concept, "kitchen", "maid_room", RouteType.SERVICE)
        route = analysis.preferred_route
        supported_external = tuple(item for item in analysis.external_routes if item.allowed)
        status = (
            FindingStatus.FAIL
            if not route.available or not route.allowed
            else (
                FindingStatus.WARNING
                if route.inappropriate_room_ids or route.uses_external_path
                else FindingStatus.PASS
            )
        )
        affected = tuple(
            sorted(
                {
                    route.start_room_id,
                    route.target_room_id,
                    *route.inappropriate_room_ids,
                    *route.door_ids,
                }
            )
        )
        evidence = [
            "preferred route: "
            + (" -> ".join(route.display_sequence) if route.available else "unavailable"),
            f"internal door steps: {route.internal_door_steps}; external door steps: {route.external_door_steps}; total cost: {route.total_cost}",
        ]
        evidence.extend(route.reasons)
        evidence.extend(
            "external service alternative: "
            f"{item.exit_door_id} -> external path -> {item.reentry_door_id}; "
            f"cost {item.total_cost}; requires_review={item.requires_review}"
            for item in supported_external
        )
        return _finding(
            ctx,
            rule_id,
            status,
            affected=affected,
            explanation=(
                "Kitchen-to-maid circulation is evaluated on the internal door graph. A "
                "classified service-door pair is reported separately and requires site-path "
                "review; it cannot by itself resolve internal service circulation."
            ),
            evidence=tuple(evidence),
            measured={
                "internal_door_steps": route.internal_door_steps,
                "external_door_steps": route.external_door_steps,
                "total_cost": route.total_cost,
                "discouraged_intermediate_rooms": list(route.inappropriate_room_ids),
                "supported_external_alternatives": len(supported_external),
            },
            expected={
                "forbidden_bedroom_or_majlis_rooms": 0,
                "preferred_discouraged_intermediate_rooms": 0,
                "external_route_requires_review": True,
            },
            recommendation=(
                "Prefer internal service circulation that avoids bedrooms, majlis, and primary "
                "family/public rooms; review any exterior service path separately."
            ),
            source_method="internal_service_route_with_separate_external_door_pair_audit",
        )

    if rule_id == "ADJ-007":
        total = len(ctx.concept.doors) + len(ctx.concept.windows) + len(ctx.concept.walls)
        invalid = len(ctx.invalid_topology_references)
        coverage = 1.0 if total == 0 else max(0.0, (total - invalid) / total)
        status = FindingStatus.PASS if invalid == 0 else FindingStatus.FAIL
        return _finding(
            ctx,
            rule_id,
            status,
            explanation="Canonical topology references were checked for known room and host-wall identifiers.",
            evidence=ctx.invalid_topology_references or ("all topology references resolve",),
            measured=round(coverage * 100, 2),
            expected={"minimum_reference_coverage_percent": 100.0},
            recommendation="Repair unresolved topology references before using adjacency diagnostics.",
            confidence=coverage,
            source_method="canonical_identifier_reference_resolution",
        )

    if rule_id == "PRI-001":
        zoned = sum(isinstance(room.zone, Zone) for room in rooms)
        coverage = zoned / len(rooms) if rooms else 0.0
        status = FindingStatus.PASS if coverage == 1 else FindingStatus.FAIL
        return _finding(
            ctx,
            rule_id,
            status,
            explanation="Every room must carry one of the canonical plan zones; semantic correctness still requires architect review.",
            evidence=(f"{zoned} of {len(rooms)} rooms carry canonical zones",),
            measured=round(coverage * 100, 2),
            expected={"minimum_zoning_coverage_percent": 100.0},
            recommendation="Assign explicit canonical zones to unzoned rooms before privacy evaluation.",
            confidence=coverage,
            source_method="canonical_room_zone_presence",
        )

    if rule_id == "PRI-003":
        analysis = analyze_room_route(ctx.concept, "majlis", "guest_wc", RouteType.GUEST_WC)
        route = analysis.preferred_route
        status = (
            FindingStatus.PASS
            if route.available
            and route.allowed
            and not route.uses_external_path
            and not route.inappropriate_room_ids
            else FindingStatus.FAIL
        )
        return _finding(
            ctx,
            rule_id,
            status,
            affected=tuple(sorted({*route.inappropriate_room_ids, *route.door_ids})),
            explanation=(
                "The check requires an internal majlis-to-guest-WC door route that avoids "
                "private rooms. Exit/re-entry is explicit evidence but not a privacy route."
            ),
            evidence=(
                "route: "
                + (" -> ".join(route.display_sequence) if route.available else "unavailable"),
                *route.reasons,
            ),
            measured={
                "uses_external_path": route.uses_external_path,
                "inappropriate_rooms": list(route.inappropriate_room_ids),
            },
            expected={
                "maximum_routes_through_private_rooms": 0,
                "external_exit_reentry_allowed": False,
            },
            recommendation="Route guest reception and guest WC access without traversing sleeping/private rooms.",
            source_method="explicit_internal_guest_route_policy",
        )

    if rule_id == "PRI-004":
        discouraged = {frozenset(pair) for pair in profile.discouraged_zone_transitions}
        transitions = []
        for door in sorted(ctx.concept.doors, key=lambda item: item.id):
            if EXTERIOR in (door.from_space, door.to_space):
                continue
            a = ctx.rooms.get(door.from_space)
            b = ctx.rooms.get(door.to_space)
            if a and b and frozenset((a.zone.value, b.zone.value)) in discouraged:
                transitions.append((door.id, a.zone.value, b.zone.value))
        public_private = [
            item for item in transitions if {item[1], item[2]} == {"public", "private"}
        ]
        status = (
            FindingStatus.FAIL
            if public_private
            else (FindingStatus.WARNING if transitions else FindingStatus.PASS)
        )
        return _finding(
            ctx,
            rule_id,
            status,
            affected=tuple(item[0] for item in transitions),
            explanation="Door-connected zone pairs were compared with the profile's explicit discouraged transitions.",
            evidence=tuple(f"{door}: {a} <-> {b}" for door, a, b in transitions)
            or ("no discouraged direct zone transitions",),
            measured=len(transitions),
            expected={
                "discouraged_zone_pairs": [
                    list(pair) for pair in profile.discouraged_zone_transitions
                ]
            },
            recommendation="Use circulation buffers between discouraged zone pairs.",
            source_method="door_endpoint_zone_transition_match",
        )

    if rule_id == "PRI-005":
        return _finding(
            ctx,
            rule_id,
            FindingStatus.NOT_EVALUABLE,
            explanation="Door connectivity and rectangles do not contain view cones, door states, furniture, or eye-level obstructions.",
            evidence=("missing source data: sightlines and visual obstructions",),
            measured=None,
            expected={"required_source_data": "view geometry and obstruction states"},
            recommendation="Perform a separate sightline/privacy review after detailed openings and furniture are modeled.",
            confidence=0.0,
            source_method="unsupported_by_canonical_plan_model",
        )

    if rule_id in {"CIR-001", "CIR-002"}:
        incident_rooms = {
            endpoint
            for door in ctx.concept.doors
            for endpoint in (door.from_space, door.to_space)
            if endpoint in ctx.rooms
        }
        no_doors = sorted(room.id for room in rooms if room.id not in incident_rooms)
        unreachable = sorted(room.id for room in rooms if room.id not in ctx.reachable_rooms)
        affected = no_doors if rule_id == "CIR-001" else unreachable
        label = (
            "no real door connection"
            if rule_id == "CIR-001"
            else "no route from any real external door"
        )
        return _finding(
            ctx,
            rule_id,
            FindingStatus.FAIL if affected else FindingStatus.PASS,
            affected=tuple(affected),
            explanation=f"Rooms with {label} are derived from explicit door endpoints only.",
            evidence=(f"affected rooms: {', '.join(affected) or 'none'}",),
            measured=len(affected),
            expected={"maximum_affected_rooms": 0},
            recommendation="Provide explicit circulation access without fabricating unmodeled doors.",
            source_method="door_graph_degree"
            if rule_id == "CIR-001"
            else "real_external_door_multisource_reachability",
        )

    if rule_id == "CIR-003":
        total = sum(max(0.0, _room_dimensions(room)[1]) for room in rooms)
        circulation = sum(
            max(0.0, _room_dimensions(room)[1]) for room in rooms if room.zone is Zone.CIRCULATION
        )
        ratio = circulation / total if total > 0 else 0.0
        preferred = profile.thresholds["preferred_circulation_ratio"]
        maximum = profile.thresholds["max_circulation_ratio"]
        status = (
            FindingStatus.PASS
            if ratio <= preferred
            else (FindingStatus.WARNING if ratio <= maximum else FindingStatus.FAIL)
        )
        return _finding(
            ctx,
            rule_id,
            status,
            affected=tuple(room.id for room in rooms if room.zone is Zone.CIRCULATION),
            explanation="Declared circulation-room area is divided by total valid room rectangle area.",
            evidence=(f"circulation {circulation:.2f} m2 / rooms {total:.2f} m2 = {ratio:.2%}",),
            measured=round(ratio, 4),
            expected={"preferred_max_ratio": preferred, "warning_max_ratio": maximum},
            recommendation="Reduce excessive circulation area without compromising clear access or privacy buffers.",
            source_method="canonical_zone_area_ratio",
        )

    if rule_id == "CIR-004":
        circulation_rooms = tuple(room for room in rooms if room.zone is Zone.CIRCULATION)
        minimum_degree = int(profile.thresholds["minimum_circulation_graph_degree"])
        isolated = sorted(
            room.id
            for room in circulation_rooms
            if len(ctx.door_graph.get(room.id, ())) < minimum_degree
        )
        return _finding(
            ctx,
            rule_id,
            FindingStatus.WARNING if isolated else FindingStatus.PASS,
            affected=tuple(isolated),
            explanation="Circulation spaces below the configured door-graph degree are reported as isolated/dead-end proxies.",
            evidence=(f"isolated circulation rooms: {', '.join(isolated) or 'none'}",),
            measured=len(isolated),
            expected={
                "preferred_isolated_circulation_rooms": 0,
                "minimum_graph_degree": minimum_degree,
            },
            recommendation="Connect or remove isolated circulation pockets after architectural review.",
            source_method="circulation_room_door_graph_degree",
        )

    if rule_id == "CIR-005":
        corridors = _types(ctx, "corridor")
        widths = [(room.id, _room_dimensions(room)[0]) for room in corridors]
        minimum = profile.thresholds["min_corridor_width_m"]
        narrow = [item for item in widths if item[1] < minimum]
        return _finding(
            ctx,
            rule_id,
            FindingStatus.FAIL if narrow else FindingStatus.PASS,
            affected=tuple(item[0] for item in narrow),
            explanation="The smaller corridor rectangle dimension is used as a clear-width proxy; finishes and projections are unavailable.",
            evidence=tuple(f"{room_id}: {width:.2f} m" for room_id, width in widths)
            or ("no corridor geometry modeled",),
            measured={room_id: round(width, 3) for room_id, width in widths},
            expected={"minimum_clear_width_m": minimum},
            recommendation="Increase narrow corridor geometry and verify detailed clear width later.",
            source_method="corridor_rectangle_min_dimension",
        )

    if rule_id == "CIR-006":
        targets = _types(ctx, "majlis", "family_living", "kitchen", "master_bedroom")
        transitions = []
        missing = []
        for target in targets:
            entrance_type = (
                EntranceType.GUEST_MAJLIS if target.type == "majlis" else EntranceType.FAMILY_MAIN
            )
            route_type = RouteType.GUEST if target.type == "majlis" else RouteType.FAMILY
            route = route_from_entrance(ctx.concept, entrance_type, target.id, route_type)
            if not route.available or not route.allowed:
                missing.append(target.id)
                continue
            zones = [
                ctx.rooms[node].zone.value for node in route.room_sequence if node in ctx.rooms
            ]
            count = sum(a != b for a, b in zip(zones, zones[1:]))
            transitions.append((target.id, count, route))
        if missing:
            return _finding(
                ctx,
                rule_id,
                FindingStatus.NOT_EVALUABLE,
                affected=tuple(missing),
                explanation=(
                    "Zone transitions require supported entrance-specific routes to every "
                    "major target; unavailable or disallowed routes cannot be omitted for credit."
                ),
                evidence=(f"targets without supported routes: {', '.join(missing)}",),
                measured=None,
                expected={"targets_without_supported_routes": 0},
                recommendation="Resolve or review entrance intent and internal route policy before comparison.",
                confidence=0.0,
                source_method="incomplete_classified_entrance_route_evidence",
            )
        maximum = int(profile.thresholds["max_zone_transitions"])
        excessive = [item for item in transitions if item[1] > maximum]
        return _finding(
            ctx,
            rule_id,
            FindingStatus.WARNING if excessive else FindingStatus.PASS,
            affected=tuple(item[0] for item in excessive),
            explanation="Zone changes are counted along deterministic shortest door routes to major rooms.",
            evidence=tuple(
                f"{target}: {count} transition(s), {' -> '.join(route.display_sequence)}"
                for target, count, route in transitions
            ),
            measured={target: count for target, count, _route in transitions},
            expected={"preferred_max_zone_transitions": maximum},
            recommendation="Simplify excessive zone transitions while preserving necessary privacy buffers.",
            source_method="classified_entrance_internal_route_zone_change_count",
        )

    if rule_id == "CIR-007":
        routes = []
        missing = []
        for room in rooms:
            if room.access_via_room is not None:
                continue
            entrance_type = (
                EntranceType.GUEST_MAJLIS if room.type == "majlis" else EntranceType.FAMILY_MAIN
            )
            route_type = RouteType.GUEST if room.type == "majlis" else RouteType.FAMILY
            route = route_from_entrance(ctx.concept, entrance_type, room.id, route_type)
            if route.available and route.allowed and not route.uses_external_path:
                routes.append(route)
            else:
                missing.append(room.id)
        if missing:
            return _finding(
                ctx,
                rule_id,
                FindingStatus.NOT_EVALUABLE,
                affected=tuple(sorted(missing)),
                explanation=(
                    "Mean route efficiency requires a supported entrance-specific internal "
                    "route for every normally circulated room; missing routes are not dropped."
                ),
                evidence=(
                    "rooms without supported entrance routes: " + ", ".join(sorted(missing)),
                ),
                measured=None,
                expected={"rooms_without_supported_routes": 0},
                recommendation="Resolve or review entrance intent and route policy before averaging.",
                confidence=0.0,
                source_method="incomplete_classified_entrance_route_evidence",
            )
        steps = [route.total_cost for route in routes if route.total_cost is not None]
        average = sum(steps) / len(steps) if steps else None
        preferred = profile.thresholds["preferred_average_route_steps"]
        maximum = profile.thresholds["max_average_route_steps"]
        status = (
            FindingStatus.PASS
            if average is not None and average <= preferred
            else (
                FindingStatus.WARNING
                if average is not None and average <= maximum
                else FindingStatus.FAIL
            )
        )
        return _finding(
            ctx,
            rule_id,
            status,
            explanation="Route efficiency is the mean real-door cost from the appropriate classified entrance for normally circulated rooms.",
            evidence=(
                (f"mean {average:.2f} steps across {len(steps)} reachable rooms",)
                if average is not None
                else ("no reachable normally circulated rooms",)
            ),
            measured=None if average is None else round(average, 3),
            expected={"preferred_max_average_steps": preferred, "warning_max": maximum},
            recommendation="Reduce unnecessarily indirect routes without removing privacy transitions.",
            source_method="mean_classified_entrance_internal_route_cost",
        )

    if rule_id in {"DAY-001", "DAY-002", "DAY-003"}:
        habitable = tuple(room for room in rooms if room.habitable)
        no_wall = sorted(room.id for room in habitable if room.id not in ctx.external_wall_rooms)
        no_opening = sorted(
            room.id for room in habitable if room.id not in ctx.external_opening_rooms
        )
        affected = no_wall if rule_id in {"DAY-001", "DAY-003"} else no_opening
        label = (
            "external-wall contact" if rule_id in {"DAY-001", "DAY-003"} else "an external opening"
        )
        return _finding(
            ctx,
            rule_id,
            FindingStatus.FAIL if affected else FindingStatus.PASS,
            affected=tuple(affected),
            explanation=f"Habitable rooms are checked for {label} using explicit wall/opening hosts only.",
            evidence=(f"habitable rooms without {label}: {', '.join(affected) or 'none'}",),
            measured=len(affected),
            expected={"maximum_affected_habitable_rooms": 0},
            recommendation="Provide verified external-wall/opening access for affected habitable rooms; assess daylight separately.",
            source_method="canonical_external_wall_and_opening_host_proxy",
        )

    if rule_id == "DAY-004":
        return _finding(
            ctx,
            rule_id,
            FindingStatus.NOT_EVALUABLE,
            explanation="Window areas, orientation, obstruction, shading, reflectance, and photometric inputs are unavailable.",
            evidence=(
                "external opening presence is available; daylight performance inputs are not",
            ),
            measured=None,
            expected={
                "required_source_data": [
                    "window_area",
                    "orientation",
                    "shading",
                    "obstructions",
                    "photometrics",
                ]
            },
            recommendation="Perform a dedicated daylight analysis when the required detailed inputs exist.",
            confidence=0.0,
            source_method="unsupported_daylight_compliance_inputs",
        )

    if rule_id == "WET-001":
        wet_ids = {room.id for room in rooms if room.wet}
        clusters = _components(ctx.wall_graph, wet_ids) if wet_ids else ()
        if not wet_ids:
            return _finding(
                ctx,
                rule_id,
                FindingStatus.NOT_EVALUABLE,
                explanation="No canonical wet rooms are available for the shared-wall grouping proxy.",
                evidence=("wet-room count: 0",),
                measured=None,
                expected={"required_source_data": "at least one declared wet room"},
                recommendation="Resolve program completeness before evaluating wet-room grouping.",
                confidence=0.0,
                source_method="conditional_wet_room_presence",
            )
        grouped_ids = {room_id for cluster in clusters if len(cluster) > 1 for room_id in cluster}
        grouped_ratio = len(grouped_ids) / len(wet_ids)
        preferred = profile.thresholds["preferred_grouped_wet_ratio"]
        minimum = profile.thresholds["minimum_grouped_wet_ratio"]
        status = (
            FindingStatus.PASS
            if grouped_ratio >= preferred
            else (FindingStatus.WARNING if grouped_ratio >= minimum else FindingStatus.FAIL)
        )
        ungrouped = tuple(sorted(wet_ids - grouped_ids))
        return _finding(
            ctx,
            rule_id,
            status,
            affected=ungrouped,
            explanation="The grouped-wet-room ratio counts wet rooms sharing a wall-connected cluster with at least one other wet room; it is not pipe routing.",
            evidence=tuple(
                f"cluster {index + 1}: {', '.join(cluster)}"
                for index, cluster in enumerate(clusters)
            ),
            measured=round(grouped_ratio, 4),
            expected={
                "preferred_grouped_ratio": preferred,
                "warning_minimum_grouped_ratio": minimum,
            },
            recommendation="Review isolated wet rooms against privacy and service-distribution priorities.",
            source_method="wet_room_shared_wall_grouped_ratio",
        )

    if rule_id == "WET-002":
        wet_ids = {room.id for room in rooms if room.wet}
        clusters = _components(ctx.wall_graph, wet_ids) if wet_ids else ()
        count = len(clusters)
        preferred = int(profile.thresholds["preferred_wet_clusters"])
        maximum = int(profile.thresholds["max_wet_clusters"])
        status = (
            FindingStatus.PASS
            if count <= preferred
            else (FindingStatus.WARNING if count <= maximum else FindingStatus.FAIL)
        )
        return _finding(
            ctx,
            rule_id,
            status,
            affected=tuple(sorted(wet_ids)),
            explanation="Wet-room clusters use shared-wall topology as a planning-efficiency proxy, not pipe routing.",
            evidence=tuple(
                f"cluster {index + 1}: {', '.join(cluster)}"
                for index, cluster in enumerate(clusters)
            )
            or ("no wet rooms modeled",),
            measured=count,
            expected={"preferred_max_clusters": preferred, "warning_max_clusters": maximum},
            recommendation="Review whether wet functions can share service zones without harming privacy or room usability.",
            source_method="wet_room_shared_wall_connected_components",
        )

    if rule_id == "WET-003":
        wet_ids = sorted(room.id for room in rooms if room.wet)
        distances = []
        for a, b in combinations(wet_ids, 2):
            distance = _distance(ctx.combined_graph, a, b)
            if distance is not None:
                distances.append((a, b, distance))
        maximum_distance = max((item[2] for item in distances), default=None)
        preferred = int(profile.thresholds["preferred_wet_topology_steps"])
        maximum = int(profile.thresholds["max_wet_topology_steps"])
        status = (
            FindingStatus.PASS
            if maximum_distance is not None and maximum_distance <= preferred
            else (
                FindingStatus.WARNING
                if maximum_distance is not None and maximum_distance <= maximum
                else FindingStatus.FAIL
            )
        )
        return _finding(
            ctx,
            rule_id,
            status,
            affected=tuple(wet_ids),
            explanation="Maximum wet-room separation uses combined door/shared-wall graph steps; it is not a pipe-length estimate.",
            evidence=tuple(f"{a} to {b}: {distance} step(s)" for a, b, distance in distances),
            measured=maximum_distance,
            expected={"preferred_max_topology_steps": preferred, "warning_max": maximum},
            recommendation="Review widely separated wet functions against privacy and service-distribution priorities.",
            source_method="wet_room_combined_topology_pair_distances",
        )

    if rule_id == "WET-004":
        return _finding(
            ctx,
            rule_id,
            FindingStatus.NOT_EVALUABLE,
            explanation="The plan contains no pipe routes, fixtures, stacks, slopes, capacities, or MEP design.",
            evidence=("only wet-room tags and plan adjacency are available",),
            measured=None,
            expected={"required_source_data": "plumbing/MEP design"},
            recommendation="Do not infer plumbing approval from wet-room proximity; engage MEP design separately.",
            confidence=0.0,
            source_method="unsupported_plumbing_inputs",
        )

    if rule_id == "SAU-001":
        groups = {
            "guest_public": any(room.zone is Zone.PUBLIC for room in rooms),
            "family": any(room.zone is Zone.FAMILY for room in rooms),
            "private_sleeping": any(
                room.zone is Zone.PRIVATE and room.type in {"bedroom", "master_bedroom"}
                for room in rooms
            ),
            "service": any(room.zone is Zone.WET_SERVICE for room in rooms),
        }
        missing = sorted(key for key, present in groups.items() if not present)
        return _finding(
            ctx,
            rule_id,
            FindingStatus.FAIL if missing else FindingStatus.PASS,
            affected=tuple(missing),
            explanation="The heuristic checks declared functional-zone presence only; it does not certify cultural suitability.",
            evidence=tuple(
                f"{key}: {'present' if value else 'missing'}" for key, value in groups.items()
            ),
            measured=sum(groups.values()),
            expected={"required_functional_groups": list(groups)},
            recommendation="Provide missing functional groups only where confirmed by the project brief and architect.",
            source_method="canonical_zone_and_room_type_presence",
        )

    if rule_id == "SAU-002":
        majlis = _types(ctx, "majlis")
        majlis_ids = {room.id for room in majlis}
        separate = [
            item
            for item in ctx.entrances
            if item.entrance_type is EntranceType.GUEST_MAJLIS
            and not item.requires_review
            and item.internal_room_id in majlis_ids
        ]
        unknown = [
            item
            for item in ctx.entrances
            if item.entrance_type is EntranceType.UNKNOWN and item.internal_room_id in majlis_ids
        ]
        if majlis and not separate and unknown:
            return _finding(
                ctx,
                rule_id,
                FindingStatus.NOT_EVALUABLE,
                affected=tuple(item.door_id for item in unknown),
                explanation=(
                    "A real majlis exterior door exists, but its authored entrance intent is "
                    "unknown and cannot provide dedicated guest-entrance credit."
                ),
                evidence=tuple(evidence for item in unknown for evidence in item.evidence),
                measured=None,
                expected={"supported_guest_entrance": True},
                recommendation="Review and author the real entrance intent before evaluation.",
                confidence=0.0,
                source_method="unknown_real_entrance_requires_review",
            )
        status = FindingStatus.PASS if majlis and separate else FindingStatus.FAIL
        affected = tuple(room.id for room in majlis) + tuple(item.door_id for item in separate)
        return _finding(
            ctx,
            rule_id,
            status,
            affected=affected,
            explanation="Where a majlis exists, the heuristic checks for an explicit exterior-tagged majlis entrance.",
            evidence=(
                f"majlis rooms: {', '.join(room.id for room in majlis) or 'none'}; supported guest entrances: {', '.join(item.door_id for item in separate) or 'none'}",
            ),
            measured={"majlis_count": len(majlis), "separate_entrance_count": len(separate)},
            expected={"minimum_majlis": 1, "minimum_majlis_entrances": 1},
            recommendation="Keep guest reception explicitly related to its confirmed entrance strategy.",
            source_method="room_type_and_supported_guest_entrance_inventory",
        )

    if rule_id == "SAU-004":
        entrances = tuple(
            item
            for item in ctx.entrances
            if item.entrance_type
            in {EntranceType.FAMILY_MAIN, EntranceType.GUEST_MAJLIS, EntranceType.SERVICE}
            and not item.requires_review
        )
        if len(entrances) < 2:
            return _finding(
                ctx,
                rule_id,
                FindingStatus.NOT_EVALUABLE,
                explanation="Entrance separation is evaluated only when multiple explicit exterior entrances exist.",
                evidence=(f"modeled exterior entrances: {len(entrances)}",),
                measured=len(entrances),
                expected={"minimum_entrances_for_evaluation": 2},
                recommendation="No conclusion; re-evaluate if the entrance strategy adds another entrance.",
                confidence=0.0,
                source_method="conditional_exterior_entrance_count",
            )
        destinations = [item.internal_room_id for item in entrances]
        distinct = len(set(destinations)) == len(destinations)
        return _finding(
            ctx,
            rule_id,
            FindingStatus.PASS if distinct else FindingStatus.FAIL,
            affected=tuple(item.door_id for item in entrances),
            explanation="Functional separation requires multiple tagged entrances to terminate in distinct interior spaces; physical spacing is not inferred.",
            evidence=tuple(
                f"{item.door_id} ({item.entrance_type.value}) -> {destination}"
                for item, destination in zip(entrances, destinations)
            ),
            measured=len(set(destinations)),
            expected={"distinct_destination_count": len(entrances)},
            recommendation="Separate entrance destinations functionally; verify facade spacing in detailed design.",
            source_method="supported_real_entrance_destination_identity",
        )

    if rule_id == "SAU-005":
        separation = entrance_separation_evidence(ctx.concept)
        if not separation.family_entrance_door_ids or not separation.guest_entrance_door_ids:
            return _finding(
                ctx,
                rule_id,
                FindingStatus.NOT_EVALUABLE,
                affected=separation.unknown_entrance_door_ids,
                explanation=(
                    "Guest/family route separation requires supported, distinct real family "
                    "and guest entrance doors; unknown intent cannot provide separation credit."
                ),
                evidence=separation.evidence,
                measured=None,
                expected={"supported_family_entrances": 1, "supported_guest_entrances": 1},
                recommendation="Author and review entrance intent before evaluating route separation.",
                confidence=0.0,
                source_method="explicit_entrance_and_route_evidence_unavailable",
            )
        if separation.separation_supported:
            status = FindingStatus.PASS
        elif (
            separation.guest_wc_route.uses_external_path
            or not separation.guest_wc_route.available
            or not separation.guest_wc_route.allowed
        ):
            status = FindingStatus.FAIL
        else:
            status = FindingStatus.WARNING
        affected = tuple(
            sorted(
                {
                    *separation.family_entrance_door_ids,
                    *separation.guest_entrance_door_ids,
                    *separation.shared_internal_room_ids,
                    *separation.guest_wc_route.door_ids,
                    "majlis",
                    "guest_wc",
                }
            )
        )
        return _finding(
            ctx,
            rule_id,
            status,
            affected=affected,
            explanation=(
                "Functional guest/family separation requires distinct real entrance doors plus "
                "an allowed internal guest-WC route; exit/re-entry cannot establish separation."
            ),
            evidence=(
                *separation.evidence,
                "guest-WC route: "
                + (
                    " -> ".join(separation.guest_wc_route.display_sequence)
                    if separation.guest_wc_route.available
                    else "unavailable"
                ),
            ),
            measured={
                "distinct_real_entrance_doors": separation.distinct_real_entrance_doors,
                "shared_internal_rooms": list(separation.shared_internal_room_ids),
                "guest_wc_uses_external_path": separation.guest_wc_route.uses_external_path,
            },
            expected={
                "distinct_real_entrance_doors": True,
                "shared_internal_rooms": 0,
                "guest_wc_uses_external_path": False,
            },
            recommendation="Keep guest-WC circulation internal to the guest route and distinct from the family entrance route.",
            source_method="explicit_distinct_entrance_and_internal_guest_route_evidence",
        )

    if rule_id == "SAU-006":
        return _finding(
            ctx,
            rule_id,
            FindingStatus.NOT_EVALUABLE,
            explanation="A geometry/topology heuristic cannot establish Saudi cultural acceptance, code compliance, permit readiness, or professional approval.",
            evidence=(
                "no verified regulation, stakeholder acceptance, or licensed architectural review is an evaluator input",
            ),
            measured=None,
            expected={
                "required_evidence": [
                    "project-specific stakeholder review",
                    "licensed architect review",
                    "applicable verified regulations",
                ]
            },
            recommendation="Treat this assessment only as a revision diagnostic and obtain the relevant human and regulatory reviews.",
            confidence=0.0,
            source_method="explicitly_outside_assessment_authority",
        )

    raise AssertionError(f"no evaluator implemented for {rule_id}")


def _score_status(score: float | None) -> ScoreStatus:
    if score is None:
        return ScoreStatus.NOT_RATED
    if score >= 85:
        return ScoreStatus.STRONG
    if score >= 70:
        return ScoreStatus.WORKABLE
    if score >= 50:
        return ScoreStatus.SUBSTANTIAL_REVISION
    return ScoreStatus.UNSUITABLE


_STATUS_RANK = {
    ScoreStatus.UNSUITABLE: 0,
    ScoreStatus.SUBSTANTIAL_REVISION: 1,
    ScoreStatus.WORKABLE: 2,
    ScoreStatus.STRONG: 3,
}


def _capped_status(status: ScoreStatus, maximum: ScoreStatus) -> ScoreStatus:
    if status is ScoreStatus.NOT_RATED or maximum is ScoreStatus.NOT_RATED:
        return ScoreStatus.NOT_RATED
    return status if _STATUS_RANK[status] <= _STATUS_RANK[maximum] else maximum


def _coverage_status(coverage: float, profile: CriteriaProfile) -> CoverageStatus:
    if coverage < profile.scoring.min_category_coverage:
        return CoverageStatus.INSUFFICIENT
    if coverage < profile.scoring.complete_category_coverage:
        return CoverageStatus.PARTIAL
    return CoverageStatus.COMPLETE


def _critical_floor_failure(
    category: QualityCategory,
    score: float | None,
    profile: CriteriaProfile,
) -> CategoryFloorFailure | None:
    floor = profile.scoring.critical_category_floors[category]
    if score is None:
        return CategoryFloorFailure(
            category=category,
            evaluated_score=None,
            required_minimum=floor.substantial_revision_min_score,
            required_for_status=ScoreStatus.SUBSTANTIAL_REVISION,
            maximum_status=ScoreStatus.NOT_RATED,
        )
    if score < floor.substantial_revision_min_score:
        return CategoryFloorFailure(
            category=category,
            evaluated_score=score,
            required_minimum=floor.substantial_revision_min_score,
            required_for_status=ScoreStatus.SUBSTANTIAL_REVISION,
            maximum_status=ScoreStatus.UNSUITABLE,
        )
    if score < floor.workable_min_score:
        return CategoryFloorFailure(
            category=category,
            evaluated_score=score,
            required_minimum=floor.workable_min_score,
            required_for_status=ScoreStatus.WORKABLE,
            maximum_status=ScoreStatus.SUBSTANTIAL_REVISION,
        )
    if score < floor.strong_min_score:
        return CategoryFloorFailure(
            category=category,
            evaluated_score=score,
            required_minimum=floor.strong_min_score,
            required_for_status=ScoreStatus.STRONG,
            maximum_status=ScoreStatus.WORKABLE,
        )
    return None


def _score(findings: tuple[QualityFinding, ...], profile: CriteriaProfile) -> _ScoringResult:
    category_scores: dict[QualityCategory, CategoryScore] = {}
    global_numerator = 0.0
    global_evaluated_weight = 0.0
    for category, category_weight in profile.category_weights.items():
        category_findings = [finding for finding in findings if finding.category is category]
        numerator = 0.0
        evaluated_weight = 0.0
        for finding in category_findings:
            rule = profile.rule(finding.rule_id)
            if finding.status is FindingStatus.NOT_EVALUABLE:
                continue
            evaluated_weight += rule.contribution_percent
            if finding.status is FindingStatus.PASS:
                factor = 1.0
            elif finding.status is FindingStatus.WARNING:
                factor = profile.scoring.warning_factors[finding.severity]
            else:
                factor = profile.scoring.fail_factors[finding.severity]
            numerator += rule.contribution_percent * factor
            global_weight = category_weight * rule.contribution_percent / 100.0
            global_numerator += global_weight * factor
            global_evaluated_weight += global_weight
        coverage = evaluated_weight / 100.0
        score = None
        if coverage >= profile.scoring.min_category_coverage and evaluated_weight > 0:
            score = round(
                numerator / evaluated_weight * 100.0, profile.scoring.score_rounding_digits
            )
        coverage_state = _coverage_status(coverage, profile)
        category_status = _score_status(score)
        if coverage_state is CoverageStatus.PARTIAL:
            category_status = _capped_status(category_status, ScoreStatus.WORKABLE)
        category_evaluated_checks = sum(
            finding.status is not FindingStatus.NOT_EVALUABLE for finding in category_findings
        )
        category_not_evaluable_checks = sum(
            finding.status is FindingStatus.NOT_EVALUABLE for finding in category_findings
        )
        category_scores[category] = CategoryScore(
            score=score,
            evaluated_score=score,
            score_status=category_status,
            evaluated_weight=round(evaluated_weight, 4),
            total_weight=100.0,
            coverage=round(coverage, 4),
            coverage_status=coverage_state,
            evaluated_checks=category_evaluated_checks,
            not_evaluable_checks=category_not_evaluable_checks,
            total_checks=len(category_findings),
            confidence=round(coverage, 4),
        )

    coverage = global_evaluated_weight / 100.0
    rated = coverage >= profile.scoring.min_overall_coverage and all(
        category_scores[category].confidence >= profile.scoring.mandatory_category_coverage
        for category in profile.scoring.mandatory_coverage_categories
    )
    raw = None
    coverage_adjusted = None
    if global_evaluated_weight > 0:
        raw = global_numerator / global_evaluated_weight * 100.0
        # Explicit deterministic evidence adjustment. Coverage is evaluated
        # criterion weight divided by total criterion weight; this is not a
        # statistical confidence estimate.
        coverage_adjusted = raw * coverage

    overall = None
    if rated and coverage_adjusted is not None:
        overall = coverage_adjusted

    unresolved_blocking = tuple(
        sorted(
            (
                finding
                for finding in findings
                if finding.severity is FindingSeverity.BLOCKING
                and finding.status in {FindingStatus.WARNING, FindingStatus.FAIL}
            ),
            key=lambda finding: finding.rule_id,
        )
    )
    if overall is not None and unresolved_blocking:
        overall = min(overall, profile.scoring.blocking_geometry_score_cap)

    constraints: list[StatusConstraint] = []
    if unresolved_blocking:
        constraints.append(
            StatusConstraint(
                constraint_id="blocking_finding_cap",
                maximum_status=ScoreStatus.UNSUITABLE,
                explanation=(
                    "An unresolved blocking finding applies the configured score cap and "
                    "prevents strong or workable status."
                ),
                affected_categories=tuple(
                    category
                    for category in QualityCategory
                    if any(finding.category is category for finding in unresolved_blocking)
                ),
                affected_rule_ids=tuple(finding.rule_id for finding in unresolved_blocking),
            )
        )

    if coverage < profile.scoring.min_overall_coverage:
        constraints.append(
            StatusConstraint(
                constraint_id="insufficient_overall_evidence",
                maximum_status=ScoreStatus.NOT_RATED,
                explanation=(
                    f"Evidence coverage {coverage:.2%} is below the configured "
                    f"{profile.scoring.min_overall_coverage:.2%} rating minimum."
                ),
            )
        )
    insufficient_mandatory = tuple(
        category
        for category in profile.scoring.mandatory_coverage_categories
        if category_scores[category].coverage < profile.scoring.mandatory_category_coverage
    )
    if insufficient_mandatory:
        constraints.append(
            StatusConstraint(
                constraint_id="insufficient_mandatory_category_evidence",
                maximum_status=ScoreStatus.NOT_RATED,
                explanation=(
                    "One or more mandatory categories are below the configured evidence "
                    "coverage required for a rating."
                ),
                affected_categories=insufficient_mandatory,
            )
        )

    floor_failures = tuple(
        failure
        for category in CRITICAL_QUALITY_CATEGORIES
        if (
            failure := _critical_floor_failure(
                category, category_scores[category].evaluated_score, profile
            )
        )
        is not None
    )
    for failure in floor_failures:
        score_text = (
            "not rated" if failure.evaluated_score is None else f"{failure.evaluated_score:.2f}"
        )
        constraints.append(
            StatusConstraint(
                constraint_id=f"critical_category_floor:{failure.category.value}",
                maximum_status=failure.maximum_status,
                explanation=(
                    f"{failure.category.value} evaluated score {score_text} is below the "
                    f"configured {failure.required_minimum:.2f} minimum required for "
                    f"{failure.required_for_status.value}."
                ),
                affected_categories=(failure.category,),
            )
        )

    failed_critical_major = tuple(
        sorted(
            (
                finding
                for finding in findings
                if finding.category in CRITICAL_QUALITY_CATEGORIES
                and finding.severity is FindingSeverity.MAJOR
                and finding.status is FindingStatus.FAIL
            ),
            key=lambda finding: finding.rule_id,
        )
    )
    if failed_critical_major:
        constraints.append(
            StatusConstraint(
                constraint_id="failed_major_critical_category",
                maximum_status=ScoreStatus.SUBSTANTIAL_REVISION,
                explanation=(
                    "A failed major rule in a critical architectural category prevents "
                    "strong or workable status."
                ),
                affected_categories=tuple(
                    category
                    for category in CRITICAL_QUALITY_CATEGORIES
                    if any(finding.category is category for finding in failed_critical_major)
                ),
                affected_rule_ids=tuple(finding.rule_id for finding in failed_critical_major),
            )
        )

    unresolved_major = tuple(
        sorted(
            (
                finding
                for finding in findings
                if finding.severity is FindingSeverity.MAJOR
                and finding.status in {FindingStatus.WARNING, FindingStatus.FAIL}
            ),
            key=lambda finding: finding.rule_id,
        )
    )
    if len(unresolved_major) > profile.scoring.max_unresolved_major_findings_for_strong:
        constraints.append(
            StatusConstraint(
                # Retain the v1.1 serialized identifier for run/manifest/CLI compatibility.
                constraint_id="multiple_unresolved_major_findings",
                maximum_status=ScoreStatus.WORKABLE,
                explanation=(
                    f"{len(unresolved_major)} unresolved major finding(s) exceed the configured "
                    "zero-finding maximum for strong status."
                ),
                affected_categories=tuple(
                    category
                    for category in QualityCategory
                    if any(finding.category is category for finding in unresolved_major)
                ),
                affected_rule_ids=tuple(finding.rule_id for finding in unresolved_major),
            )
        )

    if coverage < profile.scoring.strong_min_evidence_coverage:
        constraints.append(
            StatusConstraint(
                constraint_id="strong_overall_evidence_floor",
                maximum_status=ScoreStatus.WORKABLE,
                explanation=(
                    f"Evidence coverage {coverage:.2%} is below the configured "
                    f"{profile.scoring.strong_min_evidence_coverage:.2%} strong-status minimum."
                ),
            )
        )
    incomplete_critical = tuple(
        category
        for category in CRITICAL_QUALITY_CATEGORIES
        if category_scores[category].coverage
        < profile.scoring.strong_min_critical_category_coverage
    )
    if incomplete_critical:
        constraints.append(
            StatusConstraint(
                constraint_id="strong_critical_category_evidence_floor",
                maximum_status=ScoreStatus.WORKABLE,
                explanation=(
                    "One or more critical categories are below the configured evidence "
                    "coverage required for strong status."
                ),
                affected_categories=incomplete_critical,
            )
        )

    if overall is not None:
        overall = round(overall, profile.scoring.score_rounding_digits)
    score_status = _score_status(overall)
    for constraint in constraints:
        score_status = _capped_status(score_status, constraint.maximum_status)

    return _ScoringResult(
        category_scores=category_scores,
        raw_weighted_score=(
            None if raw is None else round(raw, profile.scoring.score_rounding_digits)
        ),
        coverage_adjusted_score=(
            None
            if coverage_adjusted is None
            else round(coverage_adjusted, profile.scoring.score_rounding_digits)
        ),
        overall_score=overall,
        score_status=score_status,
        evidence_coverage=round(coverage, 4),
        evaluated_weight=round(global_evaluated_weight, 4),
        status_constraints=tuple(constraints),
        category_floor_failures=floor_failures,
    )


def _room_assessments(
    ctx: _Context, findings: tuple[QualityFinding, ...]
) -> tuple[RoomAssessment, ...]:
    ranking = {
        FindingStatus.FAIL: 3,
        FindingStatus.WARNING: 2,
        FindingStatus.PASS: 1,
        FindingStatus.NOT_EVALUABLE: 0,
    }
    result = []
    for room in sorted(ctx.rooms.values(), key=lambda item: item.id):
        related = [finding for finding in findings if room.id in finding.affected_object_ids]
        evaluated = [
            finding.status
            for finding in related
            if finding.status is not FindingStatus.NOT_EVALUABLE
        ]
        status = max(evaluated, key=ranking.get) if evaluated else FindingStatus.PASS
        clear, _, aspect = _room_dimensions(room)
        area = room.rect.area if _finite(room.rect.area) and room.rect.area > 0 else 0.0
        safe_clear = clear if _finite(clear) and clear > 0 else 0.0
        result.append(
            RoomAssessment(
                room_id=room.id,
                room_name=room.name,
                room_type=room.type,
                zone=room.zone.value,
                area_m2=round(area, 3),
                clear_dimension_m=round(safe_clear, 3),
                aspect_ratio=None if aspect is None else round(aspect, 3),
                external_wall_contact=room.id in ctx.external_wall_rooms,
                external_opening=room.id in ctx.external_opening_rooms,
                status=status,
                finding_rule_ids=tuple(finding.rule_id for finding in related),
            )
        )
    return tuple(result)


def evaluate_architectural_quality(
    concept: Concept,
    envelope: BuildableEnvelope,
    criteria_profile: CriteriaProfile | None = None,
) -> ArchitecturalQualityAssessment:
    """Evaluate one canonical concept without modifying it.

    Invalid geometry is reported and capped here. The existing export binding
    gate remains responsible for refusing geometrically invalid concepts.
    """

    profile = criteria_profile or load_criteria_profile()
    context = _build_context(concept, envelope, profile)
    findings = tuple(_evaluate_rule(context, rule.rule_id) for rule in profile.rules)
    scoring = _score(findings, profile)
    room_assessments = _room_assessments(context, findings)
    rooms = tuple(context.rooms.values())
    wet_ids = {room.id for room in rooms if room.wet}
    wet_clusters = _components(context.wall_graph, wet_ids) if wet_ids else ()
    unreachable = [room.id for room in rooms if room.id not in context.reachable_rooms]
    incident_rooms = {
        endpoint
        for door in concept.doors
        for endpoint in (door.from_space, door.to_space)
        if endpoint in context.rooms
    }
    disconnected = [room.id for room in rooms if room.id not in incident_rooms]
    total_area = sum(max(0.0, room.rect.area) for room in rooms)
    circulation_area = sum(
        max(0.0, room.rect.area) for room in rooms if room.zone is Zone.CIRCULATION
    )
    bathrooms = _types(context, "guest_wc", "shared_bath", "master_bath")
    metrics = PlanMetrics(
        room_count=len(rooms),
        bedroom_count=len(_types(context, "bedroom", "master_bedroom")),
        bathroom_count=len(bathrooms),
        habitable_room_count=sum(room.habitable for room in rooms),
        wet_room_count=len(wet_ids),
        external_wall_room_count=len(context.external_wall_rooms),
        external_opening_room_count=len(context.external_opening_rooms),
        disconnected_room_count=len(disconnected),
        unreachable_room_count=len(unreachable),
        door_graph_edges=len(concept.doors),
        wall_adjacency_edges=sum(len(neighbors) for neighbors in context.wall_graph.values()) // 2,
        footprint_area_m2=round(concept.footprint.area, 3) if concept.footprint else 0.0,
        total_room_area_m2=round(total_area, 3),
        circulation_area_m2=round(circulation_area, 3),
        circulation_ratio=round(circulation_area / total_area, 4) if total_area > 0 else 0.0,
        wet_cluster_count=len(wet_clusters),
        evaluation_coverage=scoring.evidence_coverage,
    )
    evaluated = [
        finding for finding in findings if finding.status is not FindingStatus.NOT_EVALUABLE
    ]
    return ArchitecturalQualityAssessment(
        assessment_version=ASSESSMENT_VERSION,
        raw_weighted_score=scoring.raw_weighted_score,
        evidence_coverage=scoring.evidence_coverage,
        coverage_adjusted_score=scoring.coverage_adjusted_score,
        overall_score=scoring.overall_score,
        score_status=scoring.score_status,
        status_constraints=scoring.status_constraints,
        category_floor_failures=scoring.category_floor_failures,
        category_scores=scoring.category_scores,
        evaluation_confidence=scoring.evidence_coverage,
        evaluated_weight=scoring.evaluated_weight,
        total_weight=100.0,
        evaluated_checks=len(evaluated),
        passed_checks=sum(finding.status is FindingStatus.PASS for finding in findings),
        warning_checks=sum(finding.status is FindingStatus.WARNING for finding in findings),
        failed_checks=sum(finding.status is FindingStatus.FAIL for finding in findings),
        not_evaluable_checks=sum(
            finding.status is FindingStatus.NOT_EVALUABLE for finding in findings
        ),
        findings=findings,
        room_assessments=room_assessments,
        plan_metrics=metrics,
        criteria_profile=profile,
        limitations=profile.limitations
        + (
            "Findings are deterministic diagnostics and recommendations never modify the plan.",
            "Quality-target misses do not block export; the existing geometry/facade gate remains authoritative.",
        ),
    )
