"""Reviewable architectural classification (M6A).

Nothing is silently guessed: every inference records method, confidence,
source, and reviewer status (always ``requires_review`` until a human
reviewer confirms). A manual corrections file overrides inferences with
confidence 1.0 and method ``manual_correction``.
"""

from __future__ import annotations

import json
from pathlib import Path

from saudi_plot_design.cases.models import Classification, EntranceType, SpaceType, Zone
from saudi_plot_design.model import SpdInputError

# Keyword tables (lowercase substring match; Arabic + English). Order matters:
# first hit wins, more specific entries first - e.g. bathroom/maid/laundry
# must precede the generic master/bedroom rules so "Master Bathroom" is a
# bathroom and "Maid Bedroom" is a maid room.
_SPACE_KEYWORDS: tuple[tuple[SpaceType, tuple[str, ...]], ...] = (
    (SpaceType.WOMENS_MAJLIS, ("women majlis", "womens majlis", "مجلس نساء", "مجلس حريم")),
    (SpaceType.MENS_MAJLIS, ("majlis", "مجلس")),
    (SpaceType.BATHROOM, ("bath", "wc", "toilet", "حمام", "دورة مياه")),
    (SpaceType.MAID_ROOM, ("maid", "خادمة", "عاملة")),
    (SpaceType.LAUNDRY, ("laundry", "غسيل")),
    (SpaceType.MASTER_BEDROOM, ("master", "رئيسية", "نوم رئيسي")),
    (SpaceType.BEDROOM, ("bedroom", "bed room", "نوم")),
    (SpaceType.KITCHEN, ("kitchen", "مطبخ")),
    (SpaceType.DINING, ("dining", "طعام")),
    (SpaceType.LIVING, ("living", "family", "صالة", "معيشة")),
    (SpaceType.STORAGE, ("storage", "store", "مستودع", "تخزين")),
    (SpaceType.CORRIDOR, ("corridor", "hall", "lobby", "entry", "ممر", "مدخل", "بهو")),
    (SpaceType.STAIR, ("stair", "درج", "سلم")),
    (SpaceType.ELEVATOR, ("elevator", "lift", "مصعد")),
)

_SPACE_ZONE: dict[SpaceType, Zone] = {
    SpaceType.MENS_MAJLIS: Zone.GUEST_PUBLIC,
    SpaceType.WOMENS_MAJLIS: Zone.GUEST_PUBLIC,
    SpaceType.LIVING: Zone.FAMILY,
    SpaceType.DINING: Zone.FAMILY,
    SpaceType.KITCHEN: Zone.SERVICE,
    SpaceType.MASTER_BEDROOM: Zone.PRIVATE_BEDROOMS,
    SpaceType.BEDROOM: Zone.PRIVATE_BEDROOMS,
    SpaceType.BATHROOM: Zone.WET,
    SpaceType.MAID_ROOM: Zone.SERVICE,
    SpaceType.LAUNDRY: Zone.WET,
    SpaceType.STORAGE: Zone.SERVICE,
    SpaceType.CORRIDOR: Zone.CIRCULATION,
    SpaceType.STAIR: Zone.CIRCULATION,
    SpaceType.ELEVATOR: Zone.CIRCULATION,
    SpaceType.OTHER: Zone.UNKNOWN,
    SpaceType.UNKNOWN: Zone.UNKNOWN,
}

WET_SPACE_TYPES = frozenset({SpaceType.BATHROOM, SpaceType.LAUNDRY, SpaceType.KITCHEN})
HABITABLE_SPACE_TYPES = frozenset(
    {
        SpaceType.MENS_MAJLIS,
        SpaceType.WOMENS_MAJLIS,
        SpaceType.LIVING,
        SpaceType.DINING,
        SpaceType.KITCHEN,
        SpaceType.MASTER_BEDROOM,
        SpaceType.BEDROOM,
        SpaceType.MAID_ROOM,
    }
)


def classify_space(name: str, long_name: str | None) -> tuple[Classification, Classification]:
    """Space type + zone from name keywords - or an honest 'unknown'."""
    text = f"{name} {long_name or ''}".lower()
    for space_type, keywords in _SPACE_KEYWORDS:
        for keyword in keywords:
            if keyword in text:
                confidence = 0.9 if len(keyword) > 3 else 0.6
                type_classification = Classification(
                    value=space_type.value,
                    method="name_keyword",
                    confidence=confidence,
                    source=f"name='{name}' matched '{keyword}'",
                )
                zone = _SPACE_ZONE[space_type]
                zone_classification = Classification(
                    value=zone.value,
                    method="derived_from_space_type",
                    confidence=confidence,
                    source=f"space_type={space_type.value}",
                )
                return type_classification, zone_classification
    unknown = Classification(
        value=SpaceType.UNKNOWN.value,
        method="unclassified",
        confidence=0.0,
        source=f"name='{name}' matched no keyword",
    )
    unknown_zone = Classification(
        value=Zone.UNKNOWN.value, method="unclassified", confidence=0.0, source="no space type"
    )
    return unknown, unknown_zone


