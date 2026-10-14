"""Deterministic entrance and route semantics for M6.2.1.

The canonical plan retains ``EXTERIOR`` as a door endpoint, but this module
never treats it as a free graph node.  Internal circulation uses only real
room-to-room doors.  Any exit/re-entry alternative names both exterior doors,
applies a non-zero traversal cost, and is checked against an explicit policy.
"""

from __future__ import annotations

from collections import deque
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from saudi_plot_design.model import Concept, EXTERIOR, Zone

ROUTE_SEMANTICS_VERSION = "1.0.0"
EXTERNAL_PATH_NODE = "external_path"


class EntranceType(str, Enum):
    FAMILY_MAIN = "family_main"
    GUEST_MAJLIS = "guest_majlis"
    SERVICE = "service"
    SECONDARY = "secondary"
    UNKNOWN = "unknown"


class EntranceClassificationMethod(str, Enum):
    AUTHORED_OPENING_METADATA = "authored_opening_metadata"
    UNCLASSIFIED = "unclassified"


class RouteType(str, Enum):
    FAMILY = "family"
    GUEST = "guest"
    GUEST_WC = "guest_wc"
    SERVICE = "service"
    GENERAL = "general"


class RoutePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_id: str
    route_type: RouteType
    allow_external_circulation: bool
    allowed_external_entrance_pairs: tuple[tuple[EntranceType, EntranceType], ...] = ()
    forbidden_room_types: tuple[str, ...] = ()
    discouraged_intermediate_zones: tuple[Zone, ...] = ()
    external_traversal_cost: int = Field(default=2, ge=1)
    prefer_internal_route: bool = True


ROUTE_POLICIES: dict[RouteType, RoutePolicy] = {
    RouteType.FAMILY: RoutePolicy(
        policy_id="m621_family_v1",
        route_type=RouteType.FAMILY,
        allow_external_circulation=False,
        forbidden_room_types=("majlis", "bedroom", "master_bedroom"),
    ),
    RouteType.GUEST: RoutePolicy(
        policy_id="m621_guest_v1",
        route_type=RouteType.GUEST,
        allow_external_circulation=False,
        forbidden_room_types=("bedroom", "master_bedroom"),
        discouraged_intermediate_zones=(Zone.FAMILY, Zone.PRIVATE),
    ),
    RouteType.GUEST_WC: RoutePolicy(
        policy_id="m621_guest_wc_v1",
        route_type=RouteType.GUEST_WC,
        allow_external_circulation=False,
        forbidden_room_types=("bedroom", "master_bedroom"),
        discouraged_intermediate_zones=(Zone.FAMILY, Zone.PRIVATE),
    ),
    RouteType.SERVICE: RoutePolicy(
        policy_id="m621_service_v1",
        route_type=RouteType.SERVICE,
        allow_external_circulation=True,
        allowed_external_entrance_pairs=((EntranceType.SERVICE, EntranceType.SERVICE),),
        forbidden_room_types=("bedroom", "master_bedroom", "majlis"),
        discouraged_intermediate_zones=(Zone.PUBLIC, Zone.FAMILY),
    ),
    RouteType.GENERAL: RoutePolicy(
        policy_id="m621_general_v1",
        route_type=RouteType.GENERAL,
        allow_external_circulation=False,
    ),
}


class EntranceInventoryItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    door_id: str
    internal_room_id: str | None
    host_wall_id: str
    entrance_type: EntranceType
    classification_method: EntranceClassificationMethod
    confidence: float = Field(ge=0, le=1)
    evidence: tuple[str, ...]
    requires_review: bool


class RouteEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    route_type: RouteType
    policy_id: str
    start_room_id: str
    target_room_id: str
    path_kind: str  # internal | entrance | external_exit_reentry | unavailable
    available: bool
    allowed: bool
    requires_review: bool
    room_sequence: tuple[str, ...]
    display_sequence: tuple[str, ...]
    door_ids: tuple[str, ...]
    internal_door_steps: int = Field(ge=0)
    external_door_steps: int = Field(ge=0)
    external_traversal_steps: int = Field(ge=0)
    total_cost: int | None = Field(default=None, ge=0)
    uses_external_path: bool
    exit_door_id: str | None = None
    reentry_door_id: str | None = None
    external_path_classification: str | None = None
    inappropriate_room_ids: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


class RouteAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    semantics_version: str = ROUTE_SEMANTICS_VERSION
    route_type: RouteType
    policy: RoutePolicy
    internal_route: RouteEvidence | None
    external_routes: tuple[RouteEvidence, ...]
    preferred_route: RouteEvidence


class EntranceSeparationEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    family_entrance_door_ids: tuple[str, ...]
    guest_entrance_door_ids: tuple[str, ...]
    unknown_entrance_door_ids: tuple[str, ...]
    distinct_real_entrance_doors: bool
    shared_internal_room_ids: tuple[str, ...]
    separation_supported: bool
    requires_review: bool
    family_route: RouteEvidence
    guest_route: RouteEvidence
    guest_wc_route: RouteEvidence
    evidence: tuple[str, ...]


class RoutePenaltySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    disallowed_external_routes: int = Field(ge=0)
    external_guest_wc_detours: int = Field(ge=0)
    unknown_entrances_used_as_dedicated: int = Field(ge=0)
    unnecessary_exit_reentry_routes: int = Field(ge=0)
    selected_external_routes: int = Field(ge=0)
    external_route_extra_cost: int = Field(ge=0)
    total_penalty: int = Field(ge=0)
    details: tuple[str, ...]


class ConceptRouteAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    semantics_version: str = ROUTE_SEMANTICS_VERSION
    entrance_inventory: tuple[EntranceInventoryItem, ...]
    family_route: RouteEvidence
    guest_route: RouteEvidence
    service_route: RouteAnalysis
    guest_wc_route: RouteAnalysis
    separation: EntranceSeparationEvidence
    penalties: RoutePenaltySummary


_AUTHORED_ENTRANCE_TYPES = {
    "main": EntranceType.FAMILY_MAIN,
    "family_main": EntranceType.FAMILY_MAIN,
    "majlis": EntranceType.GUEST_MAJLIS,
    "guest_majlis": EntranceType.GUEST_MAJLIS,
    "service": EntranceType.SERVICE,
    "secondary": EntranceType.SECONDARY,
}


def classify_entrances(concept: Concept) -> tuple[EntranceInventoryItem, ...]:
    """Classify real exterior doors only; wall contact never creates an entrance."""
    rooms = {room.id: room for room in concept.rooms}
    walls = {wall.id: wall for wall in concept.walls}
    result: list[EntranceInventoryItem] = []
    for door in sorted(concept.doors, key=lambda item: item.id):
        if EXTERIOR not in (door.from_space, door.to_space):
            continue
        internal = door.to_space if door.from_space == EXTERIOR else door.from_space
        wall = walls.get(door.wall_id)
        recognized = _AUTHORED_ENTRANCE_TYPES.get(door.entrance_type or "")
        host_valid = bool(
            wall
            and wall.is_external
            and internal in rooms
            and internal in wall.room_ids
            and {door.from_space, door.to_space} == {EXTERIOR, internal}
            and door.position_m >= -1e-6
            and door.position_m + door.width_m <= wall.length_m + 1e-6
        )
        entrance_type = recognized or EntranceType.UNKNOWN
        method = (
            EntranceClassificationMethod.AUTHORED_OPENING_METADATA
            if recognized
            else EntranceClassificationMethod.UNCLASSIFIED
        )
        evidence = [
            f"door {door.id} connects {internal} to {EXTERIOR}",
            f"host wall {door.wall_id}: {'valid external host' if host_valid else 'invalid or unresolved external host'}",
            f"authored entrance_type: {door.entrance_type or 'none'}",
        ]
        if not recognized:
            evidence.append("no recognized authored entrance intent; classification withheld")
        result.append(
            EntranceInventoryItem(
                door_id=door.id,
                internal_room_id=internal if internal in rooms else None,
                host_wall_id=door.wall_id,
                entrance_type=entrance_type,
                classification_method=method,
                confidence=1.0 if recognized and host_valid else 0.0,
                evidence=tuple(evidence),
                requires_review=not (recognized and host_valid),
            )
        )
    return tuple(result)


