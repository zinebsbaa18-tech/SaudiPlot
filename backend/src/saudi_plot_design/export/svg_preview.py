"""Engineering SVG preview of a Compact 3BR concept (M2 technical preview).

Renders the canonical concept geometry only (ARCHITECTURE.md D1) - plot,
envelope, footprint, rooms, walls, doors, windows, labels, basic dimensions,
and the street reference direction. This is a development preview, not a
deliverable sheet; PDF/DXF come in M5.
"""

from __future__ import annotations

from pathlib import Path

from saudi_plot_design.model import BuildableEnvelope, Concept, PlotModel, Zone
from saudi_plot_design.output import DISCLAIMER

_SCALE = 28.0  # px per meter
_PAD = 70.0  # px page padding
_TITLE_ZONE = 55.0  # px reserved above the drawing so labels never hit the title
_ZONE_FILL = {
    Zone.PUBLIC: "#d9c7a3",
    Zone.FAMILY: "#c6d9b8",
    Zone.PRIVATE: "#b8c9d9",
    Zone.WET_SERVICE: "#d9b8c4",
    Zone.CIRCULATION: "#e8e4da",
}


def render_concept_svg(plot: PlotModel, envelope: BuildableEnvelope, concept: Concept) -> str:
    """Render the SVG document as a string."""
    xs = [c[0] for c in plot.corners]
    ys = [c[1] for c in plot.corners]
    world_w, world_h = max(xs) - min(xs), max(ys) - min(ys)
    page_w = world_w * _SCALE + 2 * _PAD
    page_h = world_h * _SCALE + 2 * _PAD + _TITLE_ZONE + 30  # title zone + disclaimer row

    def px(x: float, y: float) -> tuple[float, float]:
        # World +y points away from the street; SVG y grows downward. The
        # drawing area starts below the reserved title zone so the street
        # label of a rotated plot cannot collide with the title block.
        return (
            _PAD + (x - min(xs)) * _SCALE,
            _PAD + _TITLE_ZONE + (max(ys) - y) * _SCALE,
        )

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{page_w:.0f}" '
        f'height="{page_h:.0f}" viewBox="0 0 {page_w:.0f} {page_h:.0f}" '
        f'font-family="monospace">',
        f'<rect width="{page_w:.0f}" height="{page_h:.0f}" fill="white"/>',
        _title_block(concept, page_w, page_h),
    ]
    parts.append(_polygon(plot.corners, px, "none", "#000000", 2.5))
    parts.append(_polygon(envelope.corners, px, "none", "#2e7d32", 1.5, dash="8 5"))
    if concept.footprint is not None:
        fp = concept.footprint
        fp_corners = (
            (fp.min_x, fp.min_y),
            (fp.max_x, fp.min_y),
            (fp.max_x, fp.max_y),
            (fp.min_x, fp.max_y),
        )
        parts.append(_polygon(fp_corners, px, "none", "#444444", 2.0))
    for room in concept.rooms:
        r = room.rect
        x, y = px(r.min_x, r.max_y)
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{r.width * _SCALE:.1f}" '
            f'height="{r.height * _SCALE:.1f}" fill="{_ZONE_FILL[room.zone]}" '
            f'fill-opacity="0.55" stroke="none"/>'
        )
        cx, cy = px((r.min_x + r.max_x) / 2, (r.min_y + r.max_y) / 2)
        parts.append(
            f'<text x="{cx:.1f}" y="{cy - 5:.1f}" font-size="10" text-anchor="middle">'
            f"{_esc(room.name)}</text>"
            f'<text x="{cx:.1f}" y="{cy + 8:.1f}" font-size="9" text-anchor="middle" '
            f'fill="#555">{room.area_m2:.1f} m2 ({room.width_m:.1f}x{room.length_m:.1f})</text>'
        )
    for wall in concept.walls:
        (x1, y1), (x2, y2) = px(*wall.start), px(*wall.end)
        stroke_width = 4.0 if wall.is_external else 2.0
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#1a1a1a" stroke-width="{stroke_width}"/>'
        )
    walls = {w.id: w for w in concept.walls}
    for door in concept.doors:
        parts.append(
            _opening_marker(walls[door.wall_id], door.position_m, door.width_m, px, "#8d5a2b")
        )
    for window in concept.windows:
        parts.append(
            _opening_marker(walls[window.wall_id], window.position_m, window.width_m, px, "#1565c0")
        )
    parts.append(_dimensions(plot, envelope, concept, px))
    parts.append(_street_arrow(plot, px))
    parts.append("</svg>")
    return "\n".join(parts)


