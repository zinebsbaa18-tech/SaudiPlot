"""Engineering SVG front-elevation preview (M4 technical preview).

Renders the canonical FacadeConcept geometry only (ARCHITECTURE.md D1) - no
raster images, no external fonts, deterministic element ordering, stable
viewBox. Arabic strings are emitted in logical Unicode order with
direction="rtl" so conforming viewers shape them correctly.
"""

from __future__ import annotations

from pathlib import Path

from saudi_plot_design.elevation.models import FacadeConcept
from saudi_plot_design.styles.schema import StylePackData

_SCALE = 60.0  # px per meter
_PAD = 80.0
_TITLE_ZONE = 88.0
_LEGEND_ZONE = 120.0
_GROUND_EXTEND_M = 1.5

_OPENING_FILL = {"door": "#7a4a1f", "window": "#9ec7e8"}


def render_facade_svg(facade: FacadeConcept, pack_data: StylePackData) -> str:
    wall = facade.facade_wall
    if wall is None:
        raise ValueError("cannot render a rejected facade without geometry")
    width_m = wall.length_m + 2 * _GROUND_EXTEND_M
    page_w = width_m * _SCALE + 2 * _PAD
    page_h = wall.total_height_m * _SCALE + 2 * _PAD + _TITLE_ZONE + _LEGEND_ZONE

    def px(x: float, z: float) -> tuple[float, float]:
        # Facade X left-to-right as seen from the street; Z up (SVG y down).
        return (
            _PAD + (_GROUND_EXTEND_M + x) * _SCALE,
            _PAD + _TITLE_ZONE + (wall.total_height_m - z) * _SCALE,
        )

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{page_w:.0f}" '
        f'height="{page_h:.0f}" viewBox="0 0 {page_w:.0f} {page_h:.0f}" '
        f'font-family="monospace">',
        f'<rect width="{page_w:.0f}" height="{page_h:.0f}" fill="white"/>',
        _title_block(facade, page_h),
    ]
    # Elements in canonical order (already deterministic in the concept).
    for element in facade.facade_elements:
        parts.append(_element_svg(element, px))
    for opening in facade.facade_openings:
        (x0, y0) = px(opening.x_start_m, opening.head_elevation_m)
        w = opening.width_m * _SCALE
        h = (opening.head_elevation_m - opening.sill_elevation_m) * _SCALE
        parts.append(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{_OPENING_FILL[opening.opening_type]}" stroke="#1a1a1a" '
            f'stroke-width="1.5" data-source-plan-opening="{opening.source_plan_opening_id}" '
            f'data-source-plan-wall="{opening.source_plan_wall_id}"/>'
        )
        if opening.entrance_type:
            cx = x0 + w / 2
            parts.append(
                f'<text x="{cx:.1f}" y="{y0 - 6:.1f}" font-size="11" '
                f'text-anchor="middle">{opening.entrance_type} entrance</text>'
            )
    parts.append(_ground_line(wall, px))
    parts.append(_dimensions(wall, px))
    parts.append(_legend(facade, pack_data, page_h))
    parts.append("</svg>")
    return "\n".join(parts)


def write_facade_svg(path: str | Path, facade: FacadeConcept, pack_data: StylePackData) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_facade_svg(facade, pack_data), encoding="utf-8")
    return path


def _element_svg(element, px) -> str:
    g = element.geometry
    attrs = (
        f'data-element-type="{element.element_type}" data-source-rule="{element.source_rule_id}"'
    )
    if g["kind"] == "rect":
        (x0, y0) = px(g["x"], g["z"] + g["h"])
        outline_only = element.element_type in ("entrance_frame", "window_frame")
        fill = "none" if outline_only else element.color_hex
        stroke = element.color_hex if outline_only else "#1a1a1a"
        stroke_w = 3.0 if outline_only else 1.0
        return (
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{g["w"] * _SCALE:.1f}" '
            f'height="{g["h"] * _SCALE:.1f}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{stroke_w}" {attrs}/>'
        )
    points = " ".join(f"{px(x, z)[0]:.1f},{px(x, z)[1]:.1f}" for x, z in g["points"])
    return (
        f'<polygon points="{points}" fill="{element.color_hex}" stroke="#1a1a1a" '
        f'stroke-width="1.0" {attrs}/>'
    )


