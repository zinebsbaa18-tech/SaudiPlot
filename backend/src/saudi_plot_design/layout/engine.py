"""Bounded deterministic candidate generation, evaluation, and selection."""

from __future__ import annotations

from itertools import combinations

from saudi_plot_design.layout.geometry import LayoutGeometryError, geometry_fingerprint
from saudi_plot_design.layout.models import (
    CandidateRejection,
    FindingComparison,
    FindingRegression,
    LayoutCandidate,
    LayoutOptimizationResult,
    SearchConfig,
)
from saudi_plot_design.layout.transformations import TRANSFORMATIONS, LayoutTransformation
from saudi_plot_design.model import BuildableEnvelope, Concept
from saudi_plot_design.quality.evaluator import evaluate_architectural_quality
from saudi_plot_design.quality.models import (
    CRITICAL_QUALITY_CATEGORIES,
    FindingSeverity,
    FindingStatus,
    QualityCategory,
)
from saudi_plot_design.route_semantics import route_penalty_summary

RANKING_RULES = (
    "eligible candidates only: valid geometry, complete program, no blocking finding, no disallowed regression",
    "fewer critical-category floor failures",
    "fewer unresolved major fail findings",
    "fewer unresolved major findings",
    "fewer disallowed exterior routes and external guest-WC detours",
    "fewer unknown entrances used as dedicated entrances",
    "fewer unnecessary exit/re-entry routes and lower explicit external-route cost",
    "higher room-usability score",
    "higher privacy-zoning score",
    "higher Saudi-villa functional score",
    "higher circulation score",
    "fewer baseline-relative warning regressions, ordered major then moderate then advisory",
    "higher coverage-adjusted effective overall score",
    "fewer transformations",
    "stable candidate ID",
)

REGRESSION_POLICY = (
    "compare every rule's candidate status with the unchanged M6.1 baseline status",
    "reject every new or worsened fail finding",
    "reject loss of previously evaluable evidence to not_evaluable",
    "reject every unresolved blocking warning or fail",
    "reject a worsened critical-category floor compliance state",
    "permit non-blocking warning trade-offs only when explicitly listed in the candidate audit and ranking",
)

LIMITATIONS = (
    "This is bounded optimization of one authored Compact 3BR skeleton, not arbitrary generative architecture.",
    "M6.1 thresholds and candidate transformations are internal demo heuristics, not official requirements.",
    "The search does not establish structural, MEP, fire, accessibility, constructability, permit, cultural, or professional approval.",
    "A direct service door is only a topology proxy; site access and operational suitability are not evaluated.",
    "Exterior service-door pairs identify only a reviewable route alternative because site-path geometry is not modeled.",
    "Unknown entrance intent never grants route-separation credit and remains subject to review.",
    "Wet-area grouping remains constrained by the authored rectangular topology and external-wall requirements.",
    "Corridor aspect ratio can improve while its area ratio increases; both metrics remain reported.",
)

_EVALUATED_STATUS_RANK = {
    FindingStatus.PASS: 0,
    FindingStatus.WARNING: 1,
    FindingStatus.FAIL: 2,
}


