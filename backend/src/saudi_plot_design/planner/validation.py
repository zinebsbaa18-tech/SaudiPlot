"""Minimum livability validation - the fixed 15-check list (PRD.md FR-5, M2).

Exactly these checks and no more: no daylight simulation, no furniture
clearances, no structural/fire/energy/MEP/accessibility checks, and no
municipal compliance claims (NOT_NOW.md).
"""

from __future__ import annotations

from collections import deque

from saudi_plot_design.model import (
    EXTERIOR,
    Concept,
    Door,
    ValidationCheck,
    ValidationReport,
    Wall,
)
from saudi_plot_design.planner import skeleton as sk

_TOL = 1e-6
_BEDROOM_TYPES = frozenset({"bedroom", "master_bedroom"})


def validate_concept(concept: Concept) -> ValidationReport:
    checks = (
        _check_rooms_inside(concept),
        _check_no_overlap(concept),
        _check_min_areas(concept),
        _check_min_dimensions(concept),
        _check_wall_geometry(concept),
        _check_doors_hosted(concept),
        _check_door_clearance(concept),
        _check_external_walls(concept),
        _check_windows(concept),
        _check_no_circulation_through_bedrooms(concept),
        _check_wet_zone(concept),
        _check_main_entrance(concept),
        _check_majlis_entrance(concept),
        _check_opening_overlaps(concept),
        _check_openings_within_walls(concept),
    )
    return ValidationReport(checks=checks)


def _result(check_id: str, name: str, problems: list[str]) -> ValidationCheck:
    return ValidationCheck(
        id=check_id,
        name=name,
        passed=not problems,
        details="; ".join(problems) if problems else "ok",
    )


def _check_rooms_inside(c: Concept) -> ValidationCheck:
    problems = []
    if c.footprint is None:
        problems.append("no footprint")
    else:
        problems = [
            f"room '{r.id}' extends outside the footprint"
            for r in c.rooms
            if not c.footprint.contains(r.rect)
        ]
    return _result("C01", "all rooms inside building footprint", problems)


def _check_no_overlap(c: Concept) -> ValidationCheck:
    problems = []
    for i, a in enumerate(c.rooms):
        for b in c.rooms[i + 1 :]:
            overlap = a.rect.overlap_area(b.rect)
            if overlap > _TOL:
                problems.append(f"rooms '{a.id}' and '{b.id}' overlap by {overlap:.3f} m2")
    return _result("C02", "rooms do not overlap", problems)


def _check_min_areas(c: Concept) -> ValidationCheck:
    problems = []
    for r in c.rooms:
        min_area, _ = sk.MIN_DIMS[r.type]
        if r.area_m2 < min_area - _TOL:
            problems.append(f"room '{r.id}' area {r.area_m2:.2f} m2 < minimum {min_area:g} m2")
    return _result("C03", "required room minimum areas met", problems)


def _check_min_dimensions(c: Concept) -> ValidationCheck:
    problems = []
    for r in c.rooms:
        _, min_narrow = sk.MIN_DIMS[r.type]
        narrow = min(r.width_m, r.length_m)
        if narrow < min_narrow - _TOL:
            problems.append(f"room '{r.id}' narrow side {narrow:.2f} m < minimum {min_narrow:g} m")
    return _result("C04", "required minimum widths/lengths met", problems)


def _check_wall_geometry(c: Concept) -> ValidationCheck:
    problems = [
        f"wall '{w.id}' has zero or invalid geometry"
        for w in c.walls
        if w.length_m <= _TOL or w.thickness_m <= 0
    ]
    return _result("C05", "every wall has valid non-zero geometry", problems)


def _walls_by_id(c: Concept) -> dict[str, Wall]:
    return {w.id: w for w in c.walls}


