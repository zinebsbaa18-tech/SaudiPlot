"""Deterministic baseline/selected geometry overlay for M6.2."""

from __future__ import annotations

from html import escape
from pathlib import Path

from saudi_plot_design.layout.models import LayoutOptimizationResult
from saudi_plot_design.quality.models import FindingSeverity, FindingStatus


def render_optimization_overlay_svg(result: LayoutOptimizationResult) -> str:
    baseline = result.baseline_candidate.concept
    selected = result.selected_candidate.concept
    assessment = result.selected_candidate.quality_assessment
    assert baseline is not None and selected is not None and assessment is not None
    assert baseline.footprint is not None
    fp = baseline.footprint
    scale = min(720.0 / fp.width, 760.0 / fp.height)
    ox, oy = 55.0, 105.0
    panel_x = ox + fp.width * scale + 48.0
    view_width = max(1350.0, panel_x + 520.0)
    view_height = max(1000.0, oy + fp.height * scale + 125.0)
    affected_rooms = {
        room_id
        for audit in result.selected_candidate.transformation_audit
        for room_id in audit.affected_room_ids
    }
    changed_openings = {
        opening_id
        for audit in result.selected_candidate.transformation_audit
        for opening_id in audit.affected_opening_ids
    }

    def x(value: float) -> float:
        return ox + (value - fp.min_x) * scale

    def y(value: float) -> float:
        return oy + (fp.max_y - value) * scale

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{view_width:.0f}" '
            f'height="{view_height:.0f}" viewBox="0 0 {view_width:.0f} {view_height:.0f}">'
        ),
        f"<title>Layout optimization overlay — {escape(result.selected_candidate_id)}</title>",
        (
            f"<desc>{escape(result.disclaimer)} {escape(result.heuristic_notice)} "
            "Dashed lines are baseline boundaries; solid lines are selected boundaries.</desc>"
        ),
        "<style>text{font-family:Arial,sans-serif;fill:#182230}.small{font-size:11px}.label{font-size:12px;font-weight:700}.panel{font-size:13px}</style>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="40" y="38" font-size="21" font-weight="700">M6.2 Layout Optimization Overlay</text>',
        (
            f'<text x="40" y="64" font-size="13">Baseline '
            f"{result.baseline_candidate.quality_assessment.overall_score:.2f} → selected "
            f"{assessment.overall_score:.2f} | {escape(assessment.score_status.value)} | "
            f"{escape(result.selected_candidate_id)}</text>"
        ),
        '<text x="40" y="84" font-size="11" fill="#b42318">Internal deterministic heuristic — not architectural, cultural, code, permit, or professional approval.</text>',
        '<g id="baseline-boundaries" fill="none" stroke="#8b95a1" stroke-width="1.4" stroke-dasharray="7 5">',
    ]
    for wall in sorted(baseline.walls, key=lambda item: item.id):
        lines.append(_line(wall, x, y))
    lines.extend(["</g>", '<g id="selected-rooms">'])
    for room in sorted(selected.rooms, key=lambda item: item.id):
        fill = "#fff2cc" if room.id in affected_rooms else "#eef2f6"
        lines.extend(
            [
                (
                    f'<rect x="{x(room.rect.min_x):.2f}" y="{y(room.rect.max_y):.2f}" '
                    f'width="{room.rect.width * scale:.2f}" height="{room.rect.height * scale:.2f}" '
                    f'fill="{fill}" fill-opacity="0.70" stroke="none"/>'
                ),
                (
                    f'<text x="{x((room.rect.min_x + room.rect.max_x) / 2):.2f}" '
                    f'y="{y((room.rect.min_y + room.rect.max_y) / 2):.2f}" '
                    f'text-anchor="middle" class="label">{escape(room.id)}</text>'
                ),
            ]
        )
    lines.extend(["</g>", '<g id="selected-boundaries" stroke="#20262e" fill="none">'])
    baseline_segments = {
        (wall.start, wall.end, tuple(sorted(wall.room_ids))) for wall in baseline.walls
    }
    for wall in sorted(selected.walls, key=lambda item: item.id):
        moved = (wall.start, wall.end, tuple(sorted(wall.room_ids))) not in baseline_segments
        color = "#b42318" if moved else "#20262e"
        width = 3.2 if moved else (2.2 if wall.is_external else 1.2)
        lines.append(_line(wall, x, y, color=color, width=width))
    lines.extend(["</g>", '<g id="selected-openings">'])
    walls = {wall.id: wall for wall in selected.walls}
    for door in sorted(selected.doors, key=lambda item: item.id):
        wall = walls[door.wall_id]
        cx, cy = _opening_center(wall, door.position_m, door.width_m)
        color = "#b42318" if door.id in changed_openings else "#1769aa"
        lines.append(
            f'<circle cx="{x(cx):.2f}" cy="{y(cy):.2f}" r="5" fill="{color}"><title>{escape(door.id)}</title></circle>'
        )
    lines.append("</g>")

    resolved = [item.rule_id for item in result.finding_comparison if item.change == "improved"]
    remaining_major = [
        finding.rule_id
        for finding in assessment.findings
        if finding.severity is FindingSeverity.MAJOR
        and finding.status in {FindingStatus.WARNING, FindingStatus.FAIL}
    ]
    lines.extend(
        [
            f'<text x="{panel_x:.2f}" y="116" font-size="17" font-weight="700">Selected transformations</text>',
        ]
    )
    for index, transformation_id in enumerate(result.selected_candidate.transformation_ids):
        lines.append(
            f'<text x="{panel_x:.2f}" y="{146 + index * 22}" class="panel">{index + 1}. {escape(transformation_id)}</text>'
        )
    section_y = 175 + len(result.selected_candidate.transformation_ids) * 22
    lines.extend(
        [
            f'<text x="{panel_x:.2f}" y="{section_y}" font-size="17" font-weight="700">Finding comparison</text>',
            f'<text x="{panel_x:.2f}" y="{section_y + 28}" class="panel">Improved: {escape(", ".join(resolved) or "none")}</text>',
            f'<text x="{panel_x:.2f}" y="{section_y + 52}" class="panel">Remaining major: {escape(", ".join(remaining_major) or "none")}</text>',
            f'<text x="{panel_x:.2f}" y="{section_y + 88}" font-size="17" font-weight="700">Legend</text>',
            f'<text x="{panel_x:.2f}" y="{section_y + 114}" class="panel">dashed gray: baseline boundaries</text>',
            f'<text x="{panel_x:.2f}" y="{section_y + 136}" class="panel">red: moved/added selected boundaries or openings</text>',
            f'<text x="{panel_x:.2f}" y="{section_y + 158}" class="panel">yellow: rooms affected by selected audit</text>',
        ]
    )
    footer_y = view_height - 48
    lines.extend(
        [
            f'<line x1="40" y1="{footer_y - 24:.2f}" x2="{view_width - 40:.2f}" y2="{footer_y - 24:.2f}" stroke="#98a2b3"/>',
            f'<text x="40" y="{footer_y:.2f}" font-size="10" fill="#b42318">{escape(result.disclaimer)}</text>',
            f'<text x="40" y="{footer_y + 18:.2f}" font-size="10">{escape(result.heuristic_notice)}</text>',
            "</svg>",
            "",
        ]
    )
    return "\n".join(lines)


def write_optimization_overlay_svg(path: str | Path, result: LayoutOptimizationResult) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_optimization_overlay_svg(result), encoding="utf-8", newline="\n")
    return path


def _line(wall, x, y, color: str | None = None, width: float | None = None) -> str:
    attrs = ""
    if color:
        attrs += f' stroke="{color}"'
    if width:
        attrs += f' stroke-width="{width}"'
    return (
        f'<line x1="{x(wall.start[0]):.2f}" y1="{y(wall.start[1]):.2f}" '
        f'x2="{x(wall.end[0]):.2f}" y2="{y(wall.end[1]):.2f}"{attrs}/>'
    )


def _opening_center(wall, position: float, width: float) -> tuple[float, float]:
    offset = position + width / 2.0
    if abs(wall.start[0] - wall.end[0]) < 1e-9:
        return wall.start[0], wall.start[1] + offset
    return wall.start[0] + offset, wall.start[1]


__all__ = ["render_optimization_overlay_svg", "write_optimization_overlay_svg"]
