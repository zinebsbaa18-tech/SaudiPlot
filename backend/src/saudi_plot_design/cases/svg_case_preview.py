"""Technical inspection preview SVG for an ingested case (M6A).

This is a review aid, not a client presentation drawing. It draws only data
that actually exists in the case: wall axes with real coordinates (one panel
per storey so floors never overlap), opening markers at their host wall
midpoint (explicitly labeled approximate), and a space/classification table.
Spaces have no extracted footprints in M6A, so no room outlines are drawn -
nothing is fabricated. Output is deterministic: no timestamps, sorted
iteration everywhere.
"""

from __future__ import annotations

import html

from saudi_plot_design.cases.models import ArchitecturalDesignCase, CaseState, CaseWall

_PLAN_W = 640.0
_PLAN_H = 420.0
_MARGIN = 30.0
_PANEL_TOP = 50.0
_PANEL_GAP = 14.0
_PANEL_W = 560.0
_ROW_H = 16.0

_STATE_NOTES = {
    CaseState.APPROVED_TEMPLATE: "APPROVED TEMPLATE",
    CaseState.REJECTED: "REJECTED - do not use",
}


def render_case_preview(case: ArchitecturalDesignCase) -> str:
    parts: list[str] = []
    banner = _STATE_NOTES.get(
        case.state, f"STATE: {case.state.value.upper()} - NOT AN APPROVED TEMPLATE"
    )
    parts.append(
        f'<text x="10" y="20" font-size="14" font-weight="bold" fill="#b00">'
        f"{html.escape(banner)}</text>"
    )
    parts.append(
        f'<text x="10" y="38" font-size="11" fill="#333">case '
        f"{html.escape(case.case_id)} | schema {html.escape(case.provenance.ifc_schema)} | "
        f"source sha256 {html.escape(case.provenance.source_fingerprint[:16])}... | "
        f"technical inspection preview (not a presentation drawing)</text>"
    )

    wall_by_id = {w.ifc_global_id: w for w in case.walls}
    openings = sorted(list(case.doors) + list(case.windows), key=lambda o: o.ifc_global_id)

    # One panel per storey: multi-storey walls must never overlap in one
    # coordinate system. Openings render in their HOST wall's panel so the
    # marker aligns with the drawn wall.
    panel_y = _PANEL_TOP
    for level in case.levels:
        level_walls = [
            w
            for w in case.walls
            if w.level_id == level.ifc_global_id and w.start is not None and w.end is not None
        ]
        level_openings = [
            o
            for o in openings
            if o.host_wall_id is not None
            and o.host_wall_id in wall_by_id
            and wall_by_id[o.host_wall_id].level_id == level.ifc_global_id
        ]
        skipped = sum(
            1
            for w in case.walls
            if w.level_id == level.ifc_global_id and (w.start is None or w.end is None)
        )
        parts.extend(_level_panel(level, level_walls, level_openings, wall_by_id, panel_y, skipped))
        panel_y += _PLAN_H + _PANEL_GAP

    legend = (
        "external wall (thick) | internal wall (thin) | O door | [] window - "
        "opening markers sit at the host wall midpoint (approximate)"
    )
    parts.append(
        f'<text x="{_MARGIN}" y="{round(panel_y, 1)}" font-size="10" fill="#555">'
        f"{html.escape(legend)}</text>"
    )
    panel_y += _ROW_H

    table_x = _PLAN_W + 10
    y = 60.0
    parts.append(
        f'<text x="{table_x}" y="{y}" font-size="12" font-weight="bold" fill="#000">'
        f"Spaces ({len(case.spaces)}) - all classifications require review</text>"
    )
    y += _ROW_H
    for space in sorted(case.spaces, key=lambda s: s.ifc_global_id):
        area = f"{space.area_m2:g} m2" if space.area_m2 is not None else "area?"
        row = (
            f"{space.ifc_global_id[:8]} {space.name} | {space.space_type.value} "
            f"({space.space_type.confidence:.1f}) | {space.zone.value} | {area} | "
            f"{space.space_type.reviewer_status}"
        )
        parts.append(
            f'<text x="{table_x}" y="{round(y, 1)}" font-size="9" fill="#222">'
            f"{html.escape(row)}</text>"
        )
        y += _ROW_H

    y += _ROW_H
    metric_rows = (
        f"net room area: {case.metrics.net_room_area_m2:g} m2"
        + ("" if case.metrics.area_metrics_complete else " (INCOMPLETE - missing source areas)"),
        f"circulation: {case.metrics.circulation_area_m2:g} m2"
        + (
            f" ({case.metrics.circulation_percent:g}%)"
            if case.metrics.circulation_percent is not None
            else ""
        ),
        f"bedrooms: {case.metrics.bedroom_count} | bathrooms: {case.metrics.bathroom_count}",
        f"entrances: {case.metrics.entrance_counts or 'none classified'}",
        f"warnings: {len(case.warnings)} | levels: {len(case.levels)} | "
        f"facade openings: {len(case.facade_openings)}",
    )
    parts.append(
        f'<text x="{table_x}" y="{round(y, 1)}" font-size="12" font-weight="bold" '
        f'fill="#000">Descriptive metrics (no quality claim)</text>'
    )
    y += _ROW_H
    for row in metric_rows:
        parts.append(
            f'<text x="{table_x}" y="{round(y, 1)}" font-size="9" fill="#222">'
            f"{html.escape(row)}</text>"
        )
        y += _ROW_H

    height = max(panel_y, y) + _MARGIN
    body = "\n".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_PLAN_W + _PANEL_W:g}" height="{height:g}" '
        f'viewBox="0 0 {_PLAN_W + _PANEL_W:g} {height:g}">\n'
        f'<rect width="100%" height="100%" fill="#fff"/>\n'
        f"{body}\n</svg>\n"
    )


