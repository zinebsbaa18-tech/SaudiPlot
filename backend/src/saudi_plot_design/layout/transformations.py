"""The five explicit, ordered M6.2 Compact 3BR transformations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from saudi_plot_design.layout.geometry import (
    OpeningIntent,
    local_rect_to_world,
    opening_intents,
    rebuild_concept,
    replace_intent,
    world_rect_to_local,
    world_side_from_local,
)
from saudi_plot_design.layout.models import GeometryChange, TransformationAudit
from saudi_plot_design.model import Concept, EXTERIOR, Rect
from saudi_plot_design.route_semantics import EntranceType, classify_entrances


@dataclass(frozen=True)
class LayoutTransformation:
    transformation_id: str
    description: str
    apply: Callable[[Concept, str], tuple[Concept, TransformationAudit]]


def _changed_objects(before: Concept, after: Concept) -> tuple[GeometryChange, ...]:
    changes: list[GeometryChange] = []
    for object_type, before_items, after_items in (
        ("room", before.rooms, after.rooms),
        ("door", before.doors, after.doors),
        ("window", before.windows, after.windows),
    ):
        old = {item.id: item.model_dump(mode="json") for item in before_items}
        new = {item.id: item.model_dump(mode="json") for item in after_items}
        for object_id in sorted(set(old) | set(new)):
            if old.get(object_id) != new.get(object_id):
                changes.append(
                    GeometryChange(
                        object_type=object_type,
                        object_id=object_id,
                        before=old.get(object_id),
                        after=new.get(object_id),
                    )
                )
    return tuple(changes)


def _audit(
    transformation_id: str, description: str, before: Concept, after: Concept
) -> TransformationAudit:
    changes = _changed_objects(before, after)
    return TransformationAudit(
        transformation_id=transformation_id,
        description=description,
        affected_room_ids=tuple(
            change.object_id for change in changes if change.object_type == "room"
        ),
        affected_opening_ids=tuple(
            change.object_id for change in changes if change.object_type in {"door", "window"}
        ),
        changes=changes,
    )


def _patched_rect(
    concept: Concept,
    room_id: str,
    *,
    min_x: float | None = None,
    min_y: float | None = None,
    max_x: float | None = None,
    max_y: float | None = None,
) -> Rect:
    room = next(room for room in concept.rooms if room.id == room_id)
    local = world_rect_to_local(concept, room.rect)
    return local_rect_to_world(
        concept,
        Rect(
            min_x=local.min_x if min_x is None else min_x,
            min_y=local.min_y if min_y is None else min_y,
            max_x=local.max_x if max_x is None else max_x,
            max_y=local.max_y if max_y is None else max_y,
        ),
    )


def _rebuild(
    before: Concept,
    candidate_id: str,
    room_updates: dict[str, Rect],
    intents: tuple[OpeningIntent, ...] | None = None,
) -> Concept:
    room_rects = {room.id: room.rect for room in before.rooms}
    room_rects.update(room_updates)
    return rebuild_concept(
        before,
        room_rects,
        opening_intents(before) if intents is None else intents,
        concept_id=f"{before.skeleton_id}-v{before.skeleton_version}-m62-{candidate_id}",
    )


def _front_room_rebalance(before: Concept, candidate_id: str):
    tid = "M62-T01-front-room-rebalance"
    description = "Move the front service partitions to improve entry and kitchen clear dimensions."
    after = _rebuild(
        before,
        candidate_id,
        {
            "entry": _patched_rect(before, "entry", min_x=5.7, max_x=7.56),
            "guest_wc": _patched_rect(before, "guest_wc", min_x=7.56, max_x=9.05),
            "kitchen": _patched_rect(before, "kitchen", min_x=9.05, max_x=13.5),
        },
    )
    return after, _audit(tid, description, before, after)


def _wet_service_rebalance(before: Concept, candidate_id: str):
    tid = "M62-T02-wet-service-rebalance"
    description = (
        "Resize adjacent wet/service rooms while preserving their combined authored bands."
    )
    after = _rebuild(
        before,
        candidate_id,
        {
            "master_bath": _patched_rect(before, "master_bath", max_x=2.7),
            "laundry": _patched_rect(before, "laundry", min_x=2.7),
            "shared_bath": _patched_rect(before, "shared_bath", max_y=9.1),
            "maid_room": _patched_rect(before, "maid_room", max_y=9.1),
            "bedroom_2": _patched_rect(before, "bedroom_2", min_y=9.1),
        },
    )
    return after, _audit(tid, description, before, after)


def _corridor_reproportion(before: Concept, candidate_id: str):
    tid = "M62-T03-corridor-reproportion"
    description = (
        "Reproportion the corridor and its adjacent rooms to remove its extreme aspect ratio."
    )
    after = _rebuild(
        before,
        candidate_id,
        {
            "corridor": _patched_rect(before, "corridor", max_x=7.9),
            "dining": _patched_rect(before, "dining", min_x=7.9),
            "shared_bath": _patched_rect(before, "shared_bath", min_x=7.9, max_x=9.4),
            "maid_room": _patched_rect(before, "maid_room", min_x=9.4),
            "bedroom_2": _patched_rect(before, "bedroom_2", min_x=7.9),
            "bedroom_3": _patched_rect(before, "bedroom_3", min_x=7.9),
        },
    )
    return after, _audit(tid, description, before, after)


def _direct_service_access(before: Concept, candidate_id: str):
    tid = "M62-T04-direct-service-access"
    description = (
        "Add classified kitchen and maid exterior service doors as a reviewable external "
        "circulation alternative, not direct internal access."
    )
    intents = opening_intents(before)
    if any(intent.id in {"d_kitchen_service", "d_maid_service"} for intent in intents):
        raise ValueError("direct service access already exists")
    side = world_side_from_local(before, "E")
    intents = tuple(
        [*intents]
        + [
            OpeningIntent(
                kind="door",
                id="d_kitchen_service",
                from_space=EXTERIOR,
                to_space="kitchen",
                external_side=side,
                center_fraction=0.5,
                width_m=0.9,
                entrance_type="service",
            ),
            OpeningIntent(
                kind="door",
                id="d_maid_service",
                from_space=EXTERIOR,
                to_space="maid_room",
                external_side=side,
                center_fraction=0.21,
                width_m=0.8,
                entrance_type="service",
            ),
        ]
    )
    intents = replace_intent(intents, "w_maid", center_fraction=0.75)
    after = _rebuild(before, candidate_id, {}, intents)
    service_entrances = {
        item.door_id
        for item in classify_entrances(after)
        if item.entrance_type is EntranceType.SERVICE and not item.requires_review
    }
    if service_entrances != {"d_kitchen_service", "d_maid_service"}:
        raise ValueError("service doors do not have valid authored exterior entrance geometry")
    return after, _audit(tid, description, before, after)


def _separate_guest_family_route(before: Concept, candidate_id: str):
    tid = "M62-T05-separate-guest-family-route"
    description = (
        "Remove the majlis-to-entry door only when distinct authored guest and family exterior "
        "entrances exist; this separates entry paths but does not prove guest-WC circulation."
    )
    inventory = classify_entrances(before)
    family = {
        item.door_id
        for item in inventory
        if item.entrance_type is EntranceType.FAMILY_MAIN and not item.requires_review
    }
    guest = {
        item.door_id
        for item in inventory
        if item.entrance_type is EntranceType.GUEST_MAJLIS and not item.requires_review
    }
    if not family or not guest or not family.isdisjoint(guest):
        raise ValueError(
            "guest/family separation requires distinct valid authored family and guest exterior doors"
        )
    intents = tuple(intent for intent in opening_intents(before) if intent.id != "d_majlis_entry")
    if len(intents) == len(opening_intents(before)):
        raise ValueError("majlis-to-entry door does not exist")
    after = _rebuild(before, candidate_id, {}, intents)
    return after, _audit(tid, description, before, after)


TRANSFORMATIONS: tuple[LayoutTransformation, ...] = (
    LayoutTransformation(
        "M62-T01-front-room-rebalance",
        "Move the front service partitions to improve entry and kitchen clear dimensions.",
        _front_room_rebalance,
    ),
    LayoutTransformation(
        "M62-T02-wet-service-rebalance",
        "Resize adjacent wet/service rooms while preserving their combined authored bands.",
        _wet_service_rebalance,
    ),
    LayoutTransformation(
        "M62-T03-corridor-reproportion",
        "Reproportion the corridor and adjacent rooms.",
        _corridor_reproportion,
    ),
    LayoutTransformation(
        "M62-T04-direct-service-access",
        "Add classified exterior service doors as a reviewable external route alternative.",
        _direct_service_access,
    ),
    LayoutTransformation(
        "M62-T05-separate-guest-family-route",
        "Remove the internal guest/family link only when distinct authored exterior entrances exist.",
        _separate_guest_family_route,
    ),
)


__all__ = ["LayoutTransformation", "TRANSFORMATIONS"]
