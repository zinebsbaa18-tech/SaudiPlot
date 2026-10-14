"""A3 PDF export (M5): two vector sheets rendered from canonical geometry.

Sheet 1: site + floor plan. Sheet 2: Saudi character + front elevation.
ReportLab ``invariant=1`` makes output byte-deterministic (fixed creation
date, no random document id).

Arabic fallback (documented): the base-14 PDF fonts cannot shape Arabic and
external fonts are out of scope, so the Arabic style name is stored in
logical Unicode order in the PDF metadata (Keywords) and referenced by an
on-sheet note. DXF and run.json carry the Arabic text directly.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from saudi_plot_design.export.runlog import GENERATOR_VERSION
from saudi_plot_design.model import EXTERIOR
from saudi_plot_design.output import DISCLAIMER

PAGE_W, PAGE_H = landscape(A3)  # points

PLAN_SCALE_MM_PER_M = 5.0  # 1:200
ELEV_SCALE_MM_PER_M = 13.0  # ~1:77 (annotated as approximate)


class PaperTransform:
    """Explicit world-meters -> paper-points mapping (tested)."""

    def __init__(self, origin_x_mm: float, origin_y_mm: float, scale_mm_per_m: float):
        self.origin_x_mm = origin_x_mm
        self.origin_y_mm = origin_y_mm
        self.scale = scale_mm_per_m

    def pt(self, x_m: float, y_m: float) -> tuple[float, float]:
        return (
            (self.origin_x_mm + x_m * self.scale) * mm,
            (self.origin_y_mm + y_m * self.scale) * mm,
        )

    def length(self, meters: float) -> float:
        return meters * self.scale * mm


def _write_pdf(
    path: str | Path,
    plot,
    envelope,
    rules,
    concept,
    match,
    style_selection,
    pack_ref,
    pack_data,
    selection,
    facade,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(str(path), pagesize=(PAGE_W, PAGE_H), invariant=1)
    canvas.setTitle(f"Saudi Plot Design Studio - {plot.plot_id} (DEMO)")
    canvas.setAuthor("saudi-plot-design (DEMO output)")
    canvas.setCreator(f"saudi-plot-design {GENERATOR_VERSION}")
    canvas.setSubject("DEMO concept export - not official, requires verification")
    # Arabic style name stored in logical Unicode order (metadata fallback).
    canvas.setKeywords(
        f"{plot.plot_id}; {concept.concept_id}; {pack_ref.style_pack_id} "
        f"v{pack_ref.version}; name_ar={pack_ref.name_ar}; DEMO"
    )
    _sheet1(canvas, plot, envelope, rules, concept, match)
    canvas.showPage()
    _sheet2(canvas, plot, concept, match, style_selection, pack_ref, pack_data, selection, facade)
    canvas.showPage()
    canvas.save()
    return path


def _text(c, x_mm, y_mm, text, size=8, bold=False, color=(0, 0, 0)):
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.setFillColorRGB(*color)
    c.drawString(x_mm * mm, y_mm * mm, text)
    c.setFillColorRGB(0, 0, 0)


def _lines(c, x_mm, y_mm, lines, size=7, leading_mm=3.4):
    for i, line in enumerate(lines):
        _text(c, x_mm, y_mm - i * leading_mm, line, size=size)


def _title_band(c, sheet_title: str, plot, concept):
    _text(c, 12, 285, "Saudi Plot Design Studio (DEMO)", size=13, bold=True)
    _text(c, 12, 279, sheet_title, size=10, bold=True)
    _lines(
        c,
        250,
        288,
        [
            f"project: {plot.plot_id}   plot fp: {plot.fingerprint[:8]}",
            f"concept: {concept.concept_id}   concept fp: {concept.fingerprint[:8]}",
            f"generator: saudi-plot-design {GENERATOR_VERSION}   scale: see notes (approx/NTS)",
        ],
        size=7,
    )
    c.setLineWidth(0.6)
    c.line(12 * mm, 277 * mm, 408 * mm, 277 * mm)


def _disclaimer_footer(c):
    c.setLineWidth(0.4)
    c.line(12 * mm, 16 * mm, 408 * mm, 16 * mm)
    for i, line in enumerate(textwrap.wrap(DISCLAIMER, 170)):
        _text(c, 12, 12 - i * 3.5, line, size=7, color=(0.55, 0, 0))


def _sheet1(c, plot, envelope, rules, concept, match):
    _title_band(c, "Sheet 1 of 2 - Site and Floor Plan", plot, concept)
    t = PaperTransform(45.0, 60.0, PLAN_SCALE_MM_PER_M)

    c.setLineWidth(1.2)
    _polygon(c, t, plot.corners)
    for i in range(len(plot.corners)):
        (x1, y1), (x2, y2) = plot.edge_corners(i)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        label = f"edge {i + 1}: {plot.edges[i].value}"
        if plot.edges[i].value == "street":
            label += f" (width {plot.street_width_m:g} m)"
        px, py = t.pt(mx, my)
        offset = -5 * mm if my <= 0.01 else (3 * mm if my >= 29.9 else 0)
        side = -16 * mm if mx <= 0.01 else (2 * mm if mx >= 19.9 else -10 * mm)
        c.setFont("Helvetica", 7)
        c.drawString(px + (side if offset == 0 else -10 * mm), py + offset, label)

    c.setDash(3, 2)
    c.setLineWidth(0.7)
    _polygon(c, t, envelope.corners)
    c.setDash()
    fp = concept.footprint
    c.setLineWidth(0.9)
    _polygon(
        c,
        t,
        ((fp.min_x, fp.min_y), (fp.max_x, fp.min_y), (fp.max_x, fp.max_y), (fp.min_x, fp.max_y)),
    )

    for room in concept.rooms:
        r = room.rect
        cx, cy = t.pt((r.min_x + r.max_x) / 2, (r.min_y + r.max_y) / 2)
        c.setFont("Helvetica", 5.4)
        c.drawCentredString(cx, cy + 1.4 * mm, room.name)
        c.setFont("Helvetica", 5.0)
        c.drawCentredString(cx, cy - 1.6 * mm, f"{room.area_m2:.1f} m2")
    for wall in concept.walls:
        (x1, y1) = t.pt(*wall.start)
        (x2, y2) = t.pt(*wall.end)
        c.setLineWidth(1.0 if wall.is_external else 0.5)
        c.line(x1, y1, x2, y2)
    walls = {w.id: w for w in concept.walls}
    for door in concept.doors:
        _opening_tick(c, t, walls[door.wall_id], door.position_m, door.width_m, (0.55, 0.29, 0.12))
    for window in concept.windows:
        _opening_tick(
            c, t, walls[window.wall_id], window.position_m, window.width_m, (0.08, 0.4, 0.78)
        )

    _dim_h(c, t, 0.0, 20.0, -4.0, "20.00 m plot width")
    _dim_v(c, t, 0.0, 30.0, -4.0, "30.00 m plot depth")
    _dim_h(c, t, fp.min_x, fp.max_x, fp.min_y - 2.0, f"{fp.width:.2f} m footprint")

    x = 250
    _text(c, x, 268, "room schedule", size=9, bold=True)
    rows = sorted(concept.rooms, key=lambda r: (r.priority, r.id))
    for i, room in enumerate(rows):
        _text(
            c,
            x,
            262 - i * 4.2,
            f"{room.name:<24} {room.width_m:5.2f} x {room.length_m:5.2f} m",
            size=6.5,
        )
        _text(c, x + 88, 262 - i * 4.2, f"{room.area_m2:7.2f} m2", size=6.5)
    y = 262 - len(rows) * 4.2 - 2
    _text(c, x, y, f"{'total rooms':<24}", size=6.5, bold=True)
    _text(c, x + 88, y, f"{concept.total_room_area_m2:7.2f} m2", size=6.5, bold=True)

    _text(c, x, y - 9, "area summary", size=9, bold=True)
    _lines(
        c,
        x,
        y - 15,
        [
            f"plot area: {20 * 30:.1f} m2 (20.00 x 30.00 m)",
            f"buildable envelope: {envelope.area_m2:.1f} m2 ({envelope.width_m:g} x {envelope.depth_m:g} m)",
            f"building footprint: {fp.area:.1f} m2 ({fp.width:g} x {fp.height:g} m)",
        ],
    )
    _text(c, x, y - 30, "demo setback assumptions", size=9, bold=True)
    _lines(
        c,
        x,
        y - 36,
        [
            f"rule set {rules.id} ({rules.provenance.upper()}): front {rules.front_m:g} m, "
            f"sides {rules.side_m:g} m, rear {rules.rear_m:g} m",
            "values are demonstration placeholders, NOT municipal regulations",
        ],
    )
    _text(c, x, y - 48, "location & reference", size=9, bold=True)
    loc = plot.location or (0.0, 0.0)
    _lines(
        c,
        x,
        y - 54,
        [
            f"location (WGS84, user provided): lat {loc[0]:g}, lon {loc[1]:g}",
            "administrative source: user input - no geocoding or map API used",
            "north unknown in local coordinates - STREET edge is the reference",
            f"plan scale 1:{1000 / PLAN_SCALE_MM_PER_M:.0f} (approx at full A3 print), else NTS",
        ],
    )
    _disclaimer_footer(c)


def _sheet2(c, plot, concept, match, style_selection, pack_ref, pack_data, selection, facade):
    _title_band(c, "Sheet 2 of 2 - Saudi Character and Front Elevation", plot, concept)
    wall = facade.facade_wall
    t = PaperTransform(35.0, 130.0, ELEV_SCALE_MM_PER_M)

    for element in facade.facade_elements:
        _element_pdf(c, t, element)
    for opening in facade.facade_openings:
        x0, y0 = t.pt(opening.x_start_m, opening.sill_elevation_m)
        w = t.length(opening.width_m)
        h = t.length(opening.head_elevation_m - opening.sill_elevation_m)
        fill = (0.48, 0.29, 0.12) if opening.opening_type == "door" else (0.62, 0.78, 0.91)
        c.setFillColorRGB(*fill)
        c.setLineWidth(0.7)
        c.rect(x0, y0, w, h, stroke=1, fill=1)
        c.setFillColorRGB(0, 0, 0)
        if opening.entrance_type:
            c.setFont("Helvetica", 6)
            c.drawCentredString(x0 + w / 2, y0 + h + 2 * mm, f"{opening.entrance_type} entrance")
    gx0, gy = t.pt(-1.5, 0.0)
    gx1, _ = t.pt(wall.length_m + 1.5, 0.0)
    c.setLineWidth(1.6)
    c.line(gx0, gy, gx1, gy)
    _text(c, 35 - 20, 130 - 6, "finished ground 0.00", size=6.5)

    _dim_h(c, t, 0.0, wall.length_m, -1.2, f"{wall.length_m:g} m facade length")
    _dim_v(c, t, 0.0, wall.wall_height_m, -1.5, f"wall {wall.wall_height_m:g} m")
    _dim_v(
        c, t, wall.wall_height_m, wall.total_height_m, -1.5, f"+{wall.parapet_height_m:g} parapet"
    )

    x = 250
    _text(c, x, 268, "architectural character (DEMO classification)", size=9, bold=True)
    _lines(
        c,
        x,
        262,
        [
            f"character zone: {facade.character_match_zone_id} "
            f"(dataset {match.dataset_id} v{match.dataset_version})",
            f"style pack: {pack_ref.name_en} ({pack_ref.style_pack_id} v{pack_ref.version})",
            "Arabic style name: stored in logical Unicode order in PDF metadata",
            "(Keywords field) - base-14 PDF fonts cannot shape Arabic; no external",
            "fonts are bundled by design.",
            f"lookup: {match.match_method.value}, confidence {match.confidence_level} "
            f"({match.confidence_value})",
            f"style confirmation: {style_selection.selection_method.value}, "
            f"user_confirmed={style_selection.user_confirmed}",
            f"primary street boundary: {selection.selected_plot_boundary_id} (user confirmed)",
            f"source plan walls: {', '.join(wall.source_plan_wall_ids)}",
            match.demo_statement,
        ],
    )
    _text(c, x, 218, "material / color legend (DEMO)", size=9, bold=True)
    used: dict[str, str] = {}
    for element in facade.facade_elements:
        used.setdefault(element.material_id, element.color_hex)
    materials = {m.id: m for m in pack_data.materials.material_palette}
    for i, material_id in enumerate(sorted(used)):
        color = used[material_id]
        rgb = tuple(int(color[j : j + 2], 16) / 255 for j in (1, 3, 5))
        yy = 212 - i * 5
        c.setFillColorRGB(*rgb)
        c.rect(x * mm, yy * mm - 1.2 * mm, 5 * mm, 3.4 * mm, stroke=1, fill=1)
        c.setFillColorRGB(0, 0, 0)
        _text(c, x + 8, yy, f"{materials[material_id].name_en} ({color})", size=7)

    counts: dict[str, int] = {}
    for element in facade.facade_elements:
        counts[element.element_type] = counts.get(element.element_type, 0) + 1
    _text(c, x, 192, "applied style elements", size=9, bold=True)
    _lines(c, x, 186, [f"{k}: {v}" for k, v in sorted(counts.items())], size=6.5, leading_mm=3.2)

    _text(c, x, 152, "source-opening traceability", size=9, bold=True)
    trace = [
        f"{o.id} <- plan {o.source_plan_opening_id} @ {o.source_plan_wall_id} "
        f"({o.source_room_id if o.source_room_id != EXTERIOR else 'entrance'})"
        for o in facade.facade_openings
    ]
    _lines(c, x, 146, trace, size=6.5, leading_mm=3.2)

    _text(c, x, 124, "known limitations (DEMO)", size=9, bold=True)
    limitation_lines: list[str] = []
    # Rendered from the CONSUMED pack data so the PDF always agrees with the
    # run.json provenance record (never from the drift-prone reference).
    for limitation in pack_data.source_metadata.limitations:
        limitation_lines.extend(textwrap.wrap(limitation, 62))
    limitation_lines.extend(
        [
            "Single front elevation only; fence/gate omitted (no dimensional pack data).",
            "Not an officially compliant Saudi elevation; not municipality approved.",
        ]
    )
    _lines(c, x, 118, limitation_lines, size=6.2, leading_mm=3.0)
    _text(
        c,
        35,
        40,
        f"elevation scale 1:{1000 / ELEV_SCALE_MM_PER_M:.0f} (approx at full A3 print), else NTS",
        size=7,
    )
    _disclaimer_footer(c)


def _polygon(c, t: PaperTransform, corners):
    path = c.beginPath()
    first = t.pt(*corners[0])
    path.moveTo(*first)
    for corner in corners[1:]:
        path.lineTo(*t.pt(*corner))
    path.close()
    c.drawPath(path, stroke=1, fill=0)


def _element_pdf(c, t: PaperTransform, element):
    g = element.geometry
    rgb = tuple(int(element.color_hex[j : j + 2], 16) / 255 for j in (1, 3, 5))
    outline_only = element.element_type in ("entrance_frame", "window_frame")
    if g["kind"] == "rect":
        x0, y0 = t.pt(g["x"], g["z"])
        c.setLineWidth(1.0 if outline_only else 0.5)
        if outline_only:
            c.setStrokeColorRGB(*rgb)
            c.rect(x0, y0, t.length(g["w"]), t.length(g["h"]), stroke=1, fill=0)
            c.setStrokeColorRGB(0, 0, 0)
        else:
            c.setFillColorRGB(*rgb)
            c.rect(x0, y0, t.length(g["w"]), t.length(g["h"]), stroke=1, fill=1)
            c.setFillColorRGB(0, 0, 0)
    else:
        path = c.beginPath()
        pts = [t.pt(x, z) for x, z in g["points"]]
        path.moveTo(*pts[0])
        for p in pts[1:]:
            path.lineTo(*p)
        path.close()
        c.setFillColorRGB(*rgb)
        c.setLineWidth(0.5)
        c.drawPath(path, stroke=1, fill=1)
        c.setFillColorRGB(0, 0, 0)


def _opening_tick(c, t: PaperTransform, wall, position_m, width_m, rgb):
    length = wall.length_m
    ux = (wall.end[0] - wall.start[0]) / length
    uy = (wall.end[1] - wall.start[1]) / length
    a = t.pt(wall.start[0] + ux * position_m, wall.start[1] + uy * position_m)
    b = t.pt(
        wall.start[0] + ux * (position_m + width_m),
        wall.start[1] + uy * (position_m + width_m),
    )
    c.setStrokeColorRGB(*rgb)
    c.setLineWidth(2.2)
    c.line(a[0], a[1], b[0], b[1])
    c.setStrokeColorRGB(0, 0, 0)


def _dim_h(c, t: PaperTransform, x0_m, x1_m, y_m, label):
    (px0, py) = t.pt(x0_m, y_m)
    (px1, _) = t.pt(x1_m, y_m)
    c.setLineWidth(0.4)
    c.line(px0, py, px1, py)
    c.line(px0, py - 1 * mm, px0, py + 1 * mm)
    c.line(px1, py - 1 * mm, px1, py + 1 * mm)
    c.setFont("Helvetica", 6.5)
    c.drawCentredString((px0 + px1) / 2, py - 3 * mm, label)


def _dim_v(c, t: PaperTransform, y0_m, y1_m, x_m, label):
    (px, py0) = t.pt(x_m, y0_m)
    (_, py1) = t.pt(x_m, y1_m)
    c.setLineWidth(0.4)
    c.line(px, py0, px, py1)
    c.line(px - 1 * mm, py0, px + 1 * mm, py0)
    c.line(px - 1 * mm, py1, px + 1 * mm, py1)
    c.saveState()
    c.translate(px - 2 * mm, (py0 + py1) / 2)
    c.rotate(90)
    c.setFont("Helvetica", 6.5)
    c.drawCentredString(0, 0, label)
    c.restoreState()