def internal_door_graph(concept: Concept) -> dict[str, tuple[str, ...]]:
    rooms = {room.id for room in concept.rooms}
    graph: dict[str, set[str]] = {room_id: set() for room_id in rooms}
    for door in sorted(concept.doors, key=lambda item: item.id):
        if EXTERIOR in (door.from_space, door.to_space):
            continue
        if door.from_space in rooms and door.to_space in rooms:
            graph[door.from_space].add(door.to_space)
            graph[door.to_space].add(door.from_space)
    return {node: tuple(sorted(neighbors)) for node, neighbors in sorted(graph.items())}


def shortest_internal_path(
    concept: Concept,
    start: str,
    target: str,
    *,
    forbidden_room_ids: frozenset[str] = frozenset(),
) -> tuple[str, ...] | None:
    graph = internal_door_graph(concept)
    if start not in graph or target not in graph:
        return None
    if start in forbidden_room_ids or target in forbidden_room_ids:
        return None
    queue: deque[tuple[str, tuple[str, ...]]] = deque([(start, (start,))])
    visited = {start}
    while queue:
        node, path = queue.popleft()
        if node == target:
            return path
        for neighbor in graph.get(node, ()):
            if neighbor not in visited and neighbor not in forbidden_room_ids:
                visited.add(neighbor)
                queue.append((neighbor, (*path, neighbor)))
    return None


def _door_id_between(concept: Concept, a: str, b: str) -> str:
    return min(
        door.id
        for door in concept.doors
        if EXTERIOR not in (door.from_space, door.to_space)
        and {door.from_space, door.to_space} == {a, b}
    )


def _door_ids_for_path(concept: Concept, path: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_door_id_between(concept, a, b) for a, b in zip(path, path[1:]))


def _display_internal_path(path: tuple[str, ...], door_ids: tuple[str, ...]) -> tuple[str, ...]:
    if not path:
        return ()
    result = [f"room:{path[0]}"]
    for door_id, room_id in zip(door_ids, path[1:]):
        result.extend((f"door:{door_id}", f"room:{room_id}"))
    return tuple(result)


