"""Deterministic engineering SVG overlay for M6.1 findings."""

from __future__ import annotations

from html import escape
from pathlib import Path

from saudi_plot_design.model import Concept
from saudi_plot_design.quality.models import (
    ArchitecturalQualityAssessment,
    FindingStatus,
    QualityCategory,
)

_ZONE_COLORS = {
    "public": "#f7d9a6",
    "family": "#cce7c5",
    "private": "#cadcf4",
    "wet_service": "#d9d0eb",
    "circulation": "#e3e3e3",
}
_STATUS_STROKES = {
    FindingStatus.PASS: "#53606b",
    FindingStatus.WARNING: "#c77900",
    FindingStatus.FAIL: "#b42318",
    FindingStatus.NOT_EVALUABLE: "#667085",
}


def render_quality_overlay_svg(concept: Concept, assessment: ArchitecturalQualityAssessment) -> str:
    """Render room/zone evidence and the most material plan findings."""

    room_results = {room.room_id: room for room in assessment.room_assessments}
    if concept.footprint:
        min_x, min_y = concept.footprint.min_x, concept.footprint.min_y
        width_m, height_m = concept.footprint.width, concept.footprint.height
    elif concept.rooms:
        min_x = min(room.rect.min_x for room in concept.rooms)
        min_y = min(room.rect.min_y for room in concept.rooms)
        width_m = max(room.rect.max_x for room in concept.rooms) - min_x
        height_m = max(room.rect.max_y for room in concept.rooms) - min_y
    else:
        min_x = min_y = 0.0
        width_m = height_m = 1.0
    plan_width = 720.0
    plan_height = 760.0
    scale = min(plan_width / max(width_m, 1.0), plan_height / max(height_m, 1.0))
    ox, oy = 55.0, 105.0
    panel_x = ox + width_m * scale + 45.0
    view_width = max(1280.0, panel_x + 500.0)
    view_height = max(980.0, oy + height_m * scale + 115.0)

    def x(value: float) -> float:
        return ox + (value - min_x) * scale

    def y(value: float) -> float:
        return oy + (height_m - (value - min_y)) * scale

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{view_width:.0f}" '
            f'height="{view_height:.0f}" viewBox="0 0 {view_width:.0f} {view_height:.0f}">'
        ),
        f"<title>Architectural quality engineering overlay — {escape(concept.concept_id)}</title>",
        f"<desc>{escape(assessment.disclaimer)} This diagnostic is not architectural approval.</desc>",
        "<style>",
        "text{font-family:Arial,sans-serif;fill:#182230} .small{font-size:11px} .tiny{font-size:9px} .label{font-size:12px;font-weight:700} .panel{font-size:13px}",
        "</style>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="40" y="38" font-size="21" font-weight="700">Architectural Quality Overlay — Engineering Review</text>',
        (
            f'<text x="40" y="64" font-size="13">Overall: {escape(str(assessment.overall_score) if assessment.overall_score is not None else "not rated")} '
            f"| {escape(assessment.score_status.value)} | evidence {assessment.evidence_coverage:.1%} "
            f"| constraints {len(assessment.status_constraints)}</text>"
        ),
        '<text x="40" y="84" font-size="11" fill="#b42318">Heuristic diagnostic only — not code, cultural, permit, or professional approval.</text>',
        '<g id="rooms">',
    ]
    for room in sorted(concept.rooms, key=lambda item: item.id):
        result = room_results.get(room.id)
        status = result.status if result else FindingStatus.NOT_EVALUABLE
        rect_x = x(room.rect.min_x)
        rect_y = y(room.rect.max_y)
        rect_w = room.rect.width * scale
        rect_h = room.rect.height * scale
        fill = _ZONE_COLORS.get(room.zone.value, "#eeeeee")
        stroke = _STATUS_STROKES[status]
        stroke_width = 3 if status in {FindingStatus.WARNING, FindingStatus.FAIL} else 1.2
        cx, cy = rect_x + rect_w / 2, rect_y + rect_h / 2
        lines.extend(
            [
                (
                    f'<rect id="room-{escape(room.id)}" x="{rect_x:.2f}" y="{rect_y:.2f}" '
                    f'width="{rect_w:.2f}" height="{rect_h:.2f}" fill="{fill}" '
                    f'stroke="{stroke}" stroke-width="{stroke_width}"/>'
                ),
                f'<text x="{cx:.2f}" y="{cy - 10:.2f}" text-anchor="middle" class="label">{escape(room.name)}</text>',
                f'<text x="{cx:.2f}" y="{cy + 7:.2f}" text-anchor="middle" class="small">{escape(room.id)}</text>',
                f'<text x="{cx:.2f}" y="{cy + 23:.2f}" text-anchor="middle" class="tiny">zone: {escape(room.zone.value)}</text>',
            ]
        )
        if result and result.external_wall_contact:
            lines.append(
                f'<circle cx="{rect_x + 8:.2f}" cy="{rect_y + 8:.2f}" r="4" fill="#137333"><title>external-wall contact</title></circle>'
            )
        if result and result.external_opening:
            lines.append(
                f'<circle cx="{rect_x + 20:.2f}" cy="{rect_y + 8:.2f}" r="4" fill="#1769aa"><title>external opening</title></circle>'
            )
    lines.append("</g>")

    for wall in sorted(concept.walls, key=lambda item: item.id):
        lines.append(
            f'<line x1="{x(wall.start[0]):.2f}" y1="{y(wall.start[1]):.2f}" '
            f'x2="{x(wall.end[0]):.2f}" y2="{y(wall.end[1]):.2f}" '
            f'stroke="#20262e" stroke-width="{2.2 if wall.is_external else 1.0}"/>'
        )

    lines.extend(
        [
            f'<text x="{panel_x:.2f}" y="112" font-size="17" font-weight="700">Legend</text>',
            f'<text x="{panel_x:.2f}" y="136" class="panel">red outline: failed room evidence</text>',
            f'<text x="{panel_x:.2f}" y="157" class="panel">amber outline: warning room evidence</text>',
            f'<text x="{panel_x:.2f}" y="178" class="panel">green dot: external-wall contact</text>',
            f'<text x="{panel_x:.2f}" y="199" class="panel">blue dot: external opening</text>',
            f'<text x="{panel_x:.2f}" y="235" font-size="17" font-weight="700">Major plan diagnostics</text>',
        ]
    )
    material = [
        finding
        for finding in assessment.findings
        if finding.status in {FindingStatus.FAIL, FindingStatus.WARNING}
        and (
            finding.affected_object_ids
            or finding.category
            in {
                QualityCategory.ADJACENCY_QUALITY,
                QualityCategory.PRIVACY_ZONING,
                QualityCategory.CIRCULATION,
            }
        )
    ]
    for index, finding in enumerate(material[:14]):
        fy = 265 + index * 39
        affected = ", ".join(finding.affected_object_ids[:5]) or "plan-wide"
        if len(finding.affected_object_ids) > 5:
            affected += ", …"
        color = _STATUS_STROKES[finding.status]
        lines.append(
            f'<text x="{panel_x:.2f}" y="{fy}" class="panel" font-weight="700" fill="{color}">{escape(finding.rule_id)} — {escape(finding.title)}</text>'
        )
        lines.append(
            f'<text x="{panel_x + 14:.2f}" y="{fy + 17}" class="small">{escape(finding.status.value)}: {escape(affected)}</text>'
        )

    footer_y = view_height - 48
    lines.extend(
        [
            f'<line x1="40" y1="{footer_y - 24:.2f}" x2="{view_width - 40:.2f}" y2="{footer_y - 24:.2f}" stroke="#98a2b3"/>',
            f'<text x="40" y="{footer_y:.2f}" font-size="10" fill="#b42318">{escape(assessment.disclaimer)}</text>',
            f'<text x="40" y="{footer_y + 18:.2f}" font-size="10">Profile {escape(assessment.criteria_profile.profile_id)} v{escape(assessment.criteria_profile.profile_version)} — deterministic M6.1 review overlay.</text>',
            "</svg>",
            "",
        ]
    )
    return "\n".join(lines)


def write_quality_overlay_svg(
    path: str | Path,
    concept: Concept,
    assessment: ArchitecturalQualityAssessment,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_quality_overlay_svg(concept, assessment), encoding="utf-8", newline="\n")
    return path
