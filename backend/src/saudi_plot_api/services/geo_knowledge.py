"""Advisory architectural-character lookup over the sbc_geo_knowledge database.

Reads the existing knowledge package's built SQLite artifact
(``07_database/sbc_rules.sqlite``) read-only, replicating its published
point-in-polygon lookup semantics (bbox prefilter + shapely containment,
city maps over metropolitan map).

This is ADVISORY character knowledge only. The source package georeferences
its maps with approximate control points (declared accuracy about +-3 km), so
results never claim exact legal zoning or official regulatory compliance --
that disclaimer is carried into every response, and low-confidence or
conflicting zones stay visible instead of being resolved silently.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import Point, shape

ACCURACY_WARNING = (
    "Geographic zone boundaries are approximate (about +-3 km declared accuracy); "
    "advisory architectural-character knowledge only -- not legal zoning and not "
    "official regulatory compliance."
)

# Map-priority order from the source package: city maps beat the
# metropolitan-area map.
_MAP_SPECIFICITY = {
    "MAP-DMA-01": 1,
    "MAP-DMA-02": 2,
    "MAP-DMA-04": 2,
    "MAP-DMA-05": 2,
    "MAP-DMA-03": 3,
}

# zone_code -> the character families the source levels allow.
_LEVEL_STYLES = {
    "level_1": ["traditional"],
    "level_2": ["traditional", "transitional"],
    "level_3": ["traditional", "transitional", "contemporary"],
}


@dataclass
class CharacterResolution:
    available: bool
    candidate_zones: list[dict] = field(default_factory=list)
    recommended_character: str | None = None
    applicable_guidance: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    requires_confirmation: bool = True
    warnings: list[str] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "candidate_zones": self.candidate_zones,
            "recommended_character": self.recommended_character,
            "applicable_guidance": self.applicable_guidance,
            "confidence": self.confidence,
            "requires_confirmation": self.requires_confirmation,
            "warnings": self.warnings,
            "conflicts": self.conflicts,
        }


def resolve_character(
    db_path: Path | None, latitude: float, longitude: float
) -> CharacterResolution:
    if db_path is None or not Path(db_path).exists():
        return CharacterResolution(
            available=False,
            warnings=[
                "The architectural-character knowledge base is not configured; "
                "no advisory zones are available for this location.",
                ACCURACY_WARNING,
            ],
        )
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("coordinates out of range")

    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        zones = _matching_zones(con, latitude, longitude)
        # Guidance only through fully approved chains: approved level zone ->
        # approved link -> approved rule. Pending zones stay visible in
        # candidate_zones (with warnings) but never produce guidance.
        guidance = _approved_guidance(
            con,
            [
                z["zone_id"]
                for z in zones
                if z["zone_code"].startswith("level_") and z["review_status"] == "approved"
            ],
        )
        conflicts = _conflicts(con, [z["zone_id"] for z in zones])
    finally:
        con.close()

    warnings = [ACCURACY_WARNING]
    pending = [z["zone_id"] for z in zones if z["review_status"] != "approved"]
    if pending:
        warnings.append(
            "Zones pending human review are included and must not be treated as "
            f"approved knowledge: {', '.join(pending)}."
        )
    if conflicts:
        warnings.append(
            f"{len(conflicts)} overlapping-zone conflict(s) touch this location; "
            "conflicting zones are reported, not silently resolved."
        )
    if any(z["zone_code"] == "excluded" for z in zones):
        warnings.append(
            "The point falls in an area excluded from architectural-character "
            "requirements on the source map; verify general municipal requirements."
        )
    if not zones:
        warnings.append(
            "The point is outside the current geographic coverage of the knowledge base."
        )

    recommended, confidence = _recommend(zones)
    return CharacterResolution(
        available=True,
        candidate_zones=zones,
        recommended_character=recommended,
        applicable_guidance=guidance,
        confidence=confidence,
        requires_confirmation=True,
        warnings=warnings,
        conflicts=conflicts,
    )


def _matching_zones(con: sqlite3.Connection, latitude: float, longitude: float) -> list[dict]:
    point = Point(longitude, latitude)
    rows = con.execute(
        "SELECT zone_id, name_ar, name_en, zone_code, zone_type, allowed_styles, map_id, "
        "geometry_geojson, geometry_confidence, boundary_accuracy_meters, review_status, "
        "bbox_minx, bbox_miny, bbox_maxx, bbox_maxy FROM zones"
    ).fetchall()
    hits = []
    for row in rows:
        if not (
            row["bbox_minx"] <= longitude <= row["bbox_maxx"]
            and row["bbox_miny"] <= latitude <= row["bbox_maxy"]
        ):
            continue
        geometry = shape(json.loads(row["geometry_geojson"]))
        if not geometry.contains(point):
            continue
        hits.append(
            {
                "zone_id": row["zone_id"],
                "name_ar": row["name_ar"],
                "name_en": row["name_en"],
                "zone_code": row["zone_code"],
                "zone_type": row["zone_type"],
                "allowed_styles": json.loads(row["allowed_styles"])
                if row["allowed_styles"]
                else None,
                "map_id": row["map_id"],
                "geometry_confidence": row["geometry_confidence"],
                "boundary_accuracy_meters": row["boundary_accuracy_meters"],
                "review_status": row["review_status"],
            }
        )
    hits.sort(key=lambda z: -_MAP_SPECIFICITY.get(z["map_id"], 1))
    return hits


def _approved_guidance(con: sqlite3.Connection, zone_ids: list[str]) -> list[dict]:
    """Only rules whose extraction AND zone link are approved -- pending
    knowledge is never presented as applicable guidance."""
    if not zone_ids:
        return []
    placeholders = ",".join("?" * len(zone_ids))
    rows = con.execute(
        f"""
        SELECT r.rule_id, r.title_en, r.title_ar, r.category, r.original_text_en AS text,
               r.rule_type, r.applicable_styles, r.extraction_confidence, l.zone_id,
               l.priority AS link_priority
        FROM rule_zone_links l JOIN rules r ON r.rule_id = l.rule_id
        WHERE l.zone_id IN ({placeholders})
          AND l.relationship_type = 'applies_to'
          AND l.review_status = 'approved'
          AND r.review_status = 'approved'
        """,
        zone_ids,
    ).fetchall()
    seen: set[str] = set()
    guidance = []
    for row in rows:
        if row["rule_id"] in seen:
            continue
        seen.add(row["rule_id"])
        guidance.append(
            {
                "rule_id": row["rule_id"],
                "title_en": row["title_en"],
                "title_ar": row["title_ar"],
                "category": row["category"],
                "text": row["text"],
                "rule_type": row["rule_type"],
                "applicable_styles": json.loads(row["applicable_styles"] or "[]"),
                "extraction_confidence": row["extraction_confidence"],
                "zone_id": row["zone_id"],
                "priority": row["link_priority"],
            }
        )
    guidance.sort(key=lambda g: -(g["priority"] or 0))
    return guidance


def _conflicts(con: sqlite3.Connection, zone_ids: list[str]) -> list[dict]:
    if not zone_ids:
        return []
    rows = con.execute(
        "SELECT conflict_id, zone_ids, conflict_type, review_status, winning_zone_id, "
        "description FROM conflicts"
    ).fetchall()
    matched = []
    for row in rows:
        conflict_zones = json.loads(row["zone_ids"])
        # A zone-overlap conflict touches this location only when the point
        # lies inside EVERY conflicting zone (i.e. inside the overlap area).
        if conflict_zones and set(conflict_zones) <= set(zone_ids):
            matched.append(
                {
                    "conflict_id": row["conflict_id"],
                    "zone_ids": conflict_zones,
                    "conflict_type": row["conflict_type"],
                    "review_status": row["review_status"],
                    "winning_zone_id": row["winning_zone_id"],
                    "description": row["description"],
                }
            )
    return matched


def _recommend(zones: list[dict]) -> tuple[str | None, float]:
    """Most specific level zone wins; confidence is the minimum geometry
    confidence of the zones the recommendation rests on."""
    level_zones = [z for z in zones if z["zone_code"].startswith("level_")]
    if not level_zones:
        return None, 0.0
    top = level_zones[0]
    styles = top["allowed_styles"] or _LEVEL_STYLES.get(top["zone_code"], [])
    recommended = styles[0] if styles else None
    confidence = min((z["geometry_confidence"] or 0.0) for z in level_zones)
    return recommended, round(confidence, 2)
