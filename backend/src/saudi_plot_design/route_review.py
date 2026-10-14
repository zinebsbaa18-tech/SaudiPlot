"""Deterministic M6.2.1 entrance and route-semantics review artifacts."""

from __future__ import annotations

import csv
import io
import json
from html import escape
from pathlib import Path
from textwrap import wrap

from saudi_plot_design.layout.models import LayoutCandidate, LayoutOptimizationResult
from saudi_plot_design.model import Concept
from saudi_plot_design.output import DISCLAIMER
from saudi_plot_design.quality.models import FindingSeverity, FindingStatus
from saudi_plot_design.route_semantics import (
    EXTERNAL_PATH_NODE,
    ConceptRouteAudit,
    RouteEvidence,
    concept_route_audit,
)

PREVIOUS_SELECTED_CANDIDATE_ID = "candidate-031"
HEURISTIC_NOTICE = (
    "Deterministic concept-route diagnostic only; not architectural, cultural, "
    "regulatory, permit, or professional approval."
)


def _review_candidates(
    result: LayoutOptimizationResult,
) -> tuple[tuple[str, LayoutCandidate], ...]:
    previous = next(
        candidate
        for candidate in result.candidates
        if candidate.candidate_id == PREVIOUS_SELECTED_CANDIDATE_ID
    )
    candidates = (
        ("baseline", result.baseline_candidate),
        ("previous_selected", previous),
        ("new_selected", result.selected_candidate),
    )
    seen: set[str] = set()
    return tuple(
        (label, candidate)
        for label, candidate in candidates
        if not (candidate.candidate_id in seen or seen.add(candidate.candidate_id))
    )