def _route_room_flags(
    concept: Concept, path: tuple[str, ...], policy: RoutePolicy
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    rooms = {room.id: room for room in concept.rooms}
    intermediate = [rooms[node] for node in path[1:-1] if node in rooms]
    forbidden = tuple(
        sorted(room.id for room in intermediate if room.type in policy.forbidden_room_types)
    )
    discouraged = tuple(
        sorted(
            room.id
            for room in intermediate
            if room.zone in policy.discouraged_intermediate_zones and room.id not in forbidden
        )
    )
    return forbidden, discouraged


def _internal_route(
    concept: Concept,
    start: str,
    target: str,
    policy: RoutePolicy,
) -> RouteEvidence | None:
    path = shortest_internal_path(concept, start, target)
    if path is None:
        return None
    door_ids = _door_ids_for_path(concept, path)
    forbidden, discouraged = _route_room_flags(concept, path, policy)
    reasons = []
    if forbidden:
        reasons.append("route crosses forbidden rooms: " + ", ".join(forbidden))
    if discouraged:
        reasons.append("route crosses discouraged zones at: " + ", ".join(discouraged))
    return RouteEvidence(
        route_type=policy.route_type,
        policy_id=policy.policy_id,
        start_room_id=start,
        target_room_id=target,
        path_kind="internal",
        available=True,
        allowed=not forbidden,
        requires_review=False,
        room_sequence=path,
        display_sequence=_display_internal_path(path, door_ids),
        door_ids=door_ids,
        internal_door_steps=len(door_ids),
        external_door_steps=0,
        external_traversal_steps=0,
        total_cost=len(door_ids),
        uses_external_path=False,
        inappropriate_room_ids=tuple(sorted((*forbidden, *discouraged))),
        evidence=(f"internal door route: {' -> '.join(path)}",),
        reasons=tuple(reasons),
    )


def _external_routes(
    concept: Concept,
    start: str,
    target: str,
    policy: RoutePolicy,
) -> tuple[RouteEvidence, ...]:
    entrances = classify_entrances(concept)
    routes: list[RouteEvidence] = []
    for exit_item in entrances:
        # An exterior alternative must leave through a real door on the route's
        # current start room; do not roam internally to an arbitrary exit.
        if exit_item.internal_room_id != start:
            continue
        prefix = (start,)
        for reentry_item in entrances:
            if reentry_item.door_id == exit_item.door_id or reentry_item.internal_room_id is None:
                continue
            suffix = shortest_internal_path(concept, reentry_item.internal_room_id, target)
            if suffix is None or start in suffix:
                continue
            pair = (exit_item.entrance_type, reentry_item.entrance_type)
            pair_allowed = (
                policy.allow_external_circulation
                and pair in policy.allowed_external_entrance_pairs
                and not exit_item.requires_review
                and not reentry_item.requires_review
            )
            combined_rooms = (*prefix, *suffix)
            forbidden, discouraged = _route_room_flags(concept, tuple(combined_rooms), policy)
            allowed = pair_allowed and not forbidden
            if pair == (EntranceType.SERVICE, EntranceType.SERVICE) and allowed:
                classification = "supported_service_external_route"
            elif pair == (EntranceType.SERVICE, EntranceType.SERVICE):
                classification = "unsupported_service_external_route"
            else:
                classification = "disallowed_external_exit_reentry"
            prefix_doors = _door_ids_for_path(concept, prefix)
            suffix_doors = _door_ids_for_path(concept, suffix)
            door_ids = (
                *prefix_doors,
                exit_item.door_id,
                reentry_item.door_id,
                *suffix_doors,
            )
            internal_steps = len(prefix_doors) + len(suffix_doors)
            total_cost = internal_steps + 2 + policy.external_traversal_cost
            display = [*_display_internal_path(prefix, prefix_doors)]
            display.extend(
                (
                    f"exit_door:{exit_item.door_id}",
                    EXTERNAL_PATH_NODE,
                    f"reentry_door:{reentry_item.door_id}",
                )
            )
            suffix_display = _display_internal_path(suffix, suffix_doors)
            if suffix_display:
                display.extend(suffix_display)
            reasons = []
            if not policy.allow_external_circulation:
                reasons.append(f"{policy.route_type.value} policy disallows exit/re-entry")
            elif pair not in policy.allowed_external_entrance_pairs:
                reasons.append(
                    "entrance pair not allowed: "
                    f"{exit_item.entrance_type.value}->{reentry_item.entrance_type.value}"
                )
            if exit_item.requires_review or reentry_item.requires_review:
                reasons.append("unknown or unsupported entrance classification")
            if forbidden:
                reasons.append("route crosses forbidden rooms: " + ", ".join(forbidden))
            if discouraged:
                reasons.append("route crosses discouraged zones at: " + ", ".join(discouraged))
            routes.append(
                RouteEvidence(
                    route_type=policy.route_type,
                    policy_id=policy.policy_id,
                    start_room_id=start,
                    target_room_id=target,
                    path_kind="external_exit_reentry",
                    available=True,
                    allowed=allowed,
                    requires_review=True,
                    room_sequence=(*prefix, EXTERNAL_PATH_NODE, *suffix),
                    display_sequence=tuple(display),
                    door_ids=tuple(door_ids),
                    internal_door_steps=internal_steps,
                    external_door_steps=2,
                    external_traversal_steps=policy.external_traversal_cost,
                    total_cost=total_cost,
                    uses_external_path=True,
                    exit_door_id=exit_item.door_id,
                    reentry_door_id=reentry_item.door_id,
                    external_path_classification=classification,
                    inappropriate_room_ids=tuple(sorted((*forbidden, *discouraged))),
                    evidence=(
                        f"exit {exit_item.internal_room_id} through {exit_item.door_id}",
                        f"external traversal cost {policy.external_traversal_cost}",
                        f"re-enter {reentry_item.internal_room_id} through {reentry_item.door_id}",
                        "external site-path geometry is unavailable; route requires review",
                    ),
                    reasons=tuple(reasons),
                )
            )
    return tuple(
        sorted(
            routes,
            key=lambda item: (
                not item.allowed,
                item.total_cost if item.total_cost is not None else 10**9,
                item.exit_door_id or "",
                item.reentry_door_id or "",
                item.room_sequence,
            ),
        )
    )


def _unavailable_route(
    start: str,
    target: str,
    policy: RoutePolicy,
    reason: str,
    *,
    requires_review: bool = False,
) -> RouteEvidence:
    return RouteEvidence(
        route_type=policy.route_type,
        policy_id=policy.policy_id,
        start_room_id=start,
        target_room_id=target,
        path_kind="unavailable",
        available=False,
        allowed=False,
        requires_review=requires_review,
        room_sequence=(),
        display_sequence=(),
        door_ids=(),
        internal_door_steps=0,
        external_door_steps=0,
        external_traversal_steps=0,
        total_cost=None,
        uses_external_path=False,
        evidence=(reason,),
        reasons=(reason,),
    )


def analyze_room_route(
    concept: Concept,
    start: str,
    target: str,
    route_type: RouteType,
    *,
    policy: RoutePolicy | None = None,
) -> RouteAnalysis:
    policy = policy or ROUTE_POLICIES[route_type]
    internal = _internal_route(concept, start, target, policy)
    external = _external_routes(concept, start, target, policy)
    allowed_external = tuple(route for route in external if route.allowed)
    if internal is not None and internal.allowed and policy.prefer_internal_route:
        preferred = internal
    elif allowed_external:
        preferred = allowed_external[0]
    elif internal is not None:
        preferred = internal
    elif external:
        preferred = external[0]
    else:
        preferred = _unavailable_route(start, target, policy, "no explicit route available")
    return RouteAnalysis(
        route_type=route_type,
        policy=policy,
        internal_route=internal,
        external_routes=external,
        preferred_route=preferred,
    )


def route_from_entrance(
    concept: Concept,
    entrance_type: EntranceType,
    target_room_id: str,
    route_type: RouteType,
) -> RouteEvidence:
    policy = ROUTE_POLICIES[route_type]
    candidates: list[RouteEvidence] = []
    for entrance in classify_entrances(concept):
        if (
            entrance.entrance_type is not entrance_type
            or entrance.requires_review
            or entrance.internal_room_id is None
        ):
            continue
        internal = _internal_route(concept, entrance.internal_room_id, target_room_id, policy)
        if internal is None:
            continue
        candidates.append(
            internal.model_copy(
                update={
                    "start_room_id": entrance.internal_room_id,
                    "path_kind": "entrance",
                    "display_sequence": (
                        "outside",
                        f"entrance_door:{entrance.door_id}",
                        *internal.display_sequence,
                    ),
                    "door_ids": (entrance.door_id, *internal.door_ids),
                    "external_door_steps": 1,
                    "total_cost": (internal.total_cost or 0) + 1,
                    "evidence": (
                        f"{entrance_type.value} entrance door {entrance.door_id} enters {entrance.internal_room_id}",
                        *internal.evidence,
                    ),
                }
            )
        )
    if candidates:
        return min(
            candidates,
            key=lambda item: (
                not item.allowed,
                item.total_cost if item.total_cost is not None else 10**9,
                item.door_ids,
            ),
        )
    unknown = tuple(
        item.door_id
        for item in classify_entrances(concept)
        if item.entrance_type is EntranceType.UNKNOWN
    )
    reason = f"no supported {entrance_type.value} entrance reaches {target_room_id}"
    if unknown:
        reason += f"; unknown entrances require review: {', '.join(unknown)}"
    supported_start = next(
        (
            item.internal_room_id
            for item in classify_entrances(concept)
            if item.entrance_type is entrance_type
            and not item.requires_review
            and item.internal_room_id is not None
        ),
        "",
    )
    return _unavailable_route(
        supported_start,
        target_room_id,
        policy,
        reason,
        requires_review=bool(unknown),
    )


def reachable_rooms_from_external_doors(concept: Concept) -> frozenset[str]:
    graph = internal_door_graph(concept)
    starts = sorted(
        {
            item.internal_room_id
            for item in classify_entrances(concept)
            if item.internal_room_id is not None
        }
    )
    reached = set(starts)
    queue = deque(starts)
    while queue:
        node = queue.popleft()
        for neighbor in graph.get(node, ()):
            if neighbor not in reached:
                reached.add(neighbor)
                queue.append(neighbor)
    return frozenset(reached)


def entrance_separation_evidence(concept: Concept) -> EntranceSeparationEvidence:
    inventory = classify_entrances(concept)
    family_ids = tuple(
        item.door_id
        for item in inventory
        if item.entrance_type is EntranceType.FAMILY_MAIN and not item.requires_review
    )
    guest_ids = tuple(
        item.door_id
        for item in inventory
        if item.entrance_type is EntranceType.GUEST_MAJLIS and not item.requires_review
    )
    unknown_ids = tuple(
        item.door_id for item in inventory if item.entrance_type is EntranceType.UNKNOWN
    )
    family_route = route_from_entrance(
        concept, EntranceType.FAMILY_MAIN, "family_living", RouteType.FAMILY
    )
    guest_route = route_from_entrance(concept, EntranceType.GUEST_MAJLIS, "majlis", RouteType.GUEST)
    guest_wc_analysis = analyze_room_route(concept, "majlis", "guest_wc", RouteType.GUEST_WC)
    guest_wc = guest_wc_analysis.preferred_route
    family_rooms = {
        node
        for node in family_route.room_sequence
        if node not in {EXTERNAL_PATH_NODE, family_route.target_room_id}
    }
    guest_rooms = {
        node
        for node in guest_wc.room_sequence
        if node not in {EXTERNAL_PATH_NODE, "majlis", "guest_wc"}
    }
    shared = tuple(sorted(family_rooms & guest_rooms))
    distinct = bool(family_ids and guest_ids and set(family_ids).isdisjoint(guest_ids))
    supported = bool(
        distinct
        and family_route.available
        and family_route.allowed
        and guest_route.available
        and guest_route.allowed
        and guest_wc.available
        and guest_wc.allowed
        and not guest_wc.uses_external_path
        and not shared
    )
    requires_review = bool(
        unknown_ids
        or guest_wc.requires_review
        or family_route.requires_review
        or guest_route.requires_review
    )
    evidence = (
        f"family entrance doors: {', '.join(family_ids) or 'none'}",
        f"guest entrance doors: {', '.join(guest_ids) or 'none'}",
        f"shared internal guest/family rooms: {', '.join(shared) or 'none'}",
        f"guest WC route kind: {guest_wc.path_kind}; allowed={guest_wc.allowed}",
    )
    return EntranceSeparationEvidence(
        family_entrance_door_ids=family_ids,
        guest_entrance_door_ids=guest_ids,
        unknown_entrance_door_ids=unknown_ids,
        distinct_real_entrance_doors=distinct,
        shared_internal_room_ids=shared,
        separation_supported=supported,
        requires_review=requires_review,
        family_route=family_route,
        guest_route=guest_route,
        guest_wc_route=guest_wc,
        evidence=evidence,
    )


def route_penalty_summary(concept: Concept) -> RoutePenaltySummary:
    inventory = classify_entrances(concept)
    guest_wc = analyze_room_route(concept, "majlis", "guest_wc", RouteType.GUEST_WC)
    service = analyze_room_route(concept, "kitchen", "maid_room", RouteType.SERVICE)
    separation = entrance_separation_evidence(concept)
    preferred_guest = guest_wc.preferred_route
    selected = (preferred_guest, service.preferred_route)
    disallowed_external = sum(route.uses_external_path and not route.allowed for route in selected)
    guest_detours = int(preferred_guest.uses_external_path)
    unknown_used = int(
        (not separation.family_entrance_door_ids or not separation.guest_entrance_door_ids)
        and any(item.entrance_type is EntranceType.UNKNOWN for item in inventory)
    )
    unnecessary = sum(
        route.uses_external_path and (not route.allowed or route.external_traversal_steps > 0)
        for route in selected
    )
    selected_external = sum(route.uses_external_path for route in selected)
    extra_cost = sum(
        route.external_door_steps + route.external_traversal_steps
        for route in selected
        if route.uses_external_path
    )
    total = (
        disallowed_external * 100
        + guest_detours * 50
        + unknown_used * 30
        + unnecessary * 20
        + extra_cost
    )
    details = []
    if preferred_guest.uses_external_path:
        details.append(
            "guest WC route uses exit/re-entry "
            f"{preferred_guest.exit_door_id}->{preferred_guest.reentry_door_id}"
        )
    if service.preferred_route.uses_external_path:
        details.append(
            "preferred service route uses external circulation "
            f"{service.preferred_route.exit_door_id}->{service.preferred_route.reentry_door_id}"
        )
    if unknown_used:
        details.append("unknown entrance classification would be needed for dedicated separation")
    return RoutePenaltySummary(
        disallowed_external_routes=disallowed_external,
        external_guest_wc_detours=guest_detours,
        unknown_entrances_used_as_dedicated=unknown_used,
        unnecessary_exit_reentry_routes=unnecessary,
        selected_external_routes=selected_external,
        external_route_extra_cost=extra_cost,
        total_penalty=total,
        details=tuple(details),
    )


def concept_route_audit(concept: Concept) -> ConceptRouteAudit:
    family = route_from_entrance(
        concept, EntranceType.FAMILY_MAIN, "family_living", RouteType.FAMILY
    )
    guest = route_from_entrance(concept, EntranceType.GUEST_MAJLIS, "majlis", RouteType.GUEST)
    service = analyze_room_route(concept, "kitchen", "maid_room", RouteType.SERVICE)
    guest_wc = analyze_room_route(concept, "majlis", "guest_wc", RouteType.GUEST_WC)
    return ConceptRouteAudit(
        entrance_inventory=classify_entrances(concept),
        family_route=family,
        guest_route=guest,
        service_route=service,
        guest_wc_route=guest_wc,
        separation=entrance_separation_evidence(concept),
        penalties=route_penalty_summary(concept),
    )


__all__ = [
    "ConceptRouteAudit",
    "EntranceClassificationMethod",
    "EntranceInventoryItem",
    "EntranceSeparationEvidence",
    "EntranceType",
    "EXTERNAL_PATH_NODE",
    "ROUTE_POLICIES",
    "ROUTE_SEMANTICS_VERSION",
    "RouteAnalysis",
    "RouteEvidence",
    "RoutePenaltySummary",
    "RoutePolicy",
    "RouteType",
    "analyze_room_route",
    "classify_entrances",
    "concept_route_audit",
    "entrance_separation_evidence",
    "internal_door_graph",
    "reachable_rooms_from_external_doors",
    "route_from_entrance",
    "route_penalty_summary",
    "shortest_internal_path",
]
