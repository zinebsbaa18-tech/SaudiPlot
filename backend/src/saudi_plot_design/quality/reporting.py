"""Deterministic JSON and Markdown reporting for M6.1 assessments."""

from __future__ import annotations

from pathlib import Path

from saudi_plot_design.export.runlog import write_json
from saudi_plot_design.quality.models import (
    ArchitecturalQualityAssessment,
    CRITICAL_QUALITY_CATEGORIES,
    FindingSeverity,
    FindingStatus,
    QualityCategory,
)


def write_quality_report(path: str | Path, assessment: ArchitecturalQualityAssessment) -> Path:
    """Write the complete typed assessment as stable UTF-8 JSON."""

    return write_json(Path(path), assessment.model_dump(mode="json"))


def _score(value: float | None) -> str:
    return "not rated" if value is None else f"{value:.2f}/100"


def _finding_line(finding) -> str:
    affected = ", ".join(finding.affected_object_ids) or "plan-wide"
    return (
        f"- **{finding.rule_id} — {finding.title}** "
        f"({finding.status.value}, {finding.severity.value}; {affected}): "
        f"{finding.explanation} Recommendation: {finding.recommendation}"
    )


def render_quality_summary_markdown(
    assessment: ArchitecturalQualityAssessment,
) -> str:
    """Render a deterministic engineering-review summary."""

    lines = [
        "# Architectural Quality Summary",
        "",
        f"> {assessment.disclaimer}",
        "",
        (
            "This is a deterministic concept-design diagnostic based on synthetic demo "
            "heuristics. It is not architectural, cultural, regulatory, permit, or "
            "professional approval."
        ),
        "",
        "## Overall indicator",
        "",
        f"- Raw weighted score: **{_score(assessment.raw_weighted_score)}**",
        (
            "- Coverage-adjusted score (raw score × evidence coverage): "
            f"**{_score(assessment.coverage_adjusted_score)}**"
        ),
        f"- Overall score used for status: **{_score(assessment.overall_score)}**",
        f"- Status: **{assessment.score_status.value}**",
        f"- Evidence coverage: **{assessment.evidence_coverage:.2%}**",
        (
            f"- Checks: {assessment.passed_checks} pass, {assessment.warning_checks} warning, "
            f"{assessment.failed_checks} fail, {assessment.not_evaluable_checks} not evaluable"
        ),
        "",
        "## Status constraints",
        "",
    ]
    if assessment.status_constraints:
        for constraint in assessment.status_constraints:
            lines.append(
                f"- **{constraint.constraint_id}** (maximum "
                f"`{constraint.maximum_status.value}`): {constraint.explanation}"
            )
    else:
        lines.append("- No status constraint was triggered by the available evidence.")

    lines.extend(
        [
            "",
            "## Critical-category floors",
            "",
            (
                "These are versioned internal demo heuristics, not official or "
                "regulatory thresholds."
            ),
            "",
            "| Critical category | Evaluated score | Coverage | Strong min | Workable min | Substantial min | Result |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    failures = {failure.category: failure for failure in assessment.category_floor_failures}
    for category in CRITICAL_QUALITY_CATEGORIES:
        result = assessment.category_scores[category]
        floor = assessment.criteria_profile.scoring.critical_category_floors[category]
        failure = failures.get(category)
        outcome = (
            "meets strong floor" if failure is None else f"maximum {failure.maximum_status.value}"
        )
        lines.append(
            f"| {category.value.replace('_', ' ').title()} | {_score(result.evaluated_score)} | "
            f"{result.coverage:.2%} | {floor.strong_min_score:.2f} | "
            f"{floor.workable_min_score:.2f} | {floor.substantial_revision_min_score:.2f} | "
            f"{outcome} |"
        )

    lines.extend(
        [
            "",
            "## Category scores",
            "",
            "| Category | Evaluated-subset score | Coverage-limited status | Coverage | Evidence status | N/A rules |",
            "|---|---:|---|---:|---|---:|",
        ]
    )
    for category, result in assessment.category_scores.items():
        lines.append(
            f"| {category.value.replace('_', ' ').title()} | "
            f"{_score(result.evaluated_score)} | {result.score_status.value} | "
            f"{result.coverage:.2%} | {result.coverage_status.value} | "
            f"{result.not_evaluable_checks} |"
        )

    priority = [
        finding
        for finding in assessment.findings
        if finding.status in {FindingStatus.FAIL, FindingStatus.WARNING}
        and finding.severity in {FindingSeverity.BLOCKING, FindingSeverity.MAJOR}
    ]
    lines.extend(["", "## Blocking and major findings", ""])
    if priority:
        lines.extend(_finding_line(finding) for finding in priority)
    else:
        lines.append("- No blocking or major finding was produced from available evidence.")

    lines.extend(
        [
            "",
            "## Room usability",
            "",
            "| Room | Type | Zone | Area m² | Clear m | Aspect | External wall | Opening | Status |",
            "|---|---|---|---:|---:|---:|---|---|---|",
        ]
    )
    for room in assessment.room_assessments:
        aspect = "n/a" if room.aspect_ratio is None else f"{room.aspect_ratio:.2f}"
        lines.append(
            f"| {room.room_name} (`{room.room_id}`) | {room.room_type} | {room.zone} | "
            f"{room.area_m2:.2f} | {room.clear_dimension_m:.2f} | {aspect} | "
            f"{'yes' if room.external_wall_contact else 'no'} | "
            f"{'yes' if room.external_opening else 'no'} | {room.status.value} |"
        )

    section_categories = (
        ("Adjacency findings", QualityCategory.ADJACENCY_QUALITY),
        ("Privacy findings", QualityCategory.PRIVACY_ZONING),
        ("Circulation findings", QualityCategory.CIRCULATION),
    )
    for title, category in section_categories:
        lines.extend(["", f"## {title}", ""])
        findings = [
            finding
            for finding in assessment.findings
            if finding.category is category and finding.status is not FindingStatus.PASS
        ]
        lines.extend(_finding_line(finding) for finding in findings)
        if not findings:
            lines.append("- No warning, failure, or unsupported check in this category.")

    lines.extend(["", "## Daylight and external-access limitations", ""])
    daylight = [
        finding
        for finding in assessment.findings
        if finding.category is QualityCategory.DAYLIGHT_EXTERNAL_ACCESS
    ]
    lines.extend(_finding_line(finding) for finding in daylight)

    severity_order = {
        FindingSeverity.BLOCKING: 0,
        FindingSeverity.MAJOR: 1,
        FindingSeverity.MODERATE: 2,
        FindingSeverity.ADVISORY: 3,
    }
    status_order = {FindingStatus.FAIL: 0, FindingStatus.WARNING: 1}
    recommended = sorted(
        (finding for finding in assessment.findings if finding.status in status_order),
        key=lambda finding: (
            status_order[finding.status],
            severity_order[finding.severity],
            finding.rule_id,
        ),
    )
    lines.extend(["", "## Recommended priorities", ""])
    if recommended:
        for index, finding in enumerate(recommended[:10], start=1):
            lines.append(f"{index}. **{finding.rule_id}:** {finding.recommendation}")
    else:
        lines.append(
            "1. Retain the current plan and repeat the assessment after any geometry change."
        )

    not_evaluable = [
        finding for finding in assessment.findings if finding.status is FindingStatus.NOT_EVALUABLE
    ]
    lines.extend(["", "## Not-evaluable checks", ""])
    for finding in not_evaluable:
        lines.append(f"- **{finding.rule_id} — {finding.title}:** {finding.explanation}")

    lines.extend(["", "## Explicit limitations", ""])
    lines.extend(f"- {limitation}" for limitation in assessment.limitations)
    lines.extend(
        [
            "",
            "## Criteria provenance",
            "",
            f"- Profile: `{assessment.criteria_profile.profile_id}` "
            f"v{assessment.criteria_profile.profile_version}",
            f"- Status: {assessment.criteria_profile.provenance.source_status}",
            f"- Statement: {assessment.criteria_profile.provenance.statement}",
            "",
            f"> {assessment.disclaimer}",
            "",
        ]
    )
    return "\n".join(lines)


def write_quality_summary_markdown(
    path: str | Path, assessment: ArchitecturalQualityAssessment
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_quality_summary_markdown(assessment), encoding="utf-8", newline="\n")
    return path
