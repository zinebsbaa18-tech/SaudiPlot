"""Relationship extraction and descriptive metrics (M6A).

Adjacency comes from IFC space boundaries (spaces sharing a bounding wall);
circulation from doors filling openings in walls that bound exactly two
spaces. All metrics are descriptive only - no automatic quality claims.
"""

from __future__ import annotations

from collections import deque

from saudi_plot_design.cases.models import (
    CaseGraphs,
    CaseMetrics,
    CaseOpening,
    Entrance,
    GraphEdge,
    Space,
    SpaceType,
    Zone,
)
from saudi_plot_design.cases.semantics import HABITABLE_SPACE_TYPES, WET_SPACE_TYPES


def build_graphs(
    spaces: tuple[Space, ...],
    doors: tuple[CaseOpening, ...],
    entrances: tuple[Entrance, ...],
    wall_to_spaces: dict[str, list[str]],
    warnings: list[str],
) -> CaseGraphs:
    space_by_id = {s.ifc_global_id: s for s in spaces}

    adjacency: list[GraphEdge] = []
    seen_pairs: set[tuple[str, str]] = set()
    for wall_id, bounded in sorted(wall_to_spaces.items()):
        known = [sid for sid in bounded if sid in space_by_id]
        if len(known) == 2:
            pair = tuple(sorted(known))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                adjacency.append(GraphEdge(a=pair[0], b=pair[1], via=wall_id))
        elif len(known) > 2:
            # Without boundary-segment geometry we cannot tell which of the
            # bounded spaces actually touch each other; declaring every pair
            # adjacent would fabricate relationships (e.g. a corridor wall
            # spanning several bedrooms).
            warnings.append(
                f"wall '{wall_id}' bounds {len(known)} spaces; pairwise "
                f"adjacency via this wall is ambiguous and was not inferred"
            )

    circulation: list[GraphEdge] = []
    for door in doors:
        if door.connects_space_ids and len(door.connects_space_ids) == 2:
            a, b = sorted(door.connects_space_ids)
            circulation.append(GraphEdge(a=a, b=b, via=door.ifc_global_id))
        elif door.host_wall_id is not None and not door.is_external:
            warnings.append(
                f"door '{door.ifc_global_id}' does not connect exactly two spaces "
                f"(bounded spaces: {list(door.connects_space_ids)})"
            )

    zone_pairs: set[tuple[str, str]] = set()
    for edge in adjacency:
        za = space_by_id[edge.a].zone.value
        zb = space_by_id[edge.b].zone.value
        if za != zb:
            zone_pairs.add(tuple(sorted((za, zb))))
    zone_adjacency = tuple(GraphEdge(a=a, b=b) for a, b in sorted(zone_pairs))

    graph: dict[str, set[str]] = {}
    for edge in circulation:
        graph.setdefault(edge.a, set()).add(edge.b)
        graph.setdefault(edge.b, set()).add(edge.a)

    entrance_paths: dict[str, tuple[str, ...]] = {}
    for entrance in entrances:
        if entrance.into_space_id is None:
            entrance_paths[entrance.door_id] = ()
            continue
        entrance_paths[entrance.door_id] = _reachable(graph, entrance.into_space_id)

    guest_path = _typed_path(entrances, graph, space_by_id, "mens_majlis_entrance")
    family_path = _typed_path(entrances, graph, space_by_id, "main_family_entrance")
    service_path = _typed_path(entrances, graph, space_by_id, "service_entrance")

    wet_ids = sorted(
        s.ifc_global_id for s in spaces if SpaceType(s.space_type.value) in WET_SPACE_TYPES
    )
    adjacency_lookup: dict[str, set[str]] = {}
    for edge in adjacency:
        adjacency_lookup.setdefault(edge.a, set()).add(edge.b)
        adjacency_lookup.setdefault(edge.b, set()).add(edge.a)
    wet_groups = _cluster(wet_ids, adjacency_lookup)

    return CaseGraphs(
        room_adjacency=tuple(adjacency),
        circulation=tuple(circulation),
        zone_adjacency=zone_adjacency,
        entrance_paths=entrance_paths,
        guest_path=guest_path,
        family_path=family_path,
        service_path=service_path,
        wet_groups=wet_groups,
    )