def _ground_line(wall, px) -> str:
    (x0, y0) = px(-_GROUND_EXTEND_M, 0.0)
    (x1, _) = px(wall.length_m + _GROUND_EXTEND_M, 0.0)
    return (
        f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y0:.1f}" '
        f'stroke="#000000" stroke-width="3"/>'
        f'<text x="{x0:.1f}" y="{y0 + 16:.1f}" font-size="10">finished ground 0.00</text>'
    )


def _dimensions(wall, px) -> str:
    (x0, y_base) = px(0.0, 0.0)
    (x1, _) = px(wall.length_m, 0.0)
    (_, y_wall) = px(0.0, wall.wall_height_m)
    (_, y_total) = px(0.0, wall.total_height_m)
    dim_y = y_base + 34
    side_x = x0 - 30
    return "\n".join(
        [
            f'<line x1="{x0:.1f}" y1="{dim_y:.1f}" x2="{x1:.1f}" y2="{dim_y:.1f}" '
            f'stroke="#555" stroke-width="1"/>',
            f'<text x="{(x0 + x1) / 2:.1f}" y="{dim_y + 14:.1f}" font-size="11" '
            f'text-anchor="middle">facade length {wall.length_m:g} m</text>',
            f'<line x1="{side_x:.1f}" y1="{y_base:.1f}" x2="{side_x:.1f}" y2="{y_total:.1f}" '
            f'stroke="#555" stroke-width="1"/>',
            f'<text x="{side_x - 6:.1f}" y="{(y_base + y_wall) / 2:.1f}" font-size="11" '
            f'text-anchor="middle" transform="rotate(-90 {side_x - 6:.1f} '
            f'{(y_base + y_wall) / 2:.1f})">wall {wall.wall_height_m:g} m</text>',
            f'<text x="{side_x - 6:.1f}" y="{(y_wall + y_total) / 2:.1f}" font-size="10" '
            f'text-anchor="middle" transform="rotate(-90 {side_x - 6:.1f} '
            f'{(y_wall + y_total) / 2:.1f})">+{wall.parapet_height_m:g}</text>',
        ]
    )


def _title_block(facade: FacadeConcept, page_h: float) -> str:
    wall = facade.facade_wall
    sel = facade.primary_facade_selection
    status = "VALID" if facade.is_valid else "REJECTED/INVALID"
    return "\n".join(
        [
            f'<text x="{_PAD:.0f}" y="28" font-size="15" font-weight="bold">'
            f"Front elevation (technical preview, M4) [{status}]</text>",
            f'<text x="{_PAD:.0f}" y="46" font-size="11">character zone: '
            f"{facade.character_match_zone_id} | style pack: {facade.style_pack_id} "
            f"v{facade.style_pack_version} | scale: 1 m = {_SCALE:g} px (preview only, "
            f"not a certified scale)</text>",
            f'<text x="{_PAD:.0f}" y="62" font-size="10">source plan walls: '
            f"{', '.join(wall.source_plan_wall_ids)} | primary street boundary: "
            f"{sel.selected_plot_boundary_id} | plan concept: {facade.plan_concept_id}</text>",
            f'<text x="{_PAD:.0f}" y="{page_h - 12:.0f}" font-size="10" fill="#8b0000">'
            f"{_esc(facade.disclaimer)}</text>",
        ]
    )


def _legend(facade: FacadeConcept, pack_data: StylePackData, page_h: float) -> str:
    used = {}
    for element in facade.facade_elements:
        used.setdefault(element.material_id, element.color_hex)
    materials = {m.id: m for m in pack_data.materials.material_palette}
    parts = [
        f'<text x="{_PAD:.0f}" y="{page_h - _LEGEND_ZONE + 4:.0f}" font-size="12" '
        f'font-weight="bold">materials (DEMO)</text>'
    ]
    y = page_h - _LEGEND_ZONE + 22
    for material_id in sorted(used):
        color = used[material_id]
        entry = materials[material_id]
        parts.append(
            f'<rect x="{_PAD:.0f}" y="{y - 10:.0f}" width="14" height="12" '
            f'fill="{color}" stroke="#333"/>'
            f'<text x="{_PAD + 22:.0f}" y="{y:.0f}" font-size="11">{_esc(entry.name_en)} '
            f"({color})</text>"
            # Arabic stays in logical Unicode order; direction="rtl" lets
            # conforming viewers shape and order it correctly.
            f'<text x="{_PAD + 420:.0f}" y="{y:.0f}" font-size="11" direction="rtl" '
            f'text-anchor="end">{_esc(entry.name_ar)}</text>'
        )
        y += 18
    return "\n".join(parts)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