def _check_doors_hosted(c: Concept) -> ValidationCheck:
    walls = _walls_by_id(c)
    problems = []
    for d in c.doors:
        wall = walls.get(d.wall_id)
        if wall is None:
            problems.append(f"door '{d.id}' references missing wall '{d.wall_id}'")
            continue
        spaces = {d.from_space, d.to_space}
        if EXTERIOR in spaces:
            room = next(iter(spaces - {EXTERIOR}))
            if not wall.is_external or room not in wall.room_ids:
                problems.append(
                    f"entrance door '{d.id}' not hosted on an external wall of '{room}'"
                )
        elif spaces != set(wall.room_ids):
            problems.append(
                f"door '{d.id}' connects {sorted(spaces)} but wall '{wall.id}' "
                f"separates {sorted(wall.room_ids)}"
            )
    return _result("C06", "every door hosted on a real wall", problems)


def _check_door_clearance(c: Concept) -> ValidationCheck:
    walls = _walls_by_id(c)
    problems = []
    for d in c.doors:
        wall = walls.get(d.wall_id)
        if wall is None:
            continue  # reported by C06
        clearance = sk.MIN_DOOR_EDGE_CLEARANCE_M
        if d.position_m < clearance - _TOL or (
            d.position_m + d.width_m > wall.length_m - clearance + _TOL
        ):
            problems.append(
                f"door '{d.id}' ({d.width_m:g} m) lacks clear wall length on "
                f"wall '{wall.id}' ({wall.length_m:.2f} m)"
            )
    return _result("C07", "every door has sufficient clear wall length", problems)


def _room_walls(c: Concept, room_id: str) -> list[Wall]:
    return [w for w in c.walls if room_id in w.room_ids]


def _check_external_walls(c: Concept) -> ValidationCheck:
    problems = []
    for r in c.rooms:
        if not (r.habitable or r.requires_external_wall):
            continue
        if not any(w.is_external for w in _room_walls(c, r.id)):
            problems.append(f"room '{r.id}' requires an external wall but has none")
    return _result("C08", "habitable rooms have at least one external wall", problems)


def _check_windows(c: Concept) -> ValidationCheck:
    walls = _walls_by_id(c)
    problems = []
    for r in c.rooms:
        if not (r.habitable and r.requires_window):
            continue
        room_windows = [w for w in c.windows if w.room_id == r.id]
        if not room_windows:
            problems.append(f"habitable room '{r.id}' has no window")
            continue
        for win in room_windows:
            host = walls.get(win.wall_id)
            if host is None or not host.is_external or r.id not in host.room_ids:
                problems.append(
                    f"window '{win.id}' of room '{r.id}' is not on an external wall of the room"
                )
    return _result("C09", "habitable rooms have at least one valid window", problems)