def _level_panel(
    level,
    walls: list[CaseWall],
    openings,
    wall_by_id,
    panel_y: float,
    skipped: int,
) -> list[str]:
    parts: list[str] = []
    elevation = f"{level.elevation_m:g} m" if level.elevation_m is not None else "elevation?"
    label = f"Level: {level.name} ({elevation})"
    if skipped:
        label += f" | {skipped} wall(s) without axis not drawn"
    parts.append(
        f'<text x="{_MARGIN}" y="{round(panel_y + 14, 1)}" font-size="11" '
        f'font-weight="bold" fill="#000">{html.escape(label)}</text>'
    )

    points = [p for w in walls for p in (w.start, w.end)]
    if points:
        min_x = min(p[0] for p in points)
        max_x = max(p[0] for p in points)
        min_y = min(p[1] for p in points)
        max_y = max(p[1] for p in points)
        span_x = max(max_x - min_x, 1e-6)
        span_y = max(max_y - min_y, 1e-6)
        scale = min((_PLAN_W - 2 * _MARGIN) / span_x, (_PLAN_H - 2 * _MARGIN - 20) / span_y)
    else:
        min_x = min_y = 0.0
        scale = 1.0
        parts.append(
            f'<text x="{_MARGIN}" y="{round(panel_y + 34, 1)}" font-size="10" '
            f'fill="#555">no wall axis geometry on this level</text>'
        )

    def to_svg(p: tuple[float, float]) -> tuple[float, float]:
        # SVG y grows downward; plan north stays up.
        x = _MARGIN + (p[0] - min_x) * scale
        y = panel_y + _PLAN_H - _MARGIN - (p[1] - min_y) * scale
        return round(x, 2), round(y, 2)

    for wall in walls:
        (x1, y1), (x2, y2) = to_svg(wall.start), to_svg(wall.end)
        color = "#c40" if wall.is_external else "#444"
        width = 3 if wall.is_external else 1.5
        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{color}" stroke-width="{width}">'
            f"<title>{html.escape(wall.ifc_global_id)} {html.escape(wall.name)}</title></line>"
        )

    for opening in openings:
        host = wall_by_id[opening.host_wall_id]
        if host.start is None or host.end is None:
            continue
        mid = ((host.start[0] + host.end[0]) / 2, (host.start[1] + host.end[1]) / 2)
        x, y = to_svg(mid)
        if opening.kind == "door":
            parts.append(
                f'<circle cx="{x}" cy="{y}" r="5" fill="none" stroke="#06c" '
                f'stroke-width="1.5"><title>door {html.escape(opening.ifc_global_id)} '
                f"(marker at host wall midpoint - approximate)</title></circle>"
            )
        else:
            parts.append(
                f'<rect x="{x - 4}" y="{y - 4}" width="8" height="8" fill="none" '
                f'stroke="#080" stroke-width="1.5"><title>window '
                f"{html.escape(opening.ifc_global_id)} "
                f"(marker at host wall midpoint - approximate)</title></rect>"
            )
    return parts