def compute_metrics(
    spaces: tuple[Space, ...],
    walls_by_space: dict[str, int],
    entrances: tuple[Entrance, ...],
) -> CaseMetrics:
    # Spaces without a source area are excluded from sums and flagged - a
    # missing quantity must never be silently counted as zero.
    spaces_without_area = tuple(sorted(s.ifc_global_id for s in spaces if s.area_m2 is None))

    def area(space: Space) -> float:
        return space.area_m2 if space.area_m2 is not None else 0.0

    total = sum(area(s) for s in spaces)
    circulation_area = sum(area(s) for s in spaces if s.zone.value == Zone.CIRCULATION.value)
    zone_totals: dict[str, float] = {}
    for space in spaces:
        zone_totals[space.zone.value] = zone_totals.get(space.zone.value, 0.0) + area(space)
    zone_ratios = {
        zone: round(value / total, 4) if total > 0 else 0.0
        for zone, value in sorted(zone_totals.items())
    }
    habitable = [s for s in spaces if SpaceType(s.space_type.value) in HABITABLE_SPACE_TYPES]
    external_per_room = {s.ifc_global_id: walls_by_space.get(s.ifc_global_id, 0) for s in habitable}
    entrance_counts: dict[str, int] = {}
    for entrance in entrances:
        key = entrance.entrance_type.value
        entrance_counts[key] = entrance_counts.get(key, 0) + 1
    bedrooms = sum(
        1
        for s in spaces
        if s.space_type.value in (SpaceType.BEDROOM.value, SpaceType.MASTER_BEDROOM.value)
    )
    bathrooms = sum(1 for s in spaces if s.space_type.value == SpaceType.BATHROOM.value)
    return CaseMetrics(
        net_room_area_m2=round(total - circulation_area, 3),
        circulation_area_m2=round(circulation_area, 3),
        circulation_percent=round(100.0 * circulation_area / total, 2) if total > 0 else None,
        zone_area_ratios=zone_ratios,
        external_walls_per_habitable_room=dict(sorted(external_per_room.items())),
        entrance_counts=dict(sorted(entrance_counts.items())),
        bedroom_count=bedrooms,
        bathroom_count=bathrooms,
        average_room_aspect_ratio=None,  # requires space footprints (not extracted in M6A)
        spaces_without_area=spaces_without_area,
        area_metrics_complete=not spaces_without_area,
    )


def _reachable(graph: dict[str, set[str]], start: str) -> tuple[str, ...]:
    seen = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for nxt in sorted(graph.get(node, ())):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return tuple(sorted(seen))


def _typed_path(entrances, graph, space_by_id, entrance_type: str) -> tuple[str, ...]:
    # A villa can have several entrances of the same type; the aggregate path
    # is the union of what all of them reach, not just the first one found.
    reached: set[str] = set()
    for entrance in entrances:
        if entrance.entrance_type.value == entrance_type and entrance.into_space_id:
            reached.update(_reachable(graph, entrance.into_space_id))
    return tuple(sorted(reached))


def _cluster(ids: list[str], adjacency: dict[str, set[str]]) -> tuple[tuple[str, ...], ...]:
    remaining = set(ids)
    groups: list[tuple[str, ...]] = []
    while remaining:
        start = min(remaining)
        group = {start}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for neighbour in adjacency.get(node, ()):  # adjacency within wet set
                if neighbour in remaining and neighbour not in group:
                    group.add(neighbour)
                    queue.append(neighbour)
        remaining -= group
        groups.append(tuple(sorted(group)))
    return tuple(sorted(groups))