def _door_graph(doors: tuple[Door, ...]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for d in doors:
        graph.setdefault(d.from_space, set()).add(d.to_space)
        graph.setdefault(d.to_space, set()).add(d.from_space)
    return graph


def _reachable(graph: dict[str, set[str]], start: str, blocked_transit: frozenset[str]) -> set[str]:
    """BFS where blocked_transit nodes can be reached but not passed through."""
    seen = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node != start and node in blocked_transit:
            continue
        for nxt in graph.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def _check_no_circulation_through_bedrooms(c: Concept) -> ValidationCheck:
    graph = _door_graph(c.doors)
    bedrooms = frozenset(r.id for r in c.rooms if r.type in _BEDROOM_TYPES)
    reachable = _reachable(graph, EXTERIOR, bedrooms)
    problems = []
    for r in c.rooms:
        if r.access_via_room is not None:
            # Authored en-suite exemption: must connect directly to its bedroom.
            if r.id not in graph.get(r.access_via_room, set()):
                problems.append(f"en-suite room '{r.id}' has no door to '{r.access_via_room}'")
        elif r.id not in reachable:
            problems.append(f"room '{r.id}' is only reachable by passing through a bedroom")
    return _result("C10", "no circulation path passes through a bedroom", problems)


def _check_wet_zone(c: Concept) -> ValidationCheck:
    rooms = {r.id: r for r in c.rooms}
    problems = []
    for room_id, partner in sk.PLUMBING_PARTNERS.items():
        if room_id not in rooms:
            problems.append(f"wet room '{room_id}' missing from concept")
            continue
        shared = [w for w in c.walls if not w.is_external and set(w.room_ids) == {room_id, partner}]
        if not shared:
            problems.append(f"wet room '{room_id}' does not share a plumbing wall with '{partner}'")
    return _result("C11", "wet rooms connect to the designated wet/service zone", problems)


def _check_main_entrance(c: Concept) -> ValidationCheck:
    problems = []
    main = [d for d in c.doors if d.entrance_type == "main"]
    if len(main) != 1:
        problems.append(f"expected exactly one main entrance, got {len(main)}")
    else:
        door = main[0]
        # The tagged door itself must bridge exterior -> interior; an exterior
        # connection elsewhere in the graph does not qualify.
        if EXTERIOR not in (door.from_space, door.to_space):
            problems.append(
                f"door '{door.id}' is tagged 'main' but does not connect to the exterior"
            )
        else:
            target = door.to_space if door.from_space == EXTERIOR else door.from_space
            rooms = {r.id: r for r in c.rooms}
            room = rooms.get(target)
            if room is None or room.zone.value not in ("circulation", "public", "family"):
                problems.append(f"main entrance leads to '{target}', not family/public circulation")
    return _result("C12", "main entrance connects exterior to family/public circulation", problems)


def _check_majlis_entrance(c: Concept) -> ValidationCheck:
    problems = []
    majlis_doors = [d for d in c.doors if d.entrance_type == "majlis"]
    if len(majlis_doors) != 1:
        problems.append(f"expected exactly one majlis entrance, got {len(majlis_doors)}")
    else:
        door = majlis_doors[0]
        majlis_ids = frozenset(r.id for r in c.rooms if r.type == "majlis")
        endpoints = {door.from_space, door.to_space}
        # The tagged door itself must be the separate street entrance into the
        # majlis; reachability through other entrances does not qualify.
        if EXTERIOR not in endpoints or not (endpoints & majlis_ids):
            problems.append(
                f"door '{door.id}' is tagged 'majlis' but is not a street entrance into the majlis"
            )
        graph = _door_graph(c.doors)
        living_ids = frozenset(r.id for r in c.rooms if r.type == "family_living")
        reachable = _reachable(graph, EXTERIOR, living_ids)
        if majlis_ids and not (majlis_ids & reachable):
            problems.append("majlis unreachable without passing through the family living area")
    return _result("C13", "majlis entrance does not pass through the family living area", problems)


def _openings_on_wall(c: Concept, wall_id: str) -> list[tuple[str, float, float]]:
    spans: list[tuple[str, float, float]] = []
    for d in c.doors:
        if d.wall_id == wall_id:
            spans.append((d.id, d.position_m, d.position_m + d.width_m))
    for w in c.windows:
        if w.wall_id == wall_id:
            spans.append((w.id, w.position_m, w.position_m + w.width_m))
    return spans


def _check_opening_overlaps(c: Concept) -> ValidationCheck:
    problems = []
    for wall in c.walls:
        spans = sorted(_openings_on_wall(c, wall.id), key=lambda s: s[1])
        for (id_a, _, end_a), (id_b, start_b, _) in zip(spans, spans[1:]):
            if start_b < end_a - _TOL:
                problems.append(f"openings '{id_a}' and '{id_b}' overlap on wall '{wall.id}'")
    return _result("C14", "windows and doors do not overlap", problems)


def _check_openings_within_walls(c: Concept) -> ValidationCheck:
    walls = _walls_by_id(c)
    problems = []
    openings: list[tuple[str, str, float, float]] = [
        (d.id, d.wall_id, d.position_m, d.width_m) for d in c.doors
    ] + [(w.id, w.wall_id, w.position_m, w.width_m) for w in c.windows]
    for opening_id, wall_id, position, width in openings:
        wall = walls.get(wall_id)
        if wall is None:
            problems.append(f"opening '{opening_id}' references missing wall '{wall_id}'")
        elif position < -_TOL or position + width > wall.length_m + _TOL:
            problems.append(
                f"opening '{opening_id}' extends outside wall '{wall_id}' "
                f"({position:.2f}+{width:g} vs {wall.length_m:.2f} m)"
            )
    return _result("C15", "openings remain inside their host-wall extents", problems)


__all__ = ["validate_concept"]