def render_entrance_inventory_csv(result: LayoutOptimizationResult) -> str:
    columns = (
        "candidate_scope",
        "candidate_id",
        "door_id",
        "internal_room_id",
        "host_external_wall_id",
        "entrance_type",
        "classification_method",
        "confidence",
        "requires_review",
        "evidence",
        "disclaimer",
        "heuristic_notice",
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for scope, candidate in _review_candidates(result):
        assert candidate.concept is not None
        for item in concept_route_audit(candidate.concept).entrance_inventory:
            writer.writerow(
                {
                    "candidate_scope": scope,
                    "candidate_id": candidate.candidate_id,
                    "door_id": item.door_id,
                    "internal_room_id": item.internal_room_id or "",
                    "host_external_wall_id": item.host_wall_id,
                    "entrance_type": item.entrance_type.value,
                    "classification_method": item.classification_method.value,
                    "confidence": f"{item.confidence:.2f}",
                    "requires_review": str(item.requires_review).lower(),
                    "evidence": " | ".join(item.evidence),
                    "disclaimer": DISCLAIMER,
                    "heuristic_notice": HEURISTIC_NOTICE,
                }
            )
    return stream.getvalue()


def _route_rows(audit: ConceptRouteAudit) -> tuple[tuple[str, RouteEvidence], ...]:
    return (
        ("family", audit.family_route),
        ("guest", audit.guest_route),
        ("service", audit.service_route.preferred_route),
        ("guest_wc", audit.guest_wc_route.preferred_route),
    )


def render_route_semantics_comparison_csv(result: LayoutOptimizationResult) -> str:
    columns = (
        "candidate_scope",
        "candidate_id",
        "route_type",
        "path_kind",
        "available",
        "allowed",
        "requires_review",
        "route_sequence",
        "door_ids",
        "exit_door_id",
        "reentry_door_id",
        "internal_door_steps",
        "external_door_steps",
        "external_traversal_steps",
        "total_cost",
        "external_path_classification",
        "reasons",
        "disclaimer",
        "heuristic_notice",
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for scope, candidate in _review_candidates(result):
        assert candidate.concept is not None
        for route_type, route in _route_rows(concept_route_audit(candidate.concept)):
            writer.writerow(
                {
                    "candidate_scope": scope,
                    "candidate_id": candidate.candidate_id,
                    "route_type": route_type,
                    "path_kind": route.path_kind,
                    "available": str(route.available).lower(),
                    "allowed": str(route.allowed).lower(),
                    "requires_review": str(route.requires_review).lower(),
                    "route_sequence": " -> ".join(route.display_sequence),
                    "door_ids": "|".join(route.door_ids),
                    "exit_door_id": route.exit_door_id or "",
                    "reentry_door_id": route.reentry_door_id or "",
                    "internal_door_steps": route.internal_door_steps,
                    "external_door_steps": route.external_door_steps,
                    "external_traversal_steps": route.external_traversal_steps,
                    "total_cost": "" if route.total_cost is None else route.total_cost,
                    "external_path_classification": route.external_path_classification or "",
                    "reasons": " | ".join(route.reasons),
                    "disclaimer": DISCLAIMER,
                    "heuristic_notice": HEURISTIC_NOTICE,
                }
            )
    return stream.getvalue()


def render_candidate_ranking_comparison_csv(result: LayoutOptimizationResult) -> str:
    columns = (
        "candidate_id",
        "transformations",
        "geometrically_valid",
        "eligible_for_selection",
        "previous_selected",
        "new_selected",
        "effective_score",
        "quality_status",
        "total_external_route_penalty",
        "disallowed_external_routes",
        "external_guest_wc_detours",
        "unknown_entrances_used_as_dedicated",
        "unnecessary_exit_reentry_routes",
        "external_route_extra_cost",
        "selection_rank",
        "rejection_reason",
        "disclaimer",
        "heuristic_notice",
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for candidate in result.candidates:
        assessment = candidate.quality_assessment
        penalties = candidate.route_penalties
        geometrically_valid = bool(
            candidate.concept
            and candidate.concept.is_valid
            and candidate.validation
            and candidate.validation.passed
        )
        writer.writerow(
            {
                "candidate_id": candidate.candidate_id,
                "transformations": "|".join(candidate.transformation_ids),
                "geometrically_valid": str(geometrically_valid).lower(),
                "eligible_for_selection": str(candidate.eligible_for_selection).lower(),
                "previous_selected": str(
                    candidate.candidate_id == PREVIOUS_SELECTED_CANDIDATE_ID
                ).lower(),
                "new_selected": str(candidate.candidate_id == result.selected_candidate_id).lower(),
                "effective_score": (
                    ""
                    if assessment is None or assessment.overall_score is None
                    else f"{assessment.overall_score:.2f}"
                ),
                "quality_status": assessment.score_status.value if assessment else "",
                "total_external_route_penalty": penalties.total_penalty if penalties else "",
                "disallowed_external_routes": (
                    penalties.disallowed_external_routes if penalties else ""
                ),
                "external_guest_wc_detours": (
                    penalties.external_guest_wc_detours if penalties else ""
                ),
                "unknown_entrances_used_as_dedicated": (
                    penalties.unknown_entrances_used_as_dedicated if penalties else ""
                ),
                "unnecessary_exit_reentry_routes": (
                    penalties.unnecessary_exit_reentry_routes if penalties else ""
                ),
                "external_route_extra_cost": (
                    penalties.external_route_extra_cost if penalties else ""
                ),
                "selection_rank": (
                    json.dumps(candidate.selection_rank, separators=(",", ":"))
                    if candidate.selection_rank
                    else ""
                ),
                "rejection_reason": candidate.rejection.explanation if candidate.rejection else "",
                "disclaimer": DISCLAIMER,
                "heuristic_notice": HEURISTIC_NOTICE,
            }
        )
    return stream.getvalue()


def external_route_audit_payload(result: LayoutOptimizationResult) -> dict:
    return {
        "schema_version": 1,
        "disclaimer": DISCLAIMER,
        "heuristic_notice": HEURISTIC_NOTICE,
        "previous_selected_candidate_id": PREVIOUS_SELECTED_CANDIDATE_ID,
        "new_selected_candidate_id": result.selected_candidate_id,
        "ranking_rules": list(result.ranking_rules),
        "candidates": {
            scope: {
                "candidate_id": candidate.candidate_id,
                "transformations": list(candidate.transformation_ids),
                "eligible_for_selection": candidate.eligible_for_selection,
                "rejection": (
                    candidate.rejection.model_dump(mode="json") if candidate.rejection else None
                ),
                "route_audit": concept_route_audit(candidate.concept).model_dump(mode="json"),
            }
            for scope, candidate in _review_candidates(result)
            if candidate.concept is not None
        },
    }


def render_external_route_audit_json(result: LayoutOptimizationResult) -> str:
    return json.dumps(external_route_audit_payload(result), indent=2, ensure_ascii=False) + "\n"


def _unresolved_major(candidate: LayoutCandidate) -> tuple[str, ...]:
    assert candidate.quality_assessment is not None
    return tuple(
        finding.rule_id
        for finding in candidate.quality_assessment.findings
        if finding.severity is FindingSeverity.MAJOR
        and finding.status in {FindingStatus.WARNING, FindingStatus.FAIL}
    )


def render_review_summary_markdown(result: LayoutOptimizationResult) -> str:
    previous = next(
        candidate
        for candidate in result.candidates
        if candidate.candidate_id == PREVIOUS_SELECTED_CANDIDATE_ID
    )
    selected = result.selected_candidate
    assert previous.concept is not None and previous.quality_assessment is not None
    assert selected.concept is not None and selected.quality_assessment is not None
    previous_audit = concept_route_audit(previous.concept)
    selected_audit = concept_route_audit(selected.concept)
    return "\n".join(
        (
            "# M6.2.1 Entrance and Route Semantics Review",
            "",
            f"> {DISCLAIMER}",
            "",
            f"> {HEURISTIC_NOTICE}",
            "",
            "The former shared `exterior` graph node connected every external door at zero cost. M6.2.1 retains exterior as a canonical door endpoint but routes only through named real doors and an explicit, non-zero-cost external path when policy permits it.",
            "",
            "## Selection comparison",
            "",
            f"- Previous: `{previous.candidate_id}`; score {previous.quality_assessment.overall_score:.2f}; status `{previous.quality_assessment.score_status.value}`; route penalty {previous_audit.penalties.total_penalty}; eligible `{previous.eligible_for_selection}`.",
            f"- New: `{selected.candidate_id}`; score {selected.quality_assessment.overall_score:.2f}; status `{selected.quality_assessment.score_status.value}`; route penalty {selected_audit.penalties.total_penalty}; eligible `{selected.eligible_for_selection}`.",
            f"- New transformations: {', '.join(selected.transformation_ids) or 'none'}.",
            f"- Remaining major findings: {', '.join(_unresolved_major(selected)) or 'none'}.",
            "",
            "## Route evidence",
            "",
            *(
                f"- New {name}: {' -> '.join(route.display_sequence) or 'unavailable'}; internal doors {route.internal_door_steps}; external doors {route.external_door_steps}; external traversal {route.external_traversal_steps}; allowed `{route.allowed}`."
                for name, route in _route_rows(selected_audit)
            ),
            f"- Previous guest-WC: {' -> '.join(previous_audit.guest_wc_route.preferred_route.display_sequence)}; penalty {previous_audit.penalties.total_penalty}; allowed `{previous_audit.guest_wc_route.preferred_route.allowed}`.",
            "",
            "T04 creates two classified exterior service doors and only a reviewable service-path alternative; it does not create internal kitchen-to-maid access. T05 removes the majlis-to-entry door only when distinct real family and guest doors exist, but this removal does not establish a valid internal guest-WC route.",
            "",
        )
    )


def render_entrance_route_overlay_svg(result: LayoutOptimizationResult) -> str:
    previous = next(
        candidate
        for candidate in result.candidates
        if candidate.candidate_id == PREVIOUS_SELECTED_CANDIDATE_ID
    )
    concept = previous.concept
    assert concept is not None and concept.footprint is not None
    audit = concept_route_audit(concept)
    fp = concept.footprint
    scale = min(700.0 / fp.width, 760.0 / fp.height)
    ox, oy = 55.0, 115.0
    panel_x = ox + fp.width * scale + 50.0
    width = max(1420.0, panel_x + 620.0)
    height = max(1040.0, oy + fp.height * scale + 130.0)
    walls = {wall.id: wall for wall in concept.walls}

    def x(value: float) -> float:
        return ox + (value - fp.min_x) * scale

    def y(value: float) -> float:
        return oy + (fp.max_y - value) * scale

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">',
        "<title>M6.2.1 entrance and route semantics overlay</title>",
        f"<desc>{escape(DISCLAIMER)} {escape(HEURISTIC_NOTICE)}</desc>",
        "<style>text{font-family:Arial,sans-serif;fill:#182230}.room{font-size:11px}.panel{font-size:12px}.route{fill:none;stroke-width:4;stroke-linecap:round;stroke-linejoin:round}</style>",
        '<rect width="100%" height="100%" fill="#fff"/>',
        '<text x="40" y="36" font-size="21" font-weight="700">M6.2.1 Entrance and Route Semantics</text>',
        f'<text x="40" y="62" font-size="13">Prior candidate evidence: {escape(previous.candidate_id)} | new selection: {escape(result.selected_candidate_id)}</text>',
        '<text x="40" y="84" font-size="11" fill="#b42318">Explicit real doors; external traversal is non-zero-cost and policy controlled.</text>',
    ]
    for room in sorted(concept.rooms, key=lambda item: item.id):
        lines.append(
            f'<rect x="{x(room.rect.min_x):.2f}" y="{y(room.rect.max_y):.2f}" width="{room.rect.width * scale:.2f}" height="{room.rect.height * scale:.2f}" fill="#f2f4f7" stroke="#667085"/>'
        )
        lines.append(
            f'<text x="{x((room.rect.min_x + room.rect.max_x) / 2):.2f}" y="{y((room.rect.min_y + room.rect.max_y) / 2):.2f}" text-anchor="middle" class="room">{escape(room.id)}</text>'
        )
    colors = {
        "family": "#1769aa",
        "guest": "#7a3db8",
        "service": "#138a57",
        "service_external_review": "#138a57",
        "guest_wc": "#c43d2f",
    }
    for name, route in _route_rows(audit):
        points = _route_points(concept, route, x, y)
        if points:
            dash = ' stroke-dasharray="8 5"' if route.uses_external_path else ""
            point_text = " ".join(f"{px:.2f},{py:.2f}" for px, py in points)
            lines.append(
                f'<polyline id="route-{name}" class="route" points="{point_text}" '
                f'stroke="{colors[name]}"{dash}/>'
            )
    service_external = next(
        (route for route in audit.service_route.external_routes if route.allowed), None
    )
    if service_external is not None:
        points = _route_points(concept, service_external, x, y)
        point_text = " ".join(f"{px:.2f},{py:.2f}" for px, py in points)
        lines.append(
            f'<polyline id="route-service-external-review" class="route" '
            f'points="{point_text}" stroke="{colors["service_external_review"]}" '
            'stroke-width="2" stroke-dasharray="3 5" opacity="0.75"/>'
        )
    for item in audit.entrance_inventory:
        door = next(door for door in concept.doors if door.id == item.door_id)
        cx, cy = _opening_center(walls[door.wall_id], door.position_m, door.width_m)
        color = (
            "#b42318"
            if item.requires_review
            else colors.get(
                {"family_main": "family", "guest_majlis": "guest", "service": "service"}.get(
                    item.entrance_type.value, ""
                ),
                "#667085",
            )
        )
        review_label = " [REVIEW]" if item.requires_review else ""
        if item.entrance_type.value == "guest_majlis":
            label_x, label_y, anchor = x(cx) - 12, y(cy) - 14, "end"
        elif item.entrance_type.value == "family_main":
            label_x, label_y, anchor = x(cx) + 12, y(cy) - 30, "start"
        elif item.entrance_type.value == "service":
            label_x, label_y, anchor = x(cx) - 10, y(cy) - 9, "end"
        else:
            label_x, label_y, anchor = x(cx) + 10, y(cy) - 9, "start"
        lines.extend(
            (
                f'<circle cx="{x(cx):.2f}" cy="{y(cy):.2f}" r="7" fill="{color}"><title>{escape(item.door_id)}</title></circle>',
                f'<text x="{label_x:.2f}" y="{label_y:.2f}" text-anchor="{anchor}" '
                f'font-size="11" fill="{color}">{escape(item.door_id)}: '
                f"{escape(item.entrance_type.value)}{review_label}</text>",
            )
        )
    lines.append(
        f'<text x="{panel_x:.2f}" y="120" font-size="17" font-weight="700">Prior route audit</text>'
    )
    unsupported = tuple(item.door_id for item in audit.entrance_inventory if item.requires_review)
    lines.append(
        f'<text x="{panel_x:.2f}" y="143" class="panel" fill="#b42318">'
        f"Unsupported/unknown entrances: {escape(', '.join(unsupported) or 'none')}</text>"
    )
    panel_y = 171
    panel_routes = [*_route_rows(audit)]
    if service_external is not None:
        panel_routes.insert(3, ("service_external_review", service_external))
    for name, route in panel_routes:
        sequence = " -> ".join(route.display_sequence) or "unavailable"
        lines.append(
            f'<text x="{panel_x:.2f}" y="{panel_y}" class="panel" font-weight="700" '
            f'fill="{colors[name]}">{escape(name)} | cost '
            f"{route.total_cost if route.total_cost is not None else 'n/a'} | "
            f"allowed={str(route.allowed).lower()}</text>"
        )
        sequence_lines = wrap(sequence, width=76, break_long_words=False)
        for index, sequence_line in enumerate(sequence_lines):
            lines.append(
                f'<text x="{panel_x:.2f}" y="{panel_y + 19 + index * 17}" '
                f'class="panel">{escape(sequence_line)}</text>'
            )
        detail_y = panel_y + 22 + len(sequence_lines) * 17
        if route.exit_door_id or route.reentry_door_id:
            lines.append(
                f'<text x="{panel_x:.2f}" y="{detail_y}" class="panel" '
                f'fill="#b42318">exit={escape(route.exit_door_id or "none")} | '
                f"re-entry={escape(route.reentry_door_id or 'none')}</text>"
            )
            detail_y += 18
        panel_y = detail_y + 28
    remaining = _unresolved_major(result.selected_candidate)
    lines.extend(
        (
            f'<text x="{panel_x:.2f}" y="{panel_y + 18}" font-size="17" font-weight="700">New selection</text>',
            f'<text x="{panel_x:.2f}" y="{panel_y + 45}" class="panel">{escape(result.selected_candidate_id)} | external penalty {result.selected_candidate.route_penalties.total_penalty if result.selected_candidate.route_penalties else "n/a"}</text>',
            f'<text x="{panel_x:.2f}" y="{panel_y + 68}" class="panel">Remaining major: {escape(", ".join(remaining) or "none")}</text>',
            f'<text x="40" y="{height - 48:.2f}" font-size="10" fill="#b42318">{escape(DISCLAIMER)}</text>',
            f'<text x="40" y="{height - 28:.2f}" font-size="10">{escape(HEURISTIC_NOTICE)}</text>',
            "</svg>",
            "",
        )
    )
    return "\n".join(lines)


def _route_points(concept: Concept, route: RouteEvidence, x, y) -> list[tuple[float, float]]:
    rooms = {room.id: room for room in concept.rooms}
    walls = {wall.id: wall for wall in concept.walls}
    doors = {door.id: door for door in concept.doors}

    def room_center(room_id: str) -> tuple[float, float]:
        room = rooms[room_id]
        return x((room.rect.min_x + room.rect.max_x) / 2), y(
            (room.rect.min_y + room.rect.max_y) / 2
        )

    if not route.available:
        return []
    if not route.uses_external_path:
        points = [room_center(room_id) for room_id in route.room_sequence if room_id in rooms]
        if route.path_kind == "entrance" and route.door_ids:
            door = doors[route.door_ids[0]]
            cx, cy = _opening_center(walls[door.wall_id], door.position_m, door.width_m)
            points.insert(0, (x(cx), y(cy)))
        return points
    exit_door = doors[route.exit_door_id]
    reentry_door = doors[route.reentry_door_id]
    ex, ey = _opening_center(walls[exit_door.wall_id], exit_door.position_m, exit_door.width_m)
    rx, ry = _opening_center(
        walls[reentry_door.wall_id], reentry_door.position_m, reentry_door.width_m
    )
    start = room_center(route.start_room_id)
    target_rooms = [
        room_id
        for room_id in route.room_sequence
        if room_id not in {route.start_room_id, EXTERNAL_PATH_NODE} and room_id in rooms
    ]
    return [
        start,
        (x(ex), y(ey)),
        (x(ex), y(ey) + 24),
        (x(rx), y(ry) + 24),
        (x(rx), y(ry)),
        *(room_center(room_id) for room_id in target_rooms),
    ]


def _opening_center(wall, position: float, width: float) -> tuple[float, float]:
    offset = position + width / 2.0
    if abs(wall.start[0] - wall.end[0]) < 1e-9:
        return wall.start[0], wall.start[1] + offset
    return wall.start[0] + offset, wall.start[1]


def write_route_review_package(path: str | Path, result: LayoutOptimizationResult) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "entrance_inventory.csv": render_entrance_inventory_csv(result),
        "route_semantics_comparison.csv": render_route_semantics_comparison_csv(result),
        "candidate_ranking_comparison.csv": render_candidate_ranking_comparison_csv(result),
        "entrance_route_overlay.svg": render_entrance_route_overlay_svg(result),
        "external_route_audit.json": render_external_route_audit_json(result),
        "review_summary.md": render_review_summary_markdown(result),
    }
    for filename, content in artifacts.items():
        (path / filename).write_text(content, encoding="utf-8", newline="\n")
    return path


__all__ = [
    "external_route_audit_payload",
    "render_candidate_ranking_comparison_csv",
    "render_entrance_inventory_csv",
    "render_entrance_route_overlay_svg",
    "render_external_route_audit_json",
    "render_review_summary_markdown",
    "render_route_semantics_comparison_csv",
    "write_route_review_package",
]
