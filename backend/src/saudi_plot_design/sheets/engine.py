"""Deterministic composition of the five M6.3 architectural sheets.

The engine is presentation-only. It consumes canonical plot, plan, facade,
quality, and route objects and never mutates or re-scores them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from textwrap import wrap

from saudi_plot_design.layout.geometry import geometry_fingerprint
from saudi_plot_design.model import EXTERIOR, Concept, Rect
from saudi_plot_design.output import DISCLAIMER
from saudi_plot_design.quality.models import FindingSeverity, FindingStatus
from saudi_plot_design.route_semantics import classify_entrances, concept_route_audit
from saudi_plot_design.sheets.models import (
    GRAPHIC_PROFILE,
    ArchitecturalSheetBuild,
    CollisionRecord,
    FurnitureRecord,
    GraphicProfile,
    Primitive,
    SheetIndexEntry,
    SheetPage,
    SheetSetMode,
    SheetValidation,
)

_SHEET_TITLES = {
    "A-001": "COVER AND DESIGN BASIS",
    "A-101": "SITE AND GROUND FLOOR PLAN",
    "A-201": "FRONT ELEVATION",
    "A-601": "ROOM, DOOR AND WINDOW SCHEDULES",
    "A-901": "DESIGN REVIEW AND LIMITATIONS",
}
_SHEET_FILENAMES = {
    "A-001": "sheets/A-001-cover.svg",
    "A-101": "sheets/A-101-ground-floor-plan.svg",
    "A-201": "sheets/A-201-front-elevation.svg",
    "A-601": "sheets/A-601-schedules.svg",
    "A-901": "sheets/A-901-design-review.svg",
}
_SHEET_SCALES = {
    "A-001": "NTS",
    "A-101": "1:150",
    "A-201": "1:75",
    "A-601": "NTS",
    "A-901": "NTS",
}
_ZONE_FILL = {
    "public": "#F4EEE2",
    "family": "#E9F0EA",
    "private": "#ECEBF2",
    "wet_service": "#E7F1F2",
    "circulation": "#F2F2F2",
}
_ZONE_LABEL = {
    "public": "PUBLIC / GUEST",
    "family": "FAMILY",
    "private": "PRIVATE",
    "wet_service": "WET / SERVICE",
    "circulation": "CIRCULATION",
}


def _tag_map(items, prefix: str) -> dict[str, str]:
    return {
        item.id: f"{prefix}{index:02d}"
        for index, item in enumerate(sorted(items, key=lambda value: value.id), start=1)
    }


@dataclass(frozen=True)
class BBox:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    def intersects(self, other: BBox, gap: float = 0.0) -> bool:
        return not (
            self.max_x + gap <= other.min_x
            or other.max_x + gap <= self.min_x
            or self.max_y + gap <= other.min_y
            or other.max_y + gap <= self.min_y
        )

    def inside(self, other: BBox, gap: float = 0.0) -> bool:
        return (
            self.min_x >= other.min_x + gap
            and self.min_y >= other.min_y + gap
            and self.max_x <= other.max_x - gap
            and self.max_y <= other.max_y - gap
        )


def _primitive_within_page(primitive: Primitive, width: float, height: float) -> bool:
    tolerance = 0.01
    if primitive.kind == "text":
        text_width = _estimated_text_width(primitive.text, primitive.font_size_pt)
        if primitive.anchor == "middle":
            min_x, max_x = primitive.x - text_width / 2, primitive.x + text_width / 2
        elif primitive.anchor == "end":
            min_x, max_x = primitive.x - text_width, primitive.x
        else:
            min_x, max_x = primitive.x, primitive.x + text_width
        text_height = primitive.font_size_pt * 25.4 / 72.0
        min_y, max_y = primitive.y - text_height, primitive.y + text_height * 0.25
    elif primitive.kind == "rect":
        min_x, min_y = primitive.x, primitive.y
        max_x, max_y = primitive.x + primitive.width, primitive.y + primitive.height
    elif primitive.kind == "circle":
        min_x, min_y = primitive.x - primitive.radius, primitive.y - primitive.radius
        max_x, max_y = primitive.x + primitive.radius, primitive.y + primitive.radius
    else:
        if not primitive.points:
            return False
        min_x = min(point[0] for point in primitive.points)
        min_y = min(point[1] for point in primitive.points)
        max_x = max(point[0] for point in primitive.points)
        max_y = max(point[1] for point in primitive.points)
    return (
        -tolerance <= min_x <= max_x <= width + tolerance
        and -tolerance <= min_y <= max_y <= height + tolerance
    )


@dataclass(frozen=True)
class PlanTransform:
    x_mm: float
    y_mm: float
    scale_mm_per_m: float
    world_min_x: float
    world_max_y: float

    def point(self, point: tuple[float, float]) -> tuple[float, float]:
        x, y = point
        return (
            self.x_mm + (x - self.world_min_x) * self.scale_mm_per_m,
            self.y_mm + (self.world_max_y - y) * self.scale_mm_per_m,
        )

    def rect(self, rect: Rect) -> BBox:
        a = self.point((rect.min_x, rect.max_y))
        b = self.point((rect.max_x, rect.min_y))
        return BBox(a[0], a[1], b[0], b[1])


class Composer:
    def __init__(self, profile: GraphicProfile = GRAPHIC_PROFILE):
        self.profile = profile
        self.items: list[Primitive] = []

    def line(
        self,
        a: tuple[float, float],
        b: tuple[float, float],
        *,
        stroke: str = "#111111",
        width: float | None = None,
        dash: tuple[float, ...] = (),
        role: str = "line",
        source_id: str = "",
        opacity: float = 1.0,
    ) -> None:
        self.items.append(
            Primitive(
                kind="line",
                points=(a, b),
                stroke=stroke,
                stroke_width_mm=width or self.profile.line_light_mm,
                dash_mm=dash,
                role=role,
                source_id=source_id,
                opacity=opacity,
            )
        )

    def polyline(
        self,
        points: tuple[tuple[float, float], ...],
        *,
        stroke: str = "#111111",
        fill: str = "none",
        width: float | None = None,
        dash: tuple[float, ...] = (),
        role: str = "polyline",
        source_id: str = "",
        opacity: float = 1.0,
        closed: bool = False,
    ) -> None:
        self.items.append(
            Primitive(
                kind="polygon" if closed else "polyline",
                points=points,
                stroke=stroke,
                fill=fill,
                stroke_width_mm=width or self.profile.line_light_mm,
                dash_mm=dash,
                role=role,
                source_id=source_id,
                opacity=opacity,
            )
        )

    def rect(
        self,
        box: BBox,
        *,
        stroke: str = "#111111",
        fill: str = "none",
        width: float | None = None,
        role: str = "rect",
        source_id: str = "",
        opacity: float = 1.0,
    ) -> None:
        self.items.append(
            Primitive(
                kind="rect",
                x=box.min_x,
                y=box.min_y,
                width=box.width,
                height=box.height,
                stroke=stroke,
                fill=fill,
                stroke_width_mm=width or self.profile.line_light_mm,
                role=role,
                source_id=source_id,
                opacity=opacity,
            )
        )

    def circle(
        self,
        center: tuple[float, float],
        radius: float,
        *,
        stroke: str = "#111111",
        fill: str = "none",
        width: float | None = None,
        role: str = "circle",
        source_id: str = "",
    ) -> None:
        self.items.append(
            Primitive(
                kind="circle",
                x=center[0],
                y=center[1],
                radius=radius,
                stroke=stroke,
                fill=fill,
                stroke_width_mm=width or self.profile.line_light_mm,
                role=role,
                source_id=source_id,
            )
        )

    def text(
        self,
        x: float,
        y: float,
        text: str,
        *,
        size: float | None = None,
        bold: bool = False,
        anchor: str = "start",
        color: str = "#111111",
        rotation: float = 0.0,
        role: str = "text",
        source_id: str = "",
        opacity: float = 1.0,
    ) -> None:
        self.items.append(
            Primitive(
                kind="text",
                x=x,
                y=y,
                text=text,
                font_size_pt=size or self.profile.body_pt,
                stroke=color,
                fill=color,
                anchor=anchor,
                bold=bold,
                rotation_deg=rotation,
                role=role,
                source_id=source_id,
                opacity=opacity,
            )
        )


def select_scale(
    world_width_m: float,
    world_height_m: float,
    viewport_width_mm: float,
    viewport_height_mm: float,
    candidates: tuple[int, ...] = (50, 75, 100, 125, 150, 200, 250),
) -> int:
    """Choose the largest conventional scale whose geometry fits."""
    for denominator in candidates:
        mm_per_m = 1000.0 / denominator
        if (
            world_width_m * mm_per_m <= viewport_width_mm
            and world_height_m * mm_per_m <= viewport_height_mm
        ):
            return denominator
    return candidates[-1]


def plan_transform(plot, viewport: BBox) -> tuple[PlanTransform, int]:
    xs = [point[0] for point in plot.corners]
    ys = [point[1] for point in plot.corners]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    denominator = select_scale(width, height, viewport.width, viewport.height)
    scale = 1000.0 / denominator
    drawn_w = width * scale
    drawn_h = height * scale
    return (
        PlanTransform(
            x_mm=viewport.min_x + (viewport.width - drawn_w) / 2,
            y_mm=viewport.min_y + (viewport.height - drawn_h) / 2,
            scale_mm_per_m=scale,
            world_min_x=min(xs),
            world_max_y=max(ys),
        ),
        denominator,
    )


def _page(
    number: str,
    composer: Composer,
    issue_date: str,
    candidate_id: str,
    fingerprint: str,
    *,
    scale: str | None = None,
    review_variant: bool = False,
) -> SheetPage:
    _title_block(
        composer,
        number=number,
        title=_SHEET_TITLES[number],
        issue_date=issue_date,
        scale=scale or _SHEET_SCALES[number],
        candidate_id=candidate_id,
        fingerprint=fingerprint,
    )
    return SheetPage(
        number=number,
        title=_SHEET_TITLES[number],
        scale=scale or _SHEET_SCALES[number],
        revision="P01",
        issue_status="CONCEPT ISSUE - NOT FOR CONSTRUCTION",
        issue_date=issue_date,
        candidate_id=candidate_id,
        geometry_fingerprint=fingerprint,
        primitives=tuple(composer.items),
        review_variant=review_variant,
    )


def _title_block(
    c: Composer,
    *,
    number: str,
    title: str,
    issue_date: str,
    scale: str,
    candidate_id: str,
    fingerprint: str,
) -> None:
    p = c.profile
    top = p.title_block_top_mm
    bottom = p.title_block_bottom_mm
    c.line((10, top), (410, top), width=p.line_medium_mm, role="title-block")
    c.line((10, bottom), (410, bottom), width=p.line_medium_mm, role="title-block")
    for x in (10, 112, 260, 330, 410):
        c.line((x, top), (x, bottom), width=p.line_light_mm, role="title-block")
    c.text(14, top + 7, "SAUDI PLOT DESIGN STUDIO", size=10, bold=True, role="title-block")
    c.text(14, top + 13, "DETERMINISTIC CONCEPT DOCUMENTATION", size=5.5, role="title-block")
    c.text(
        14, top + 21, "NOT FOR CONSTRUCTION", size=8, bold=True, color="#A32626", role="title-block"
    )
    c.text(116, top + 7, title, size=8, bold=True, role="title-block")
    c.text(116, top + 14, "PROJECT: COMPACT 3BR DEMO VILLA CONCEPT", size=5.8, role="title-block")
    c.text(116, top + 20, f"REFERENCE: SPD-{candidate_id.upper()}", size=5.4, role="title-block")
    c.text(116, top + 26, f"SOURCE GEOMETRY: {fingerprint}", size=5.2, role="title-block")
    c.text(264, top + 6, "ISSUE", size=4.8, bold=True, role="title-block")
    c.text(264, top + 12, "CONCEPT / REVIEW", size=5.4, role="title-block")
    c.text(264, top + 18, f"DATE  {issue_date}", size=5.4, role="title-block")
    c.text(264, top + 24, f"SCALE  {scale} @ A3", size=5.4, role="title-block")
    c.text(334, top + 6, "REV", size=4.8, bold=True, role="title-block")
    c.text(334, top + 15, "P01", size=11, bold=True, role="title-block")
    c.text(405, top + 8, number, size=15, bold=True, anchor="end", role="title-block")
    c.text(405, top + 16, "SHEET", size=4.8, anchor="end", role="title-block")
    c.text(405, top + 24, "GENERATED BY SPD M6.3", size=4.8, anchor="end", role="title-block")
    disclaimer_lines = wrap(DISCLAIMER, width=182)
    for i, line in enumerate(disclaimer_lines[:2]):
        c.text(10, 251.5 + i * 3.2, line, size=4.4, color="#9B1C1C", role="disclaimer")


def _section_heading(c: Composer, x: float, y: float, width: float, text: str) -> None:
    c.rect(BBox(x, y, x + width, y + 7), stroke="#243746", fill="#E8EDF0", width=0.2)
    c.text(x + 3, y + 5, text, size=7, bold=True, color="#243746", role="section-heading")


def _wrapped_text(
    c: Composer,
    x: float,
    y: float,
    text: str,
    *,
    width_chars: int,
    size: float = 5.5,
    leading_mm: float = 3.4,
    bold: bool = False,
    color: str = "#222222",
    max_lines: int | None = None,
    role: str = "note",
) -> float:
    lines = wrap(text, width=width_chars, break_long_words=False, break_on_hyphens=False) or [""]
    if max_lines is not None:
        lines = lines[:max_lines]
    for index, line in enumerate(lines):
        c.text(x, y + index * leading_mm, line, size=size, bold=bold, color=color, role=role)
    return y + len(lines) * leading_mm


def _cover_sheet(
    plot,
    envelope,
    rules,
    concept,
    assessment,
    candidate_id: str,
    fingerprint: str,
    issue_date: str,
) -> SheetPage:
    c = Composer()
    c.text(15, 28, "PROFESSIONAL ARCHITECTURAL CONCEPT SET", size=20, bold=True, color="#243746")
    c.text(15, 40, "COMPACT 3BR / SINGLE-STOREY DEMO STUDY", size=10, color="#526876")
    c.text(
        15,
        50,
        "CONCEPT ISSUE  |  NOT FOR CONSTRUCTION  |  NOT REGULATORY APPROVAL",
        size=7,
        bold=True,
        color="#A32626",
    )
    c.line((15, 56), (405, 56), stroke="#243746", width=0.5)

    _section_heading(c, 15, 65, 120, "PROJECT AND DESIGN BASIS")
    xs = [point[0] for point in plot.corners]
    ys = [point[1] for point in plot.corners]
    basis = (
        ("Project reference", f"SPD-{candidate_id.upper()}"),
        ("Location", f"{plot.location[0]:.5f}, {plot.location[1]:.5f} (WGS84 point only)"),
        (
            "Plot",
            f"{max(xs) - min(xs):.2f} x {max(ys) - min(ys):.2f} m / {(max(xs) - min(xs)) * (max(ys) - min(ys)):.1f} m2",
        ),
        ("Street", f"edge {plot.street_edge_index + 1}, authored width {plot.street_width_m:g} m"),
        (
            "Setbacks used",
            f"front {rules.front_m:g} / side {rules.side_m:g} / rear {rules.rear_m:g} m",
        ),
        (
            "Envelope",
            f"{envelope.width_m:.2f} x {envelope.depth_m:.2f} m / {envelope.area_m2:.1f} m2",
        ),
        (
            "Layout",
            f"optimized deterministic search / {candidate_id}"
            if candidate_id != "baseline"
            else "authored baseline",
        ),
        ("Source geometry", fingerprint),
    )
    y = 78.0
    for label, value in basis:
        c.text(18, y, label.upper(), size=4.7, bold=True, color="#60717B")
        c.text(55, y, value, size=5.6)
        y += 8.0

    _section_heading(c, 145, 65, 120, "PROGRAM AND QUALITY SNAPSHOT")
    major = [
        finding.rule_id
        for finding in assessment.findings
        if finding.severity is FindingSeverity.MAJOR
        and finding.status in {FindingStatus.WARNING, FindingStatus.FAIL}
    ]
    facts = (
        ("ROOMS / SPACES", str(len(concept.rooms))),
        ("INTERNAL CONCEPT AREA", f"{concept.total_room_area_m2:.1f} m2"),
        ("FOOTPRINT", f"{concept.footprint.area:.1f} m2"),
        ("FROZEN M6.2.1 SCORE", f"{assessment.overall_score:.2f} / 100"),
        ("STATUS", assessment.score_status.value.replace("_", " ").upper()),
        ("EVIDENCE COVERAGE", f"{assessment.evidence_coverage:.1%}"),
        (
            "BLOCKING FINDINGS",
            str(
                sum(
                    finding.severity is FindingSeverity.BLOCKING
                    and finding.status in {FindingStatus.WARNING, FindingStatus.FAIL}
                    for finding in assessment.findings
                )
            ),
        ),
        ("REMAINING MAJOR", ", ".join(major) or "NONE"),
    )
    y = 79.0
    for label, value in facts:
        c.rect(BBox(149, y - 5, 261, y + 1.8), stroke="#CBD3D7", fill="#FAFBFB", width=0.12)
        c.text(152, y, label, size=4.8, bold=True, color="#60717B")
        c.text(258, y, value, size=5.5, bold=True, anchor="end")
        y += 9.0

    _section_heading(c, 275, 65, 130, "DRAWING INDEX")
    headers = ("SHEET", "TITLE", "SCALE")
    _table_row(c, 278, 79, (22, 91, 12), headers, header=True, height=7)
    y = 86.0
    for number in ("A-001", "A-101", "A-201", "A-601", "A-901"):
        _table_row(
            c,
            278,
            y,
            (22, 91, 12),
            (number, _SHEET_TITLES[number], _SHEET_SCALES[number]),
            height=8,
            font_size=4.8,
        )
        y += 8.0
    c.text(
        278,
        y + 6,
        "A-901 IS INCLUDED IN THE DESIGN REVIEW SET ONLY.",
        size=5,
        bold=True,
        color="#A32626",
    )

    _section_heading(c, 15, 151, 190, "GENERAL CONCEPT NOTES")
    notes = (
        "All dimensions are metres unless noted. Dimensions derive from canonical concept geometry; missing data is shown as N/A.",
        "North has not been surveyed. The plan arrow identifies local plot +Y only and must not be used as true north.",
        "Door swings and concept furniture are deterministic presentation conventions, not authored handing, operation, procurement, or detailed interior design.",
        "The style pack is a DEMO Najdi-character interpretation requiring architect review. It is not an official Saudi classification.",
        (
            "The frozen M6.2.1 assessment is a revision diagnostic. Active major limitations "
            f"{', '.join(major)} remain visible in the review set."
            if major
            else "The frozen M6.2.1 assessment is a revision diagnostic; no active major limitations are reported."
        ),
    )
    y = 165.0
    for index, note in enumerate(notes, start=1):
        c.text(19, y, f"{index:02d}", size=5.5, bold=True, color="#60717B")
        y = _wrapped_text(c, 29, y, note, width_chars=86, size=5.2, leading_mm=3.2, max_lines=2)
        y += 3.0

    _section_heading(c, 215, 151, 190, "SYMBOLS AND STATUS LEGEND")
    legend_y = 166.0
    c.line((220, legend_y), (240, legend_y), width=0.6, role="legend")
    c.text(246, legend_y + 1, "CUT / EXTERNAL WALL", size=5.3)
    c.line((220, legend_y + 10), (240, legend_y + 10), width=0.18, dash=(2.2, 1.2), role="legend")
    c.text(246, legend_y + 11, "SETBACK / BUILDABLE ENVELOPE", size=5.3)
    c.circle((230, legend_y + 21), 3.0, stroke="#A32626", fill="#FFF4F4", width=0.3, role="legend")
    c.text(230, legend_y + 22, "!", size=6, bold=True, anchor="middle", color="#A32626")
    c.text(246, legend_y + 22, "REVIEW EVIDENCE (REVIEW SET ONLY)", size=5.3)
    c.rect(
        BBox(220, legend_y + 30, 240, legend_y + 36),
        stroke="#60717B",
        fill="#F2F2F2",
        width=0.15,
        role="legend",
    )
    c.text(246, legend_y + 35, "CONCEPT FURNITURE / FIXTURE", size=5.3)
    c.text(220, legend_y + 50, "ISSUE STATUS", size=5, bold=True, color="#60717B")
    c.text(220, legend_y + 59, "NOT FOR CONSTRUCTION", size=12, bold=True, color="#A32626")
    c.text(
        220, legend_y + 68, "NOT PERMIT, REGULATORY, OR PROFESSIONAL APPROVAL", size=5.5, bold=True
    )
    return _page("A-001", c, issue_date, candidate_id, fingerprint)


def _table_row(
    c: Composer,
    x: float,
    y: float,
    widths: tuple[float, ...],
    values: tuple[str, ...],
    *,
    header: bool = False,
    height: float = 6.0,
    font_size: float = 4.5,
    role: str = "schedule",
) -> None:
    cursor = x
    fill = "#E8EDF0" if header else "#FFFFFF"
    for width, value in zip(widths, values, strict=True):
        c.rect(
            BBox(cursor, y, cursor + width, y + height),
            stroke="#9AA8AF",
            fill=fill,
            width=0.1,
            role=role,
        )
        c.text(cursor + 1.2, y + height * 0.69, value, size=font_size, bold=header, role=role)
        cursor += width


def _wall_openings(concept: Concept) -> dict[str, tuple[object, ...]]:
    result: dict[str, list[object]] = {wall.id: [] for wall in concept.walls}
    for opening in (*concept.doors, *concept.windows):
        result[opening.wall_id].append(opening)
    return {
        wall_id: tuple(sorted(items, key=lambda item: (item.position_m, item.id)))
        for wall_id, items in result.items()
    }


def _wall_point(wall, offset_m: float) -> tuple[float, float]:
    length = wall.length_m
    ux = (wall.end[0] - wall.start[0]) / length
    uy = (wall.end[1] - wall.start[1]) / length
    return wall.start[0] + ux * offset_m, wall.start[1] + uy * offset_m


def _wall_segments(wall, openings: tuple[object, ...]) -> tuple[tuple[float, float], ...]:
    cursor = 0.0
    segments: list[tuple[float, float]] = []
    for opening in openings:
        start = max(cursor, opening.position_m)
        if start > cursor + 1e-6:
            segments.append((cursor, start))
        cursor = max(cursor, opening.position_m + opening.width_m)
    if cursor < wall.length_m - 1e-6:
        segments.append((cursor, wall.length_m))
    return tuple(segments)


def _room_center(room) -> tuple[float, float]:
    return (
        (room.rect.min_x + room.rect.max_x) / 2,
        (room.rect.min_y + room.rect.max_y) / 2,
    )


def _door_symbol_world(concept: Concept, door) -> tuple[tuple[float, float], ...]:
    """Return hinge, closed end, and schematic open leaf end in world metres.

    The hinge is a disclosed deterministic graphic convention at the opening's
    wall-start side. It is not authored handing or operation information.
    """
    walls = {wall.id: wall for wall in concept.walls}
    rooms = {room.id: room for room in concept.rooms}
    wall = walls[door.wall_id]
    hinge = _wall_point(wall, door.position_m)
    closed = _wall_point(wall, door.position_m + door.width_m)
    target_id = door.to_space if door.to_space != EXTERIOR else door.from_space
    target = rooms.get(target_id)
    ux = (wall.end[0] - wall.start[0]) / wall.length_m
    uy = (wall.end[1] - wall.start[1]) / wall.length_m
    normal_a = (-uy, ux)
    normal_b = (uy, -ux)
    if target is None:
        normal = normal_a
    else:
        center = _room_center(target)
        vector = (center[0] - hinge[0], center[1] - hinge[1])
        normal = normal_a if vector[0] * normal_a[0] + vector[1] * normal_a[1] >= 0 else normal_b
    opened = (hinge[0] + normal[0] * door.width_m, hinge[1] + normal[1] * door.width_m)
    return hinge, closed, opened


def _page_arc(
    center: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
    segments: int = 10,
) -> tuple[tuple[float, float], ...]:
    radius = math.dist(center, start)
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    delta = (a1 - a0) % (2 * math.pi)
    if delta > math.pi:
        delta -= 2 * math.pi
    return tuple(
        (
            center[0] + radius * math.cos(a0 + delta * i / segments),
            center[1] + radius * math.sin(a0 + delta * i / segments),
        )
        for i in range(segments + 1)
    )


def _dimension_h(
    c: Composer,
    x0: float,
    x1: float,
    y: float,
    witness_y: float,
    label: str,
    *,
    source_id: str = "",
) -> None:
    c.line((x0, witness_y), (x0, y + 1), width=0.12, role="dimension", source_id=source_id)
    c.line((x1, witness_y), (x1, y + 1), width=0.12, role="dimension", source_id=source_id)
    c.line((x0, y), (x1, y), width=0.12, role="dimension", source_id=source_id)
    for x, direction in ((x0, 1), (x1, -1)):
        c.polyline(
            ((x, y), (x + direction * 1.8, y - 0.8), (x + direction * 1.8, y + 0.8)),
            fill="#111111",
            width=0.1,
            role="dimension-arrow",
            source_id=source_id,
            closed=True,
        )
    c.text(
        (x0 + x1) / 2,
        y - 1.5,
        label,
        size=4.8,
        anchor="middle",
        role="dimension",
        source_id=source_id,
    )


def _dimension_v(
    c: Composer,
    y0: float,
    y1: float,
    x: float,
    witness_x: float,
    label: str,
    *,
    source_id: str = "",
) -> None:
    c.line((witness_x, y0), (x - 1, y0), width=0.12, role="dimension", source_id=source_id)
    c.line((witness_x, y1), (x - 1, y1), width=0.12, role="dimension", source_id=source_id)
    c.line((x, y0), (x, y1), width=0.12, role="dimension", source_id=source_id)
    c.polyline(
        ((x, y0), (x - 0.8, y0 + 1.8), (x + 0.8, y0 + 1.8)),
        fill="#111111",
        width=0.1,
        role="dimension-arrow",
        closed=True,
    )
    c.polyline(
        ((x, y1), (x - 0.8, y1 - 1.8), (x + 0.8, y1 - 1.8)),
        fill="#111111",
        width=0.1,
        role="dimension-arrow",
        closed=True,
    )
    c.text(
        x - 1.6,
        (y0 + y1) / 2,
        label,
        size=4.8,
        anchor="middle",
        rotation=-90,
        role="dimension",
        source_id=source_id,
    )


def _label_text(room, review: bool, room_tag: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    full = (
        *((f"{room_tag} | {room.id.upper()}",) if review else ()),
        room.name.upper(),
        f"{room.area_m2:.1f} m2",
        f"{room.width_m:.2f} x {room.length_m:.2f} m",
    )
    aliases = {
        "master_bath": "MASTER BATH",
        "shared_bath": "SHARED BATH",
        "family_living": "FAMILY LIVING",
        "laundry": "LAUNDRY",
        "corridor": "CORRIDOR",
        "guest_wc": "GUEST WC",
        "maid_room": "MAID ROOM",
        "master_bedroom": "MASTER BEDROOM",
    }
    compact = (
        *((room_tag,) if review else ()),
        aliases.get(room.type, room.name).upper(),
        f"{room.area_m2:.1f} m2",
    )
    return full, compact


def _estimated_text_width(text: str, font_size_pt: float) -> float:
    return len(text) * font_size_pt * 0.17


def _room_labels(
    c: Composer,
    concept: Concept,
    transform: PlanTransform,
    *,
    review: bool,
) -> tuple[CollisionRecord, ...]:
    records: list[CollisionRecord] = []
    room_tags = _tag_map(concept.rooms, "R")
    for room in sorted(concept.rooms, key=lambda item: item.id):
        box = transform.rect(room.rect)
        full, compact = _label_text(room, review, room_tags[room.id])
        font_size = 4.7
        line_gap = 3.3
        fits_full = (
            max(_estimated_text_width(line, font_size) for line in full) <= box.width - 2.0
            and len(full) * line_gap <= box.height - 2.0
        )
        lines = full if fits_full else compact
        if not fits_full:
            font_size = 4.1
            line_gap = 2.9
            records.append(
                CollisionRecord(
                    annotation_id=f"room-label:{room.id}",
                    room_id=room.id,
                    disposition="compact_fallback",
                    details="full room label did not fit; deterministic compact label used",
                )
            )
        required_w = max(_estimated_text_width(line, font_size) for line in lines)
        required_h = len(lines) * line_gap
        if required_w > box.width - 1.0 or required_h > box.height - 1.0:
            # A keyed leader callout is truthful and avoids silently omitting the room.
            code = room_tags[room.id] if review else room.name.upper()
            c.text(
                box.max_x - 1.0,
                box.min_y + 3.5,
                code,
                size=3.6,
                anchor="end",
                bold=True,
                role="room-label",
                source_id=room.id,
            )
            c.line(
                ((box.min_x + box.max_x) / 2, (box.min_y + box.max_y) / 2),
                (box.max_x - 1.5, box.min_y + 4.0),
                width=0.1,
                role="room-label-leader",
                source_id=room.id,
            )
            records.append(
                CollisionRecord(
                    annotation_id=f"room-label:{room.id}",
                    room_id=room.id,
                    disposition="leader_fallback",
                    details="compact label did not fit; keyed label and leader used",
                )
            )
            continue
        cx = (box.min_x + box.max_x) / 2
        start_y = (box.min_y + box.max_y) / 2 - required_h / 2 + 2.3
        for index, line in enumerate(lines):
            c.text(
                cx,
                start_y + index * line_gap,
                line,
                size=font_size,
                anchor="middle",
                bold=index == 0,
                role="room-label",
                source_id=room.id,
            )
    return tuple(records)


def _symbol_rect(c: Composer, box: BBox, room_id: str, symbol_type: str) -> None:
    c.rect(
        box, stroke="#7A858A", fill="none", width=0.12, role="concept-furniture", source_id=room_id
    )
    if symbol_type in {"bed", "maid_bed"}:
        c.line(
            (box.min_x, box.min_y + box.height * 0.28),
            (box.max_x, box.min_y + box.height * 0.28),
            stroke="#7A858A",
            width=0.1,
            role="concept-furniture",
            source_id=room_id,
        )
        c.rect(
            BBox(box.min_x + 0.7, box.min_y + 0.7, box.max_x - 0.7, box.min_y + box.height * 0.25),
            stroke="#7A858A",
            width=0.08,
            role="concept-furniture",
            source_id=room_id,
        )
    elif symbol_type in {"sofa", "majlis_seating"}:
        c.line(
            (box.min_x + 1, box.min_y + 1.4),
            (box.max_x - 1, box.min_y + 1.4),
            stroke="#7A858A",
            width=0.1,
            role="concept-furniture",
            source_id=room_id,
        )
    elif symbol_type == "wardrobe":
        c.line(
            (box.min_x + box.width / 2, box.min_y),
            (box.min_x + box.width / 2, box.max_y),
            stroke="#7A858A",
            width=0.08,
            role="concept-furniture",
            source_id=room_id,
        )
    elif symbol_type == "dining_table":
        for point in (
            (box.min_x - 1, box.min_y + 1),
            (box.max_x + 1, box.min_y + 1),
            (box.min_x - 1, box.max_y - 1),
            (box.max_x + 1, box.max_y - 1),
        ):
            c.circle(
                point,
                0.65,
                stroke="#7A858A",
                width=0.1,
                role="concept-furniture",
                source_id=room_id,
            )


def _door_clearance_boxes(
    concept: Concept, transform: PlanTransform
) -> dict[str, tuple[BBox, ...]]:
    result: dict[str, list[BBox]] = {room.id: [] for room in concept.rooms}
    for door in concept.doors:
        hinge, closed, opened = (
            transform.point(point) for point in _door_symbol_world(concept, door)
        )
        room_id = door.to_space if door.to_space != EXTERIOR else door.from_space
        if room_id not in result:
            continue
        result[room_id].append(
            BBox(
                min(hinge[0], closed[0], opened[0]) - 0.8,
                min(hinge[1], closed[1], opened[1]) - 0.8,
                max(hinge[0], closed[0], opened[0]) + 0.8,
                max(hinge[1], closed[1], opened[1]) + 0.8,
            )
        )
    return {room_id: tuple(boxes) for room_id, boxes in result.items()}


def _safe_corner_box(
    usable: BBox,
    width: float,
    height: float,
    forbidden: tuple[BBox, ...],
) -> BBox | None:
    candidates = (
        BBox(usable.min_x, usable.max_y - height, usable.min_x + width, usable.max_y),
        BBox(usable.max_x - width, usable.max_y - height, usable.max_x, usable.max_y),
        BBox(usable.min_x, usable.min_y, usable.min_x + width, usable.min_y + height),
        BBox(usable.max_x - width, usable.min_y, usable.max_x, usable.min_y + height),
    )
    return next(
        (
            box
            for box in candidates
            if not any(box.intersects(other, gap=0.8) for other in forbidden)
        ),
        None,
    )


def _furniture(
    c: Composer,
    concept: Concept,
    transform: PlanTransform,
) -> tuple[FurnitureRecord, ...]:
    """Place limited, deterministic concept symbols without changing geometry."""
    records: list[FurnitureRecord] = []
    clearance = _door_clearance_boxes(concept, transform)
    symbol_by_type = {
        "bedroom": "bed",
        "master_bedroom": "bed",
        "maid_room": "maid_bed",
        "family_living": "sofa",
        "majlis": "majlis_seating",
        "dining": "dining_table",
        "kitchen": "kitchen_counter",
        "guest_wc": "wc",
        "master_bath": "shower",
        "shared_bath": "wash_basin",
        "laundry": "washer",
    }
    for room in sorted(concept.rooms, key=lambda item: item.id):
        symbol_type = symbol_by_type.get(room.type)
        if symbol_type is None:
            continue
        room_box = transform.rect(room.rect)
        usable = BBox(
            room_box.min_x + 1.8, room_box.min_y + 1.8, room_box.max_x - 1.8, room_box.max_y - 1.8
        )
        if usable.width < 6 or usable.height < 6:
            records.append(
                FurnitureRecord(
                    f"F-{room.id}",
                    room.id,
                    symbol_type,
                    "omitted",
                    "room too small for a safe schematic symbol",
                )
            )
            continue
        if symbol_type in {"bed", "maid_bed"}:
            width = min(10.5, usable.width * 0.42)
            height = min(14.0, usable.height * 0.48)
            box = _safe_corner_box(usable, width, height, clearance[room.id])
            if box is None:
                records.append(
                    FurnitureRecord(
                        f"F-{room.id}",
                        room.id,
                        symbol_type,
                        "omitted",
                        "no corner placement clears the schematic door-swing zone",
                    )
                )
                continue
            _symbol_rect(c, box, room.id, symbol_type)
            if symbol_type == "bed":
                wardrobe_width = min(3.8, usable.width * 0.20)
                wardrobe_height = min(10.0, usable.height * 0.42)
                wardrobe = _safe_corner_box(
                    usable,
                    wardrobe_width,
                    wardrobe_height,
                    (*clearance[room.id], box),
                )
                if wardrobe is None:
                    records.append(
                        FurnitureRecord(
                            f"F-{room.id}-wardrobe",
                            room.id,
                            "wardrobe",
                            "omitted",
                            "no wardrobe placement clears the bed and schematic door-swing zone",
                        )
                    )
                else:
                    _symbol_rect(c, wardrobe, room.id, "wardrobe")
                    records.append(
                        FurnitureRecord(
                            f"F-{room.id}-wardrobe",
                            room.id,
                            "wardrobe",
                            "placed",
                            "concept furniture layout; no geometry or score effect",
                        )
                    )
        elif symbol_type in {"sofa", "majlis_seating"}:
            width = min(usable.width * 0.55, 17.0)
            box = _safe_corner_box(usable, width, 4.2, clearance[room.id])
            if box is None:
                records.append(
                    FurnitureRecord(
                        f"F-{room.id}",
                        room.id,
                        symbol_type,
                        "omitted",
                        "no wall-side placement clears the schematic door-swing zone",
                    )
                )
                continue
            _symbol_rect(c, box, room.id, symbol_type)
        elif symbol_type == "dining_table":
            width = min(usable.width * 0.42, 11.0)
            height = min(usable.height * 0.34, 7.0)
            box = _safe_corner_box(usable, width, height, clearance[room.id])
            if box is None:
                records.append(
                    FurnitureRecord(
                        f"F-{room.id}",
                        room.id,
                        symbol_type,
                        "omitted",
                        "no table placement clears the schematic door-swing zone",
                    )
                )
                continue
            _symbol_rect(c, box, room.id, symbol_type)
        elif symbol_type == "kitchen_counter":
            candidates = (
                BBox(usable.min_x, usable.min_y, usable.max_x, usable.min_y + 2.5),
                BBox(usable.min_x, usable.max_y - 2.5, usable.max_x, usable.max_y),
            )
            box = next(
                (
                    candidate
                    for candidate in candidates
                    if not any(candidate.intersects(other, gap=0.8) for other in clearance[room.id])
                ),
                None,
            )
            if box is None:
                records.append(
                    FurnitureRecord(
                        f"F-{room.id}",
                        room.id,
                        symbol_type,
                        "omitted",
                        "no counter edge clears the schematic door-swing zone",
                    )
                )
                continue
            c.rect(
                box,
                stroke="#7A858A",
                fill="#F5F5F2",
                width=0.12,
                role="concept-fixture",
                source_id=room.id,
            )
            c.circle(
                (box.max_x - 2.0, box.min_y + 1.25),
                0.65,
                stroke="#7A858A",
                width=0.1,
                role="concept-fixture",
                source_id=room.id,
            )
        elif symbol_type == "washer":
            box = _safe_corner_box(usable, 4.4, 4.4, clearance[room.id])
            if box is None:
                records.append(
                    FurnitureRecord(
                        f"F-{room.id}",
                        room.id,
                        symbol_type,
                        "omitted",
                        "no washer placement clears the schematic door-swing zone",
                    )
                )
                continue
            center = ((box.min_x + box.max_x) / 2, (box.min_y + box.max_y) / 2)
            c.rect(
                BBox(center[0] - 2.2, center[1] - 2.2, center[0] + 2.2, center[1] + 2.2),
                stroke="#7A858A",
                width=0.12,
                role="concept-fixture",
                source_id=room.id,
            )
            c.circle(
                center, 1.35, stroke="#7A858A", width=0.1, role="concept-fixture", source_id=room.id
            )
        else:
            fixture_box = _safe_corner_box(usable, 4.8, 5.2, clearance[room.id])
            if fixture_box is None:
                records.append(
                    FurnitureRecord(
                        f"F-{room.id}",
                        room.id,
                        symbol_type,
                        "omitted",
                        "no fixture placement clears the schematic door-swing zone",
                    )
                )
                continue
            center = (
                (fixture_box.min_x + fixture_box.max_x) / 2,
                (fixture_box.min_y + fixture_box.max_y) / 2,
            )
            if symbol_type == "wc":
                c.circle(
                    center,
                    1.35,
                    stroke="#7A858A",
                    width=0.12,
                    role="concept-fixture",
                    source_id=room.id,
                )
                c.rect(
                    BBox(center[0] - 1.2, center[1] - 2.6, center[0] + 1.2, center[1] - 1.4),
                    stroke="#7A858A",
                    width=0.1,
                    role="concept-fixture",
                    source_id=room.id,
                )
            elif symbol_type == "shower":
                c.rect(
                    BBox(center[0] - 2.2, center[1] - 2.2, center[0] + 2.2, center[1] + 2.2),
                    stroke="#7A858A",
                    width=0.12,
                    role="concept-fixture",
                    source_id=room.id,
                )
                c.line(
                    (center[0] - 1.8, center[1] - 1.8),
                    (center[0] + 1.8, center[1] + 1.8),
                    stroke="#7A858A",
                    width=0.08,
                    role="concept-fixture",
                    source_id=room.id,
                )
            else:
                c.rect(
                    BBox(center[0] - 2.2, center[1] - 1.5, center[0] + 2.2, center[1] + 1.5),
                    stroke="#7A858A",
                    width=0.12,
                    role="concept-fixture",
                    source_id=room.id,
                )
                c.circle(
                    center,
                    0.7,
                    stroke="#7A858A",
                    width=0.08,
                    role="concept-fixture",
                    source_id=room.id,
                )
        records.append(
            FurnitureRecord(
                f"F-{room.id}",
                room.id,
                symbol_type,
                "placed",
                "concept furniture layout; no geometry or score effect",
            )
        )
    return tuple(records)


def _plan_sheet(
    plot,
    envelope,
    rules,
    concept,
    assessment,
    candidate_id: str,
    fingerprint: str,
    issue_date: str,
    *,
    review: bool,
) -> tuple[SheetPage, tuple[CollisionRecord, ...], tuple[FurnitureRecord, ...]]:
    c = Composer()
    c.text(15, 17, _SHEET_TITLES["A-101"], size=13, bold=True, color="#243746")
    c.text(15, 25, "CANONICAL CONCEPT GEOMETRY / METRES / A3", size=5.5, color="#60717B")
    viewport = BBox(28, 31, 202, 234)
    transform, denominator = plan_transform(plot, viewport)
    plot_points = tuple(transform.point(point) for point in plot.corners)
    envelope_points = tuple(transform.point(point) for point in envelope.corners)

    # Site hierarchy.
    c.polyline(
        plot_points,
        stroke="#1A2730",
        width=0.5,
        role="plot-boundary",
        source_id=plot.plot_id,
        closed=True,
    )
    c.polyline(
        envelope_points,
        stroke="#47788C",
        width=0.22,
        dash=GRAPHIC_PROFILE.dash_mm,
        role="buildable-envelope",
        source_id=rules.id,
        closed=True,
    )
    fp = concept.footprint
    fp_box = transform.rect(fp)
    c.rect(
        fp_box,
        stroke="#55656D",
        width=0.24,
        role="building-footprint",
        source_id=concept.concept_id,
    )
    for room in sorted(concept.rooms, key=lambda item: item.id):
        room_box = transform.rect(room.rect)
        fill = _ZONE_FILL[room.zone.value] if review else "#FCFCFB"
        c.rect(
            room_box,
            stroke="#E3E6E7",
            fill=fill,
            width=0.06,
            role="room-zone" if review else "room",
            source_id=room.id,
            opacity=0.90,
        )

    # Wall cuts with exact opening gaps.
    openings = _wall_openings(concept)
    for wall in sorted(concept.walls, key=lambda item: item.id):
        for start, end in _wall_segments(wall, openings[wall.id]):
            c.line(
                transform.point(_wall_point(wall, start)),
                transform.point(_wall_point(wall, end)),
                stroke="#10191E",
                width=0.60 if wall.is_external else 0.32,
                role="wall-cut" if wall.is_external else "wall-projected",
                source_id=wall.id,
            )

    # Openings use canonical host coordinates; swing/hinge is a disclosed symbol convention.
    door_tags = _tag_map(concept.doors, "D")
    for door in sorted(concept.doors, key=lambda item: item.id):
        hinge_w, closed_w, opened_w = _door_symbol_world(concept, door)
        hinge = transform.point(hinge_w)
        closed = transform.point(closed_w)
        opened = transform.point(opened_w)
        c.line(hinge, opened, stroke="#355C6B", width=0.26, role="door-leaf", source_id=door.id)
        c.polyline(
            _page_arc(hinge, closed, opened),
            stroke="#778990",
            width=0.12,
            role="door-swing-schematic",
            source_id=door.id,
        )
        c.circle(
            hinge,
            0.45,
            stroke="#355C6B",
            fill="#FFFFFF",
            width=0.12,
            role="door-hinge-schematic",
            source_id=door.id,
        )
        mx = (hinge[0] + closed[0]) / 2
        my = (hinge[1] + closed[1]) / 2
        c.text(
            mx,
            my - 1.2,
            door_tags[door.id],
            size=3.2,
            anchor="middle",
            bold=True,
            color="#355C6B",
            role="door-tag",
            source_id=door.id,
        )
    walls = {wall.id: wall for wall in concept.walls}
    window_tags = _tag_map(concept.windows, "W")
    for window in sorted(concept.windows, key=lambda item: item.id):
        wall = walls[window.wall_id]
        a_w = _wall_point(wall, window.position_m)
        b_w = _wall_point(wall, window.position_m + window.width_m)
        a = transform.point(a_w)
        b = transform.point(b_w)
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        nx, ny = -dy / length * 0.55, dx / length * 0.55
        c.line(
            (a[0] + nx, a[1] + ny),
            (b[0] + nx, b[1] + ny),
            stroke="#2F6774",
            width=0.18,
            role="window-symbol",
            source_id=window.id,
        )
        c.line(
            (a[0] - nx, a[1] - ny),
            (b[0] - nx, b[1] - ny),
            stroke="#2F6774",
            width=0.18,
            role="window-symbol",
            source_id=window.id,
        )
        c.line(
            (a[0] + nx, a[1] + ny),
            (a[0] - nx, a[1] - ny),
            stroke="#2F6774",
            width=0.12,
            role="window-symbol",
            source_id=window.id,
        )
        c.line(
            (b[0] + nx, b[1] + ny),
            (b[0] - nx, b[1] - ny),
            stroke="#2F6774",
            width=0.12,
            role="window-symbol",
            source_id=window.id,
        )
        c.text(
            (a[0] + b[0]) / 2,
            (a[1] + b[1]) / 2 - 1.3,
            window_tags[window.id],
            size=3.1,
            anchor="middle",
            bold=True,
            color="#2F6774",
            role="window-tag",
            source_id=window.id,
        )

    furniture = _furniture(c, concept, transform)
    collisions = _room_labels(c, concept, transform, review=review)

    # Plot/street relationship.
    street_index = plot.street_edge_index
    street_a, street_b = plot.edge_corners(street_index)
    street_a_p, street_b_p = transform.point(street_a), transform.point(street_b)
    street_y = max(street_a_p[1], street_b_p[1]) + 7.0
    c.line(
        (street_a_p[0], street_y),
        (street_b_p[0], street_y),
        stroke="#A25C27",
        width=0.65,
        role="street-edge",
        source_id=f"plot-edge-{street_index + 1}",
    )
    c.text(
        (street_a_p[0] + street_b_p[0]) / 2,
        street_y + 5.0,
        f"AUTHORED STREET EDGE / WIDTH {plot.street_width_m:g} m",
        size=5.2,
        bold=True,
        anchor="middle",
        color="#A25C27",
        role="street-label",
    )
    for index in range(len(plot.corners)):
        a, b = plot.edge_corners(index)
        pa, pb = transform.point(a), transform.point(b)
        c.text(
            (pa[0] + pb[0]) / 2,
            (pa[1] + pb[1]) / 2 - 1.2,
            f"E{index + 1} {plot.edges[index].value.upper()}",
            size=3.8,
            anchor="middle",
            color="#526876",
            role="boundary-label",
            source_id=f"plot-edge-{index + 1}",
        )

    # Overall, footprint, plot and selected chained dimensions.
    plot_box = BBox(
        min(x for x, _ in plot_points),
        min(y for _, y in plot_points),
        max(x for x, _ in plot_points),
        max(y for _, y in plot_points),
    )
    _dimension_h(
        c,
        plot_box.min_x,
        plot_box.max_x,
        plot_box.max_y + 2.8,
        plot_box.max_y,
        f"{(max(p[0] for p in plot.corners) - min(p[0] for p in plot.corners)):.2f} m PLOT",
        source_id=plot.plot_id,
    )
    _dimension_v(
        c,
        plot_box.min_y,
        plot_box.max_y,
        plot_box.min_x - 5.0,
        plot_box.min_x,
        f"{(max(p[1] for p in plot.corners) - min(p[1] for p in plot.corners)):.2f} m PLOT",
        source_id=plot.plot_id,
    )
    _dimension_h(
        c,
        fp_box.min_x,
        fp_box.max_x,
        fp_box.min_y - 5.0,
        fp_box.min_y,
        f"{fp.width:.2f} m FOOTPRINT",
        source_id=concept.concept_id,
    )
    _dimension_v(
        c,
        fp_box.min_y,
        fp_box.max_y,
        fp_box.max_x + 5.0,
        fp_box.max_x,
        f"{fp.height:.2f} m FOOTPRINT",
        source_id=concept.concept_id,
    )
    front_breaks = sorted(
        {
            fp.min_x,
            fp.max_x,
            *[room.rect.min_x for room in concept.rooms if abs(room.rect.min_y - fp.min_y) < 1e-6],
            *[room.rect.max_x for room in concept.rooms if abs(room.rect.min_y - fp.min_y) < 1e-6],
        }
    )
    chain_y = fp_box.max_y + 7.2
    for start, end in zip(front_breaks, front_breaks[1:]):
        x0 = transform.point((start, fp.min_y))[0]
        x1 = transform.point((end, fp.min_y))[0]
        _dimension_h(c, x0, x1, chain_y, fp_box.max_y, f"{end - start:.2f}")

    # Setback callouts from canonical values.
    c.text(
        plot_box.min_x + 2,
        plot_box.max_y - 2,
        f"FRONT SETBACK {rules.front_m:g} m",
        size=4.3,
        color="#47788C",
        role="setback-label",
    )
    c.text(
        plot_box.min_x + 2,
        plot_box.min_y + 4,
        f"REAR SETBACK {rules.rear_m:g} m",
        size=4.3,
        color="#47788C",
        role="setback-label",
    )
    c.text(
        plot_box.min_x + 2,
        (plot_box.min_y + plot_box.max_y) / 2,
        f"SIDE {rules.side_m:g} m",
        size=4.3,
        rotation=-90,
        color="#47788C",
        role="setback-label",
    )

    # Local reference arrow and scale bar (truthful orientation semantics).
    nx, ny = 214.0, 43.0
    c.line((nx, ny + 18), (nx, ny), width=0.35, role="north-reference")
    c.polyline(
        ((nx, ny), (nx - 2.2, ny + 5), (nx + 2.2, ny + 5)),
        fill="#111111",
        width=0.15,
        role="north-reference",
        closed=True,
    )
    c.text(nx, ny - 2.5, "N*", size=7, bold=True, anchor="middle", role="north-reference")
    c.text(nx + 7, ny + 5, "LOCAL PLOT +Y", size=4.7, bold=True, role="north-reference")
    c.text(nx + 7, ny + 11, "NORTH NOT SURVEYED", size=4.7, color="#A32626", role="north-reference")
    bar_x, bar_y = 211.0, 72.0
    one_m = transform.scale_mm_per_m
    c.line((bar_x, bar_y), (bar_x + one_m * 10, bar_y), width=0.35, role="scale-bar")
    for index in range(11):
        height = 3 if index in {0, 5, 10} else 1.8
        c.line(
            (bar_x + one_m * index, bar_y - height / 2),
            (bar_x + one_m * index, bar_y + height / 2),
            width=0.18,
            role="scale-bar",
        )
    c.text(bar_x, bar_y + 6, "0", size=4.3, anchor="middle", role="scale-bar")
    c.text(bar_x + one_m * 5, bar_y + 6, "5", size=4.3, anchor="middle", role="scale-bar")
    c.text(bar_x + one_m * 10, bar_y + 6, "10 m", size=4.3, anchor="middle", role="scale-bar")

    # Right-side basis, entrance inventory, legend, and review summary.
    _section_heading(c, 211, 88, 194, "PLAN BASIS AND SYMBOL CONVENTIONS")
    y = 101.0
    basis_notes = (
        f"Scale 1:{denominator}. Dimensions and opening positions derive from canonical geometry fingerprint {fingerprint}.",
        "Door leaf, hinge and swing are schematic graphic conventions only; authored handing and operation are not available.",
        "Furniture and fixtures are a concept furniture layout only. They do not affect geometry, quality scores, procurement or detailed interior design.",
    )
    for note in basis_notes:
        y = _wrapped_text(c, 214, y, note, width_chars=80, size=4.9, leading_mm=3.1, max_lines=2)
        y += 2.0
    _section_heading(c, 211, y + 1, 94, "ENTRANCE INVENTORY")
    _section_heading(c, 311, y + 1, 94, "ZONE LEGEND")
    y += 12.0
    entrance_y = y
    for entrance in classify_entrances(concept):
        label = entrance.entrance_type.value.replace("_", " ").upper()
        c.text(
            214,
            entrance_y,
            f"{door_tags[entrance.door_id]}  {entrance.door_id}",
            size=4.3,
            bold=True,
            color="#355C6B",
        )
        c.text(246, entrance_y, label, size=4.6)
        entrance_y += 6.0
    zone_y = y
    for zone, label in _ZONE_LABEL.items():
        c.rect(
            BBox(314, zone_y - 3.2, 322, zone_y + 0.8),
            stroke="#88979D",
            fill=_ZONE_FILL[zone],
            width=0.1,
            role="zone-legend",
        )
        c.text(326, zone_y, label, size=4.4)
        zone_y += 6.0
    y = max(entrance_y, zone_y) + 3.0
    _section_heading(c, 211, y, 194, "DESIGN STATUS")
    y += 11.0
    major_ids = [
        finding.rule_id
        for finding in assessment.findings
        if finding.severity is FindingSeverity.MAJOR
        and finding.status in {FindingStatus.WARNING, FindingStatus.FAIL}
    ]
    c.text(
        214, y, f"FROZEN M6.2.1 SCORE  {assessment.overall_score:.2f} / 100", size=6.0, bold=True
    )
    c.text(
        214, y + 7, f"STATUS  {assessment.score_status.value.replace('_', ' ').upper()}", size=5.2
    )
    c.text(
        214,
        y + 14,
        f"REMAINING MAJOR  {', '.join(major_ids) or 'NONE'}",
        size=5.2,
        bold=True,
        color="#A32626",
    )
    if review:
        c.text(
            214,
            y + 22,
            "REVIEW VARIANT: ROOM IDS + EVIDENCE MARKERS",
            size=5.2,
            bold=True,
            color="#A32626",
        )
        for index, finding_id in enumerate(major_ids):
            row, column = divmod(index, 5)
            row_count = min(5, len(major_ids) - row * 5)
            cx = 400 - (row_count - 1 - column) * 12
            cy = y + 16 + row * 15
            c.circle(
                (cx, cy),
                4.0,
                stroke="#A32626",
                fill="#FFF4F4",
                width=0.3,
                role="review-marker",
                source_id=finding_id,
            )
            c.text(
                cx,
                cy + 1.4,
                str(index + 1),
                size=5.2,
                bold=True,
                anchor="middle",
                color="#A32626",
                role="review-marker",
                source_id=finding_id,
            )
            c.text(
                cx,
                cy + 7.2,
                finding_id,
                size=3.6,
                anchor="middle",
                color="#A32626",
                role="review-marker",
                source_id=finding_id,
            )
    else:
        c.text(
            214,
            y + 22,
            "CLEAN VARIANT: NO QUALITY OVERLAYS OR FINDING MARKERS",
            size=5.0,
            bold=True,
            color="#60717B",
        )
    return (
        _page(
            "A-101",
            c,
            issue_date,
            candidate_id,
            fingerprint,
            scale=f"1:{denominator}",
            review_variant=review,
        ),
        collisions,
        furniture,
    )


def _element_bbox(geometry: dict) -> tuple[float, float, float, float]:
    if geometry["kind"] == "rect":
        return (
            geometry["x"],
            geometry["z"],
            geometry["x"] + geometry["w"],
            geometry["z"] + geometry["h"],
        )
    points = geometry["points"]
    return (
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    )


def _elevation_sheet(
    concept,
    facade,
    pack_ref,
    pack_data,
    candidate_id: str,
    fingerprint: str,
    issue_date: str,
) -> SheetPage:
    c = Composer()
    c.text(15, 17, _SHEET_TITLES["A-201"], size=13, bold=True, color="#243746")
    c.text(
        15, 25, "SELECTED STREET-FACING FACADE / DEMO NAJDI CHARACTER", size=5.5, color="#60717B"
    )
    wall = facade.facade_wall
    scale = 1000.0 / 75.0
    x0 = 38.0
    base_y = 181.0

    def point(x: float, z: float) -> tuple[float, float]:
        return x0 + x * scale, base_y - z * scale

    door_tags = _tag_map(concept.doors, "D")
    window_tags = _tag_map(concept.windows, "W")

    # Restrained style-pack material fills; all geometry remains facade-derived.
    for element in facade.facade_elements:
        geometry = element.geometry
        color = element.color_hex if element.color_hex else "#F0EEE9"
        if geometry["kind"] == "rect":
            a = point(geometry["x"], geometry["z"] + geometry["h"])
            b = point(geometry["x"] + geometry["w"], geometry["z"])
            c.rect(
                BBox(a[0], a[1], b[0], b[1]),
                stroke="#26343A",
                fill=color,
                width=0.18,
                role=f"facade-{element.element_type}",
                source_id=element.id,
                opacity=0.65,
            )
        else:
            points = tuple(point(x, z) for x, z in geometry["points"])
            c.polyline(
                points,
                stroke="#26343A",
                fill=color,
                width=0.18,
                role=f"facade-{element.element_type}",
                source_id=element.id,
                opacity=0.65,
                closed=True,
            )
    for opening in facade.facade_openings:
        a = point(opening.x_start_m, opening.head_elevation_m)
        b = point(opening.x_start_m + opening.width_m, opening.sill_elevation_m)
        c.rect(
            BBox(a[0], a[1], b[0], b[1]),
            stroke="#17252B",
            fill="#FFFFFF",
            width=0.32,
            role="facade-opening",
            source_id=opening.source_plan_opening_id,
        )
        opening_tag = (
            door_tags[opening.source_plan_opening_id]
            if opening.opening_type == "door"
            else window_tags[opening.source_plan_opening_id]
        )
        c.text(
            (a[0] + b[0]) / 2,
            a[1] - 2.0,
            opening_tag,
            size=4.2,
            bold=True,
            anchor="middle",
            color="#355C6B",
            role="facade-opening-tag",
            source_id=opening.source_plan_opening_id,
        )
        if opening.opening_type == "window":
            c.line(
                (a[0], (a[1] + b[1]) / 2),
                (b[0], (a[1] + b[1]) / 2),
                stroke="#62777F",
                width=0.12,
                role="facade-window-mullion",
                source_id=opening.source_plan_opening_id,
            )
    ground_a = point(-1.5, 0)
    ground_b = point(wall.length_m + 1.5, 0)
    c.line(ground_a, ground_b, stroke="#162229", width=0.55, role="ground-line")
    c.text(
        ground_a[0],
        ground_a[1] + 5,
        "FINISHED GROUND 0.00 (CONCEPT DATUM)",
        size=4.8,
        role="level-note",
    )

    # Levels and overall dimensions from the canonical facade/style pack.
    level_x = point(wall.length_m, 0)[0] + 14
    for elevation, label in (
        (0.0, "FGL 0.00"),
        (wall.wall_height_m, f"WALL +{wall.wall_height_m:.2f}"),
        (wall.total_height_m, f"PARAPET +{wall.total_height_m:.2f}"),
    ):
        py = point(0, elevation)[1]
        c.line((level_x - 4, py), (level_x + 9, py), stroke="#47788C", width=0.15, role="level")
        c.text(level_x + 11, py + 1.2, label, size=4.8, color="#355C6B", role="level")
    _dimension_h(
        c,
        point(0, 0)[0],
        point(wall.length_m, 0)[0],
        base_y + 15,
        base_y,
        f"{wall.length_m:.2f} m FACADE",
        source_id=facade.facade_concept_id,
    )
    _dimension_v(
        c,
        point(0, wall.total_height_m)[1],
        base_y,
        point(0, 0)[0] - 10,
        point(0, 0)[0],
        f"{wall.total_height_m:.2f} m OVERALL",
        source_id=facade.facade_concept_id,
    )

    _section_heading(c, 260, 38, 145, "DEMO CHARACTER AND MATERIAL BASIS")
    c.text(264, 53, pack_ref.name_en.upper(), size=8, bold=True, color="#243746")
    c.text(264, 61, f"STYLE PACK {pack_ref.style_pack_id} v{pack_ref.version}", size=5.2)
    c.text(
        264, 68, "STATUS: DEMO / REQUIRES ARCHITECT REVIEW", size=5.2, bold=True, color="#A32626"
    )
    y = 80.0
    for material in pack_data.materials.material_palette:
        c.rect(
            BBox(264, y - 4, 273, y + 1),
            stroke="#7A858A",
            fill="#F0EEE9",
            width=0.12,
            role="material-legend",
            source_id=material.id,
        )
        c.text(
            278,
            y,
            material.name_en.upper(),
            size=4.8,
            bold=True,
            role="material-legend",
            source_id=material.id,
        )
        y = (
            _wrapped_text(
                c,
                278,
                y + 4,
                material.finish_note,
                width_chars=51,
                size=4.4,
                leading_mm=2.8,
                max_lines=2,
                role="material-legend",
            )
            + 3
        )
    _section_heading(c, 260, 155, 145, "ELEVATION NOTES")
    notes = (
        "Only the selected front elevation is shown. No side, rear, structural, waterproofing, or construction details are implied.",
        "Opening locations and widths trace to the selected plan. Sill/head elevations and decorative treatment come from the DEMO style pack.",
        "Material zones are style-pack presentation labels, not specifications, approvals, procurement selections, or official Saudi requirements.",
        "Najdi character is a demo interpretation requiring professional architect review.",
    )
    y = 170.0
    for note in notes:
        y = _wrapped_text(c, 264, y, note, width_chars=59, size=4.8, leading_mm=3.0, max_lines=2)
        y += 3.0
    return _page("A-201", c, issue_date, candidate_id, fingerprint, scale="1:75")


def room_schedule_rows(concept: Concept, assessment) -> tuple[tuple[str, ...], ...]:
    room_assessment = {item.room_id: item for item in assessment.room_assessments}
    return tuple(
        (
            room.id,
            room.name,
            room.zone.value,
            f"{room.area_m2:.2f}",
            f"{room.width_m:.2f}",
            f"{room.length_m:.2f}",
            f"{2 * (room.rect.width + room.rect.height):.2f}",
            "YES" if room_assessment[room.id].external_wall_contact else "NO",
            "YES" if room_assessment[room.id].external_opening else "NO",
            room_assessment[room.id].status.value,
        )
        for room in sorted(concept.rooms, key=lambda item: item.id)
    )


def door_schedule_rows(concept: Concept, facade) -> tuple[tuple[str, ...], ...]:
    facade_by_source = {
        opening.source_plan_opening_id: opening
        for opening in facade.facade_openings
        if opening.opening_type == "door"
    }
    entrances = {item.door_id: item for item in classify_entrances(concept)}
    tags = _tag_map(concept.doors, "D")
    rows = []
    for door in sorted(concept.doors, key=lambda item: item.id):
        facade_opening = facade_by_source.get(door.id)
        entrance = entrances.get(door.id)
        rows.append(
            (
                f"{tags[door.id]} / {door.id}",
                f"{door.from_space} / {door.to_space}",
                "EXT" if EXTERIOR in (door.from_space, door.to_space) else "INT",
                (entrance.entrance_type.value if entrance else "N/A"),
                f"{door.width_m:.2f}",
                f"{facade_opening.head_elevation_m:.2f}" if facade_opening else "N/A",
                "SCHEMATIC / HANDING N/A",
                "REVIEW" if entrance and entrance.requires_review else "-",
            )
        )
    return tuple(rows)


def window_schedule_rows(concept: Concept, facade) -> tuple[tuple[str, ...], ...]:
    facade_by_source = {
        opening.source_plan_opening_id: opening
        for opening in facade.facade_openings
        if opening.opening_type == "window"
    }
    tags = _tag_map(concept.windows, "W")
    return tuple(
        (
            f"{tags[window.id]} / {window.id}",
            window.room_id,
            window.wall_id,
            f"{window.width_m:.2f}",
            f"{facade_by_source[window.id].head_elevation_m - facade_by_source[window.id].sill_elevation_m:.2f}"
            if window.id in facade_by_source
            else f"{window.head_height_m - window.sill_height_m:.2f}",
            f"{facade_by_source[window.id].sill_elevation_m:.2f}"
            if window.id in facade_by_source
            else f"{window.sill_height_m:.2f}",
            "FRONT FACADE" if window.id in facade_by_source else f"PLAN WALL {window.wall_id}",
            "-" if window.id in facade_by_source else "PLAN NOMINAL / FACADE N/A",
        )
        for window in sorted(concept.windows, key=lambda item: item.id)
    )


def _schedule_sheet(
    concept,
    facade,
    assessment,
    candidate_id: str,
    fingerprint: str,
    issue_date: str,
) -> SheetPage:
    c = Composer()
    c.text(15, 17, _SHEET_TITLES["A-601"], size=13, bold=True, color="#243746")
    c.text(
        15,
        25,
        "CANONICAL SCHEDULES / N/A MEANS SOURCE DATA NOT AVAILABLE",
        size=5.5,
        color="#60717B",
    )

    _section_heading(c, 15, 35, 185, "ROOM SCHEDULE")
    room_headers = ("ID", "ROOM", "ZONE", "AREA", "W", "D", "PERIM", "EXT", "OPEN", "QUALITY")
    room_widths = (23, 31, 24, 13, 10, 10, 13, 9, 10, 24)
    _table_row(c, 15, 44, room_widths, room_headers, header=True, height=7, font_size=4.2)
    y = 51.0
    for row in room_schedule_rows(concept, assessment):
        _table_row(c, 15, y, room_widths, row, height=8.0, font_size=3.75)
        y += 8.0
    c.text(
        15,
        y + 6,
        f"ROOM COUNT {len(concept.rooms)}  |  TOTAL INTERNAL CONCEPT AREA {concept.total_room_area_m2:.2f} m2",
        size=5.0,
        bold=True,
    )

    _section_heading(c, 207, 35, 198, "DOOR SCHEDULE")
    door_headers = (
        "ID",
        "CONNECTED SPACES",
        "I/E",
        "ENTRANCE",
        "W",
        "H",
        "OPERATION / HANDING",
        "FLAG",
    )
    door_widths = (36, 40, 9, 21, 9, 9, 48, 26)
    _table_row(c, 207, 44, door_widths, door_headers, header=True, height=7, font_size=3.8)
    y = 51.0
    for row in door_schedule_rows(concept, facade):
        _table_row(c, 207, y, door_widths, row, height=6.0, font_size=3.35)
        y += 6.0
    c.text(
        207,
        y + 5,
        "SWINGS ARE SCHEMATIC PRESENTATION CONVENTIONS; HANDING IS NOT AUTHORED.",
        size=4.5,
        bold=True,
        color="#A32626",
    )

    y += 13.0
    _section_heading(c, 207, y, 198, "WINDOW SCHEDULE")
    window_headers = ("ID", "ROOM", "WALL", "W", "H", "SILL", "REFERENCE", "FLAG")
    window_widths = (24, 34, 19, 10, 10, 11, 42, 48)
    _table_row(c, 207, y + 9, window_widths, window_headers, header=True, height=7, font_size=3.9)
    y += 16.0
    for row in window_schedule_rows(concept, facade):
        _table_row(c, 207, y, window_widths, row, height=6.1, font_size=3.35)
        y += 6.1
    c.text(
        207,
        y + 5,
        "FRONT HEIGHTS/SILLS ARE STYLE-PACK-SUPPORTED; OTHERS ARE PLAN-NOMINAL, NOT FACADE-DEVELOPED.",
        size=4.4,
        bold=True,
        color="#A32626",
    )
    return _page("A-601", c, issue_date, candidate_id, fingerprint)


def _route_summary(route) -> str:
    if not route.available:
        return f"UNAVAILABLE | {'; '.join(route.reasons) or 'no explicit route'}"
    sequence = " > ".join(route.display_sequence)
    return (
        f"{route.path_kind.upper()} | ALLOWED={str(route.allowed).upper()} | "
        f"REVIEW={str(route.requires_review).upper()} | {sequence}"
    )


def _review_sheet(
    concept,
    assessment,
    candidate_id: str,
    fingerprint: str,
    issue_date: str,
) -> SheetPage:
    c = Composer()
    c.text(15, 17, _SHEET_TITLES["A-901"], size=13, bold=True, color="#243746")
    c.text(
        15,
        25,
        "FROZEN M6.2.1 REVISION DIAGNOSTIC / NOT PROFESSIONAL APPROVAL",
        size=5.5,
        color="#A32626",
    )

    # Score cards.
    cards = (
        ("EFFECTIVE SCORE", f"{assessment.overall_score:.2f}"),
        ("EVIDENCE COVERAGE", f"{assessment.evidence_coverage:.1%}"),
        (
            "BLOCKING",
            str(
                sum(
                    f.severity is FindingSeverity.BLOCKING
                    and f.status in {FindingStatus.WARNING, FindingStatus.FAIL}
                    for f in assessment.findings
                )
            ),
        ),
        (
            "MAJOR",
            str(
                sum(
                    f.severity is FindingSeverity.MAJOR
                    and f.status in {FindingStatus.WARNING, FindingStatus.FAIL}
                    for f in assessment.findings
                )
            ),
        ),
    )
    for index, (label, value) in enumerate(cards):
        x = 15 + index * 97.5
        c.rect(
            BBox(x, 34, x + 90, 59),
            stroke="#8C9AA0",
            fill="#F6F8F8",
            width=0.2,
            role="review-metric",
        )
        c.text(x + 4, 42, label, size=4.8, bold=True, color="#60717B", role="review-metric")
        c.text(x + 4, 54, value, size=12, bold=True, color="#243746", role="review-metric")

    _section_heading(c, 15, 68, 145, "CATEGORY SCORES AND COVERAGE")
    _table_row(
        c,
        15,
        77,
        (73, 22, 22, 28),
        ("CATEGORY", "SCORE", "COVER", "STATUS"),
        header=True,
        height=7,
        font_size=4.3,
    )
    y = 84.0
    for category, score in assessment.category_scores.items():
        _table_row(
            c,
            15,
            y,
            (73, 22, 22, 28),
            (
                category.value.replace("_", " ").upper(),
                "N/A" if score.evaluated_score is None else f"{score.evaluated_score:.1f}",
                f"{score.coverage:.0%}",
                score.score_status.value.replace("_", " ").upper()[:18],
            ),
            height=7.2,
            font_size=3.8,
        )
        y += 7.2

    _section_heading(c, 169, 68, 236, "MAJOR AND MODERATE FINDINGS")
    active = [
        finding
        for finding in assessment.findings
        if finding.severity in {FindingSeverity.MAJOR, FindingSeverity.MODERATE}
        and finding.status in {FindingStatus.WARNING, FindingStatus.FAIL}
    ]
    y = 81.0
    for finding in active:
        color = "#A32626" if finding.severity is FindingSeverity.MAJOR else "#9A6718"
        c.text(
            173,
            y,
            f"{finding.rule_id}  {finding.severity.value.upper()}  {finding.status.value.upper()}",
            size=5.2,
            bold=True,
            color=color,
            role="quality-finding",
            source_id=finding.rule_id,
        )
        y = _wrapped_text(
            c,
            173,
            y + 4,
            finding.title + ": " + finding.explanation,
            width_chars=91,
            size=4.4,
            leading_mm=2.8,
            max_lines=1,
            role="quality-finding",
        )
        if finding.rule_id in {"ADJ-006", "SAU-005"}:
            evidence = " | ".join(finding.evidence[:2])
            y = _wrapped_text(
                c,
                178,
                y,
                "EVIDENCE: " + evidence,
                width_chars=88,
                size=4.1,
                leading_mm=2.7,
                max_lines=1,
                color="#526876",
                role="quality-evidence",
            )
        y += 2.0

    audit = concept_route_audit(concept)
    route_top = max(157.0, y + 2.0)
    _section_heading(c, 15, route_top, 390, "ENTRANCE AND ROUTE EVIDENCE")
    y = route_top + 13.0
    routes = (
        ("FAMILY", audit.family_route),
        ("GUEST", audit.guest_route),
        ("SERVICE", audit.service_route.preferred_route),
        ("GUEST WC", audit.guest_wc_route.preferred_route),
    )
    for label, route in routes:
        c.text(19, y, label, size=4.8, bold=True, color="#355C6B", role="route-evidence")
        y = _wrapped_text(
            c,
            48,
            y,
            _route_summary(route),
            width_chars=143,
            size=4.2,
            leading_mm=2.8,
            max_lines=2,
            role="route-evidence",
        )
        y += 2.0

    lower = max(202.0, y + 2.0)
    _section_heading(c, 15, lower, 190, "UNSUPPORTED / NOT EVALUABLE")
    _section_heading(c, 215, lower, 190, "ASSUMPTIONS AND LIMITATIONS")
    unsupported = [
        finding for finding in assessment.findings if finding.status is FindingStatus.NOT_EVALUABLE
    ]
    y_left = lower + 12.0
    for finding in unsupported[:5]:
        y_left = (
            _wrapped_text(
                c,
                19,
                y_left,
                f"{finding.rule_id}: {finding.title}",
                width_chars=73,
                size=4.2,
                leading_mm=2.8,
                max_lines=2,
                role="unsupported-check",
            )
            + 1.4
        )
    limits = (
        "This sheet reports the frozen assessment; it does not recalculate, hide, or improve scores.",
        "External site-path geometry, surveyed north, door handing, detailed furniture clearance, structure, MEP, fire, accessibility, energy and municipal compliance are unavailable.",
        (
            "The frozen assessment status is "
            f"{assessment.score_status.value.replace('_', ' ')}; it is not architectural, "
            "regulatory, permit, construction or professional approval."
        ),
    )
    y_right = lower + 12.0
    for note in limits:
        y_right = (
            _wrapped_text(
                c,
                219,
                y_right,
                note,
                width_chars=75,
                size=4.3,
                leading_mm=2.8,
                max_lines=2,
                role="limitation",
            )
            + 2.0
        )
    return _page("A-901", c, issue_date, candidate_id, fingerprint, review_variant=True)


def _index_entries(
    mode: SheetSetMode,
    candidate_id: str,
    fingerprint: str,
    scales: dict[str, str],
) -> tuple[SheetIndexEntry, ...]:
    numbers = ("A-001", "A-101", "A-201", "A-601")
    if mode in {"review", "all"}:
        numbers = (*numbers, "A-901")
    entries = []
    for number in numbers:
        included = []
        if number != "A-901" and mode in {"concept", "all"}:
            included.append("architectural_concept_sheet_set.pdf")
        if mode in {"review", "all"}:
            included.append("architectural_review_sheet_set.pdf")
        entries.append(
            SheetIndexEntry(
                sheet_number=number,
                title=_SHEET_TITLES[number],
                revision="P01",
                issue_status="CONCEPT ISSUE - NOT FOR CONSTRUCTION",
                paper_size="A3",
                orientation="landscape",
                scale=scales[number],
                source_candidate_id=candidate_id,
                source_geometry_fingerprint=fingerprint,
                output_filename=_SHEET_FILENAMES[number],
                included_in=tuple(included),
            )
        )
    return tuple(entries)


def _validate_build(
    build: ArchitecturalSheetBuild,
    *,
    concept: Concept,
    facade,
    assessment,
) -> SheetValidation:
    checks: list[dict[str, object]] = []

    def record(check_id: str, passed: bool, details: str) -> None:
        checks.append({"id": check_id, "passed": passed, "details": details})

    expected_concept = ("A-001", "A-101", "A-201", "A-601")
    expected_review = (*expected_concept, "A-901")
    record(
        "SHT-001",
        tuple(page.number for page in build.concept_pages) == expected_concept,
        "clean concept page order",
    )
    record(
        "SHT-002",
        tuple(page.number for page in build.review_pages) == expected_review,
        "design review page order",
    )
    record(
        "SHT-003",
        not build.profile.validate(),
        "; ".join(build.profile.validate()) or "graphic profile valid",
    )
    record(
        "SHT-004",
        all(
            page.candidate_id == build.concept_pages[0].candidate_id
            for page in (*build.concept_pages, *build.review_pages)
        ),
        "candidate identity consistent",
    )
    record(
        "SHT-005",
        all(
            page.geometry_fingerprint == geometry_fingerprint(concept)
            for page in (*build.concept_pages, *build.review_pages)
        ),
        "source geometry fingerprint consistent",
    )
    record(
        "SHT-006",
        len(room_schedule_rows(concept, assessment)) == len(concept.rooms),
        "room schedule complete",
    )
    record(
        "SHT-007",
        len(door_schedule_rows(concept, facade)) == len(concept.doors),
        "door schedule complete",
    )
    record(
        "SHT-008",
        len(window_schedule_rows(concept, facade)) == len(concept.windows),
        "window schedule complete",
    )
    record(
        "SHT-009",
        all(not item.unresolved for item in build.collisions),
        f"{sum(item.unresolved for item in build.collisions)} unresolved annotation collisions",
    )
    page_scales = {page.number: page.scale for page in build.review_pages}
    valid_scales = all(
        value == "NTS" or (value.startswith("1:") and value[2:].isdigit() and int(value[2:]) > 0)
        for value in page_scales.values()
    )
    record(
        "SHT-011",
        valid_scales
        and all(entry.scale == page_scales[entry.sheet_number] for entry in build.index_entries),
        "valid page scales match the sheet index",
    )
    validation_pages: list[SheetPage] = []
    seen_variants: set[tuple[str, bool]] = set()
    for page in (*build.concept_pages, *build.review_pages):
        key = (page.number, page.review_variant)
        if key not in seen_variants:
            validation_pages.append(page)
            seen_variants.add(key)
    for page in validation_pages:
        within = all(
            _primitive_within_page(
                item, build.profile.paper_width_mm, build.profile.paper_height_mm
            )
            for item in page.primitives
        )
        record(
            f"SHT-BND-{page.number}-{'R' if page.review_variant else 'C'}",
            within,
            "full primitive bounds within A3 media",
        )
        title_block = [item for item in page.primitives if item.role == "title-block"]
        record(
            f"SHT-TTLB-{page.number}-{'R' if page.review_variant else 'C'}",
            bool(title_block)
            and all(
                _primitive_within_page(
                    item, build.profile.paper_width_mm, build.profile.paper_height_mm
                )
                for item in title_block
            ),
            "title-block primitives within A3 media",
        )
        text = " ".join(item.text for item in page.primitives if item.kind == "text")
        record(
            f"SHT-DIS-{page.number}-{'R' if page.review_variant else 'C'}",
            "DEMO DATA" in text and "NOT FOR CONSTRUCTION" in text,
            "required disclaimer and status present",
        )
        body = [item for item in page.primitives if item.role not in {"title-block", "disclaimer"}]

        def bottom(item: Primitive) -> float:
            if item.kind == "rect":
                return item.y + item.height
            if item.kind == "circle":
                return item.y + item.radius
            if item.kind == "text":
                return item.y
            return max((point[1] for point in item.points), default=0.0)

        record(
            f"SHT-BODY-{page.number}-{'R' if page.review_variant else 'C'}",
            all(bottom(item) <= 249.5 for item in body),
            "body content clears disclaimer and title block",
        )
    record(
        "SHT-010",
        any(
            f"{assessment.overall_score:.2f}" in item.text
            for page in build.review_pages
            for item in page.primitives
            if item.kind == "text"
        ),
        "supplied assessment score is reported without rescoring",
    )
    return SheetValidation(
        passed=all(bool(item["passed"]) for item in checks), checks=tuple(checks)
    )


def build_architectural_sheets(
    *,
    plot,
    envelope,
    rules,
    concept: Concept,
    facade,
    pack_ref,
    pack_data,
    quality_assessment,
    candidate_id: str,
    issue_date: str,
    mode: SheetSetMode = "all",
    profile: GraphicProfile = GRAPHIC_PROFILE,
) -> ArchitecturalSheetBuild:
    """Build both page variants; ``mode`` controls only individual/index publication."""
    errors = profile.validate()
    if errors:
        raise ValueError("invalid sheet graphic profile: " + "; ".join(errors))
    if mode not in {"none", "concept", "review", "all"}:
        raise ValueError(f"unsupported sheet-set mode: {mode}")
    fingerprint = geometry_fingerprint(concept)
    cover = _cover_sheet(
        plot, envelope, rules, concept, quality_assessment, candidate_id, fingerprint, issue_date
    )
    clean_plan, clean_collisions, clean_furniture = _plan_sheet(
        plot,
        envelope,
        rules,
        concept,
        quality_assessment,
        candidate_id,
        fingerprint,
        issue_date,
        review=False,
    )
    review_plan, review_collisions, review_furniture = _plan_sheet(
        plot,
        envelope,
        rules,
        concept,
        quality_assessment,
        candidate_id,
        fingerprint,
        issue_date,
        review=True,
    )
    elevation = _elevation_sheet(
        concept, facade, pack_ref, pack_data, candidate_id, fingerprint, issue_date
    )
    schedules = _schedule_sheet(
        concept, facade, quality_assessment, candidate_id, fingerprint, issue_date
    )
    review = _review_sheet(concept, quality_assessment, candidate_id, fingerprint, issue_date)
    concept_pages = (cover, clean_plan, elevation, schedules)
    review_pages = (cover, review_plan, elevation, schedules, review)
    selected_plan = review_plan if mode in {"review", "all"} else clean_plan
    individual_pages = (
        (_SHEET_FILENAMES["A-001"], cover),
        (_SHEET_FILENAMES["A-101"], selected_plan),
        (_SHEET_FILENAMES["A-201"], elevation),
        (_SHEET_FILENAMES["A-601"], schedules),
        *(((_SHEET_FILENAMES["A-901"], review),) if mode in {"review", "all"} else ()),
    )
    build = ArchitecturalSheetBuild(
        profile=profile,
        concept_pages=concept_pages,
        review_pages=review_pages,
        individual_pages=individual_pages,
        index_entries=_index_entries(
            mode,
            candidate_id,
            fingerprint,
            {page.number: page.scale for page in review_pages},
        ),
        collisions=review_collisions if mode in {"review", "all"} else clean_collisions,
        furniture=review_furniture if mode in {"review", "all"} else clean_furniture,
    )
    validation = _validate_build(
        build, concept=concept, facade=facade, assessment=quality_assessment
    )
    return ArchitecturalSheetBuild(**{**build.__dict__, "validation": validation})


__all__ = [
    "PlanTransform",
    "build_architectural_sheets",
    "door_schedule_rows",
    "plan_transform",
    "room_schedule_rows",
    "select_scale",
    "window_schedule_rows",
]