def write_concept_svg(
    path: str | Path, plot: PlotModel, envelope: BuildableEnvelope, concept: Concept
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_concept_svg(plot, envelope, concept), encoding="utf-8")
    return path


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _polygon(corners, px, fill: str, stroke: str, width: float, dash: str | None = None) -> str:
    points = " ".join(f"{px(x, y)[0]:.1f},{px(x, y)[1]:.1f}" for x, y in corners)
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<polygon points="{points}" fill="{fill}" stroke="{stroke}" '
        f'stroke-width="{width}"{dash_attr}/>'
    )


def _opening_marker(wall, position: float, width: float, px, color: str) -> str:
    (sx, sy), (ex, ey) = wall.start, wall.end
    length = wall.length_m
    ux, uy = (ex - sx) / length, (ey - sy) / length
    a = (sx + ux * position, sy + uy * position)
    b = (sx + ux * (position + width), sy + uy * (position + width))
    (x1, y1), (x2, y2) = px(*a), px(*b)
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{color}" stroke-width="6" stroke-linecap="butt"/>'
    )


def _dimensions(plot: PlotModel, envelope: BuildableEnvelope, concept: Concept, px) -> str:
    xs = [c[0] for c in plot.corners]
    ys = [c[1] for c in plot.corners]
    plot_w, plot_h = max(xs) - min(xs), max(ys) - min(ys)
    x0, y0 = px(min(xs), min(ys))
    x1, _ = px(max(xs), min(ys))
    _, y1 = px(min(xs), max(ys))
    parts = [
        f'<text x="{(x0 + x1) / 2:.1f}" y="{y0 + 28:.1f}" font-size="11" '
        f'text-anchor="middle">plot width {plot_w:g} m</text>',
        f'<text x="{x0 - 28:.1f}" y="{(y0 + y1) / 2:.1f}" font-size="11" '
        f'text-anchor="middle" transform="rotate(-90 {x0 - 28:.1f} {(y0 + y1) / 2:.1f})">'
        f"plot depth {plot_h:g} m</text>",
    ]
    if concept.footprint is not None:
        fp = concept.footprint
        fx, fy = px((fp.min_x + fp.max_x) / 2, fp.max_y)
        parts.append(
            f'<text x="{fx:.1f}" y="{fy - 6:.1f}" font-size="10" text-anchor="middle" '
            f'fill="#444">footprint {fp.width:.1f} x {fp.height:.1f} m | envelope '
            f"{envelope.width_m:g} x {envelope.depth_m:g} m</text>"
        )
    return "\n".join(parts)


def _street_arrow(plot: PlotModel, px) -> str:
    (x1, y1), (x2, y2) = plot.edge_corners(plot.street_edge_index)
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    ax, ay = px(mx, my)
    ay += 46 if my <= 0.01 else -46  # place outside the plot on the street side
    return (
        f'<text x="{ax:.1f}" y="{ay:.1f}" font-size="12" text-anchor="middle" '
        f'font-weight="bold">STREET (reference direction - north unknown)</text>'
    )


def _title_block(concept: Concept, page_w: float, page_h: float) -> str:
    status = "VALID" if concept.is_valid else "REJECTED/INVALID"
    return (
        f'<text x="{_PAD:.0f}" y="30" font-size="14" font-weight="bold">'
        f"Compact 3BR concept preview - {_esc(concept.concept_id)} [{status}]</text>"
        f'<text x="{_PAD:.0f}" y="46" font-size="10">technical preview (M2) - '
        f"not a deliverable sheet</text>"
        f'<text x="{_PAD:.0f}" y="{page_h - 14:.0f}" font-size="10" fill="#8b0000">'
        f"{_esc(DISCLAIMER)}</text>"
    )