def optimize_layout(
    baseline: Concept,
    envelope: BuildableEnvelope,
    *,
    config: SearchConfig | None = None,
    transformations: tuple[LayoutTransformation, ...] = TRANSFORMATIONS,
) -> LayoutOptimizationResult:
    if not baseline.is_valid:
        raise ValueError("layout optimization requires a valid baseline concept")
    config = config or SearchConfig()
    baseline_assessment = evaluate_architectural_quality(baseline, envelope)
    baseline_fp = geometry_fingerprint(baseline)
    baseline_regressions, baseline_rejection = _regression_guard(
        baseline_assessment, baseline_assessment
    )
    baseline_candidate = LayoutCandidate(
        candidate_id="candidate-000-baseline",
        parent_candidate_id=None,
        transformation_ids=(),
        geometry_fingerprint=baseline_fp,
        concept=baseline,
        validation=baseline.validation,
        quality_assessment=baseline_assessment,
        route_penalties=route_penalty_summary(baseline),
        finding_regressions=baseline_regressions,
        rejection=baseline_rejection,
        eligible_for_selection=baseline_rejection is None,
    )
    candidates: list[LayoutCandidate] = [baseline_candidate]
    fingerprints = {baseline_fp: baseline_candidate.candidate_id}

    sequences = (
        sequence
        for depth in range(1, min(config.max_transformation_depth, len(transformations)) + 1)
        for sequence in combinations(transformations, depth)
    )
    for sequence in sequences:
        if len(candidates) >= config.max_candidates:
            break
        candidate_id = f"candidate-{len(candidates):03d}"
        transformation_ids = tuple(item.transformation_id for item in sequence)
        prefix_ids = transformation_ids[:-1]
        parent = _candidate_id_for_sequence(candidates, prefix_ids)
        concept = baseline
        audits = []
        try:
            for transformation in sequence:
                concept, audit = transformation.apply(concept, candidate_id)
                audits.append(audit)
                if not concept.is_valid:
                    failures = "; ".join(concept.rejection_reasons)
                    raise LayoutGeometryError(failures or "planner validation failed")
            fingerprint = geometry_fingerprint(concept)
            if fingerprint in fingerprints:
                candidates.append(
                    LayoutCandidate(
                        candidate_id=candidate_id,
                        parent_candidate_id=parent,
                        transformation_ids=transformation_ids,
                        geometry_fingerprint=fingerprint,
                        concept=concept,
                        validation=concept.validation,
                        quality_assessment=None,
                        transformation_audit=tuple(audits),
                        duplicate_of_candidate_id=fingerprints[fingerprint],
                        rejection=CandidateRejection(
                            code="duplicate_geometry",
                            explanation=(
                                f"geometry duplicates {fingerprints[fingerprint]}; duplicate is not evaluated or ranked"
                            ),
                        ),
                    )
                )
                continue
            fingerprints[fingerprint] = candidate_id
            assessment = evaluate_architectural_quality(concept, envelope)
            regressions, rejection = _regression_guard(baseline_assessment, assessment)
            candidate = LayoutCandidate(
                candidate_id=candidate_id,
                parent_candidate_id=parent,
                transformation_ids=transformation_ids,
                geometry_fingerprint=fingerprint,
                concept=concept,
                validation=concept.validation,
                quality_assessment=assessment,
                route_penalties=route_penalty_summary(concept),
                transformation_audit=tuple(audits),
                finding_regressions=regressions,
                rejection=rejection,
                eligible_for_selection=rejection is None,
            )
            candidates.append(candidate)
        except (LayoutGeometryError, ValueError, AssertionError) as exc:
            candidates.append(
                LayoutCandidate(
                    candidate_id=candidate_id,
                    parent_candidate_id=parent,
                    transformation_ids=transformation_ids,
                    geometry_fingerprint=None,
                    concept=None,
                    validation=None,
                    quality_assessment=None,
                    transformation_audit=tuple(audits),
                    rejection=CandidateRejection(
                        code="invalid_transformation",
                        explanation=str(exc),
                    ),
                )
            )

    ranked: list[LayoutCandidate] = []
    for candidate in candidates:
        if candidate.eligible_for_selection and candidate.quality_assessment is not None:
            ranked.append(candidate.model_copy(update={"selection_rank": _rank(candidate)}))
        else:
            ranked.append(candidate)
    eligible = [candidate for candidate in ranked if candidate.eligible_for_selection]
    if not eligible:
        raise ValueError(
            "layout optimization produced no candidate eligible under the blocking and regression guards"
        )
    selected = min(eligible, key=lambda candidate: candidate.selection_rank)
    comparisons = _finding_comparison(baseline_assessment, selected.quality_assessment)
    return LayoutOptimizationResult(
        heuristic_notice=(
            "Deterministic concept-layout diagnostic only; selection is not architectural, cultural, regulatory, or professional approval."
        ),
        config=config,
        ranking_rules=RANKING_RULES,
        regression_policy=REGRESSION_POLICY,
        candidates=tuple(ranked),
        selected_candidate_id=selected.candidate_id,
        finding_comparison=comparisons,
        limitations=LIMITATIONS,
    )


def _candidate_id_for_sequence(
    candidates: list[LayoutCandidate], transformation_ids: tuple[str, ...]
) -> str:
    if not transformation_ids:
        return candidates[0].candidate_id
    for candidate in candidates:
        if candidate.transformation_ids == transformation_ids:
            return candidate.candidate_id
    return candidates[0].candidate_id