def classify_entrance(into_space_type: str | None) -> Classification:
    mapping = {
        SpaceType.MENS_MAJLIS.value: EntranceType.MENS_MAJLIS,
        SpaceType.WOMENS_MAJLIS.value: EntranceType.MENS_MAJLIS,
        SpaceType.CORRIDOR.value: EntranceType.MAIN_FAMILY,
        SpaceType.LIVING.value: EntranceType.MAIN_FAMILY,
        SpaceType.KITCHEN.value: EntranceType.SERVICE,
        SpaceType.LAUNDRY.value: EntranceType.SERVICE,
        SpaceType.MAID_ROOM.value: EntranceType.SERVICE,
    }
    entrance = mapping.get(into_space_type or "", EntranceType.UNKNOWN)
    if entrance is EntranceType.UNKNOWN:
        return Classification(
            value=entrance.value,
            method="unclassified",
            confidence=0.0,
            source=f"external door into space type '{into_space_type}'",
        )
    return Classification(
        value=entrance.value,
        method="derived_from_space_type",
        confidence=0.7,
        source=f"external door into space type '{into_space_type}'",
    )


def load_corrections(source_dir: str | Path) -> dict:
    """Optional manual corrections file: review_corrections.json in the case
    source directory. Structure:

    {"spaces": {"<GlobalId>": {"space_type": "...", "zone": "...",
                               "reviewer": "name"}},
     "entrances": {"<door GlobalId>": {"entrance_type": "...",
                                        "reviewer": "name"}}}
    """
    path = Path(source_dir) / "review_corrections.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpdInputError(f"review_corrections.json is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise SpdInputError("review_corrections.json must be a JSON object")
    for section in ("spaces", "entrances"):
        block = data.get(section)
        if block is None:
            continue
        if not isinstance(block, dict):
            raise SpdInputError(
                f"review_corrections.json '{section}' must be an object mapping "
                f"GlobalIds to correction objects"
            )
        for global_id, entry in block.items():
            if not isinstance(entry, dict):
                raise SpdInputError(
                    f"review_corrections.json {section}['{global_id}'] must be "
                    f"an object, got {type(entry).__name__}"
                )
    return data


def apply_space_correction(
    corrections: dict, global_id: str, current_type: Classification, current_zone: Classification
) -> tuple[Classification, Classification]:
    entry = (corrections.get("spaces") or {}).get(global_id)
    if not entry:
        return current_type, current_zone
    reviewer = entry.get("reviewer") or "unnamed reviewer"
    corrected_type = current_type
    corrected_zone = current_zone
    # Blank values mean "unchanged" so the generated template can be saved
    # back with only selected entries filled in.
    if entry.get("space_type"):
        value = entry["space_type"]
        if value not in {t.value for t in SpaceType}:
            raise SpdInputError(f"correction for '{global_id}': unknown space_type '{value}'")
        corrected_type = Classification(
            value=value,
            method="manual_correction",
            confidence=1.0,
            source=f"review_corrections.json by {reviewer}",
            reviewer_status="reviewer_confirmed",
        )
        derived = _SPACE_ZONE[SpaceType(value)]
        corrected_zone = Classification(
            value=derived.value,
            method="manual_correction",
            confidence=1.0,
            source=f"derived from corrected space_type by {reviewer}",
            reviewer_status="reviewer_confirmed",
        )
    if entry.get("zone"):
        value = entry["zone"]
        if value not in {z.value for z in Zone}:
            raise SpdInputError(f"correction for '{global_id}': unknown zone '{value}'")
        corrected_zone = Classification(
            value=value,
            method="manual_correction",
            confidence=1.0,
            source=f"review_corrections.json by {reviewer}",
            reviewer_status="reviewer_confirmed",
        )
    return corrected_type, corrected_zone


def apply_entrance_correction(
    corrections: dict, door_id: str, current: Classification
) -> Classification:
    entry = (corrections.get("entrances") or {}).get(door_id)
    if not entry or not entry.get("entrance_type"):
        return current  # blank means "unchanged" (template round-trip safe)
    value = entry["entrance_type"]
    if value not in {e.value for e in EntranceType}:
        raise SpdInputError(f"correction for '{door_id}': unknown entrance_type '{value}'")
    return Classification(
        value=value,
        method="manual_correction",
        confidence=1.0,
        source=f"review_corrections.json by {entry.get('reviewer') or 'unnamed reviewer'}",
        reviewer_status="reviewer_confirmed",
    )