def _regression_guard(baseline, candidate):
    baseline_findings = {finding.rule_id: finding for finding in baseline.findings}
    candidate_findings = {finding.rule_id: finding for finding in candidate.findings}
    regressions: list[FindingRegression] = []
    reasons: list[str] = []
    for rule_id in sorted(set(baseline_findings) | set(candidate_findings)):
        before = baseline_findings.get(rule_id)
        after = candidate_findings.get(rule_id)
        if before is None or after is None:
            exemplar = before or after
            assert exemplar is not None
            regressions.append(
                FindingRegression(
                    rule_id=rule_id,
                    category=exemplar.category.value,
                    severity=exemplar.severity.value,
                    baseline_status=before.status.value if before else "missing",
                    candidate_status=after.status.value if after else "missing",
                    disposition="rejected",
                    explanation="baseline and candidate rule sets are not identical",
                )
            )
            reasons.append(f"quality rule set mismatch at {rule_id}")
            continue
        if not _status_worsened(before.status, after.status):
            continue
        evidence_loss = (
            after.status is FindingStatus.NOT_EVALUABLE
            and before.status is not FindingStatus.NOT_EVALUABLE
        )
        disallowed = (
            after.status is FindingStatus.FAIL
            or after.severity is FindingSeverity.BLOCKING
            or evidence_loss
        )
        disposition = "rejected" if disallowed else "reported_tradeoff"
        if evidence_loss:
            explanation = "loss of previously evaluable M6.1 evidence is not permitted"
        elif disallowed:
            explanation = "new or worsened fail/blocking finding is not permitted"
        else:
            explanation = (
                "non-blocking warning trade-off retained for explicit ranking and reporting"
            )
        regressions.append(
            FindingRegression(
                rule_id=rule_id,
                category=after.category.value,
                severity=after.severity.value,
                baseline_status=before.status.value,
                candidate_status=after.status.value,
                disposition=disposition,
                explanation=explanation,
            )
        )
        if disallowed:
            reasons.append(f"{rule_id} worsened {before.status.value}->{after.status.value}")

    blocking = [
        finding.rule_id
        for finding in candidate.findings
        if finding.severity is FindingSeverity.BLOCKING
        and finding.status in {FindingStatus.WARNING, FindingStatus.FAIL}
    ]
    if blocking:
        reasons.append("unresolved blocking findings: " + ", ".join(sorted(blocking)))

    baseline_floors = {
        failure.category: failure.maximum_status for failure in baseline.category_floor_failures
    }
    candidate_floors = {
        failure.category: failure.maximum_status for failure in candidate.category_floor_failures
    }
    floor_rank = {
        "not_rated_insufficient_evidence": 0,
        "unsuitable_concept_baseline": 1,
        "substantial_architectural_revision_required": 2,
        "workable_with_targeted_revisions": 3,
        "strong_concept_candidate": 4,
    }
    for category in CRITICAL_QUALITY_CATEGORIES:
        before = baseline_floors.get(category)
        after = candidate_floors.get(category)
        before_rank = 4 if before is None else floor_rank[before.value]
        after_rank = 4 if after is None else floor_rank[after.value]
        if after_rank < before_rank:
            reasons.append(f"critical category floor worsened: {category.value}")

    rejection = None
    if reasons:
        rejection = CandidateRejection(
            code="selection_guard_failed",
            explanation="; ".join(sorted(set(reasons))),
        )
    return tuple(regressions), rejection


def _rank(candidate: LayoutCandidate) -> tuple:
    assessment = candidate.quality_assessment
    assert assessment is not None
    penalties = candidate.route_penalties or route_penalty_summary(candidate.concept)

    def category_score(category: QualityCategory) -> float:
        return assessment.category_scores[category].evaluated_score or 0.0

    failed_major = sum(
        finding.severity is FindingSeverity.MAJOR and finding.status is FindingStatus.FAIL
        for finding in assessment.findings
    )
    unresolved_major = sum(
        finding.severity is FindingSeverity.MAJOR
        and finding.status in {FindingStatus.WARNING, FindingStatus.FAIL}
        for finding in assessment.findings
    )
    warning_regressions = tuple(
        regression
        for regression in candidate.finding_regressions
        if regression.disposition == "reported_tradeoff"
    )
    regression_cost = tuple(
        sum(regression.severity == severity for regression in warning_regressions)
        for severity in ("major", "moderate", "advisory")
    )
    return (
        len(assessment.category_floor_failures),
        failed_major,
        unresolved_major,
        penalties.disallowed_external_routes,
        penalties.external_guest_wc_detours,
        penalties.unknown_entrances_used_as_dedicated,
        penalties.unnecessary_exit_reentry_routes,
        penalties.selected_external_routes,
        penalties.external_route_extra_cost,
        -category_score(QualityCategory.ROOM_USABILITY),
        -category_score(QualityCategory.PRIVACY_ZONING),
        -category_score(QualityCategory.SAUDI_VILLA_FUNCTIONAL),
        -category_score(QualityCategory.CIRCULATION),
        *regression_cost,
        -(assessment.overall_score or 0.0),
        len(candidate.transformation_ids),
        candidate.candidate_id,
    )


def _finding_comparison(baseline, selected) -> tuple[FindingComparison, ...]:
    before = {finding.rule_id: finding.status for finding in baseline.findings}
    after = {finding.rule_id: finding.status for finding in selected.findings}
    result = []
    for rule_id in sorted(before):
        if before[rule_id] == after[rule_id]:
            change = "unchanged"
        elif _status_improved(before[rule_id], after[rule_id]):
            change = "improved"
        else:
            change = "worsened"
        result.append(
            FindingComparison(
                rule_id=rule_id,
                baseline_status=before[rule_id].value,
                selected_status=after[rule_id].value,
                change=change,
            )
        )
    return tuple(result)


def _status_worsened(before: FindingStatus, after: FindingStatus) -> bool:
    if before is FindingStatus.NOT_EVALUABLE:
        return False
    if after is FindingStatus.NOT_EVALUABLE:
        return True
    return _EVALUATED_STATUS_RANK[after] > _EVALUATED_STATUS_RANK[before]


def _status_improved(before: FindingStatus, after: FindingStatus) -> bool:
    if before is FindingStatus.NOT_EVALUABLE:
        return after is not FindingStatus.NOT_EVALUABLE
    if after is FindingStatus.NOT_EVALUABLE:
        return False
    return _EVALUATED_STATUS_RANK[after] < _EVALUATED_STATUS_RANK[before]


__all__ = ["optimize_layout", "RANKING_RULES", "REGRESSION_POLICY"]
