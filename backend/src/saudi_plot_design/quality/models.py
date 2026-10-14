"""Typed M6.1 criteria and assessment models.

The models deliberately distinguish measured evidence, heuristic expectations,
and unsupported conclusions. Nothing in this package represents regulatory,
cultural, or professional architectural approval.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from saudi_plot_design.output import DISCLAIMER


class QualityCategory(str, Enum):
    GEOMETRIC_VALIDITY = "geometric_validity"
    PROGRAM_COMPLETENESS = "program_completeness"
    ROOM_USABILITY = "room_usability"
    ADJACENCY_QUALITY = "adjacency_quality"
    PRIVACY_ZONING = "privacy_zoning"
    CIRCULATION = "circulation"
    DAYLIGHT_EXTERNAL_ACCESS = "daylight_external_access_proxy"
    WET_AREA_ORGANIZATION = "wet_area_organization"
    SAUDI_VILLA_FUNCTIONAL = "saudi_villa_functional_character"


class FindingSeverity(str, Enum):
    BLOCKING = "blocking"
    MAJOR = "major"
    MODERATE = "moderate"
    ADVISORY = "advisory"


class FindingStatus(str, Enum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    NOT_EVALUABLE = "not_evaluable"


class ScoreStatus(str, Enum):
    STRONG = "strong_concept_candidate"
    WORKABLE = "workable_with_targeted_revisions"
    SUBSTANTIAL_REVISION = "substantial_architectural_revision_required"
    UNSUITABLE = "unsuitable_concept_baseline"
    NOT_RATED = "not_rated_insufficient_evidence"


class CoverageStatus(str, Enum):
    COMPLETE = "complete_evidence"
    PARTIAL = "partial_evidence"
    INSUFFICIENT = "insufficient_evidence"


CRITICAL_QUALITY_CATEGORIES = (
    QualityCategory.ROOM_USABILITY,
    QualityCategory.PRIVACY_ZONING,
    QualityCategory.CIRCULATION,
    QualityCategory.SAUDI_VILLA_FUNCTIONAL,
)


class CriteriaProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: Literal["demo"]
    source_status: str
    statement: str
    official: Literal[False] = False


class RoomTypeCriterion(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_area_m2: float = Field(gt=0)
    min_clear_dimension_m: float = Field(gt=0)
    max_aspect_ratio: float = Field(gt=1)


class RuleCriterion(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(pattern=r"^[A-Z]{3}-\d{3}$")
    category: QualityCategory
    title: str
    severity: FindingSeverity
    contribution_percent: float = Field(gt=0, le=100)
    unit: str
    support: Literal["evaluated", "conditional", "unsupported"] = "evaluated"


class CriticalCategoryFloor(BaseModel):
    """Internal score floors; these are heuristics, never regulatory minima."""

    model_config = ConfigDict(frozen=True)

    strong_min_score: float = Field(ge=0, le=100)
    workable_min_score: float = Field(ge=0, le=100)
    substantial_revision_min_score: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def ordered_floors(self) -> CriticalCategoryFloor:
        if not (
            self.strong_min_score >= self.workable_min_score >= self.substantial_revision_min_score
        ):
            raise ValueError("critical category floors must descend by status")
        return self


class ScoringConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    warning_factors: dict[FindingSeverity, float]
    fail_factors: dict[FindingSeverity, float]
    min_category_coverage: float = Field(ge=0, le=1)
    min_overall_coverage: float = Field(ge=0, le=1)
    mandatory_category_coverage: float = Field(ge=0, le=1)
    mandatory_coverage_categories: tuple[QualityCategory, ...]
    complete_category_coverage: float = Field(ge=0, le=1)
    strong_min_evidence_coverage: float = Field(ge=0, le=1)
    strong_min_critical_category_coverage: float = Field(ge=0, le=1)
    critical_category_floors: dict[QualityCategory, CriticalCategoryFloor]
    max_unresolved_major_findings_for_strong: int = Field(ge=0)
    blocking_geometry_score_cap: float = Field(ge=0, lt=50)
    score_rounding_digits: int = Field(ge=0, le=4)

    @model_validator(mode="after")
    def complete_factor_maps(self) -> ScoringConfiguration:
        severities = set(FindingSeverity)
        if set(self.warning_factors) != severities or set(self.fail_factors) != severities:
            raise ValueError("warning and fail factors must define every severity")
        if any(not 0 <= value <= 1 for value in self.warning_factors.values()):
            raise ValueError("warning factors must be between 0 and 1")
        if any(not 0 <= value <= 1 for value in self.fail_factors.values()):
            raise ValueError("fail factors must be between 0 and 1")
        if tuple(self.critical_category_floors) != CRITICAL_QUALITY_CATEGORIES:
            raise ValueError("critical category floors must use the stable critical-category order")
        if len(self.mandatory_coverage_categories) != len(set(self.mandatory_coverage_categories)):
            raise ValueError("mandatory coverage categories must be unique")
        if self.min_category_coverage > self.complete_category_coverage:
            raise ValueError("complete category coverage cannot be below minimum coverage")
        if self.min_overall_coverage > self.strong_min_evidence_coverage:
            raise ValueError("strong evidence coverage cannot be below minimum overall coverage")
        if self.mandatory_category_coverage > self.strong_min_critical_category_coverage:
            raise ValueError("strong critical-category coverage cannot be below mandatory coverage")
        return self


class CriteriaProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str
    profile_version: str
    description: str
    provenance: CriteriaProvenance
    units: dict[str, str]
    category_weights: dict[QualityCategory, float]
    rules: tuple[RuleCriterion, ...]
    room_type_criteria: dict[str, RoomTypeCriterion]
    preferred_adjacencies: tuple[tuple[str, str], ...]
    discouraged_zone_transitions: tuple[tuple[str, str], ...]
    thresholds: dict[str, float]
    scoring: ScoringConfiguration
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def validate_weights_and_order(self) -> CriteriaProfile:
        categories = tuple(QualityCategory)
        if tuple(self.category_weights) != categories:
            raise ValueError("category_weights must contain every category in stable enum order")
        if abs(sum(self.category_weights.values()) - 100.0) > 1e-9:
            raise ValueError("category weights must sum to 100 percent")
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("quality rule ids must be unique")
        if ids != sorted(
            ids, key=lambda rule_id: (categories.index(self._category(rule_id)), rule_id)
        ):
            raise ValueError("quality rules must be ordered by category then rule id")
        for category in categories:
            total = sum(
                rule.contribution_percent for rule in self.rules if rule.category is category
            )
            if abs(total - 100.0) > 1e-9:
                raise ValueError(f"{category.value} rule contributions must sum to 100 percent")
        if self.provenance.level != "demo" or self.provenance.official:
            raise ValueError("M6.1 quality criteria must carry non-official demo provenance")
        return self

    def _category(self, rule_id: str) -> QualityCategory:
        return next(rule.category for rule in self.rules if rule.rule_id == rule_id)

    def rule(self, rule_id: str) -> RuleCriterion:
        return next(rule for rule in self.rules if rule.rule_id == rule_id)


class QualityFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str
    category: QualityCategory
    severity: FindingSeverity
    status: FindingStatus
    affected_object_ids: tuple[str, ...]
    title: str
    explanation: str
    evidence: tuple[str, ...]
    measured_value: JsonValue
    expected_value: JsonValue
    recommendation: str
    confidence: float = Field(ge=0, le=1)
    source_method: str


class CategoryScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    # ``score`` remains as a backward-compatible alias for the evaluated-subset score.
    score: float | None = Field(default=None, ge=0, le=100)
    evaluated_score: float | None = Field(default=None, ge=0, le=100)
    score_status: ScoreStatus
    evaluated_weight: float = Field(ge=0)
    total_weight: float = Field(gt=0)
    coverage: float = Field(ge=0, le=1)
    coverage_status: CoverageStatus
    evaluated_checks: int = Field(ge=0)
    not_evaluable_checks: int = Field(ge=0)
    total_checks: int = Field(ge=0)
    # ``confidence`` is retained for compatibility; it is evidence coverage,
    # not a statistical confidence estimate.
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def consistent_compatibility_fields(self) -> CategoryScore:
        if self.score != self.evaluated_score:
            raise ValueError("score and evaluated_score must match")
        if self.coverage != self.confidence:
            raise ValueError("coverage and compatibility confidence must match")
        if self.evaluated_checks + self.not_evaluable_checks != self.total_checks:
            raise ValueError("category check counts must sum to total_checks")
        return self


class StatusConstraint(BaseModel):
    model_config = ConfigDict(frozen=True)

    constraint_id: str = Field(pattern=r"^[a-z0-9_:.-]+$")
    maximum_status: ScoreStatus
    explanation: str
    affected_categories: tuple[QualityCategory, ...] = ()
    affected_rule_ids: tuple[str, ...] = ()


class CategoryFloorFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: QualityCategory
    evaluated_score: float | None = Field(default=None, ge=0, le=100)
    required_minimum: float = Field(ge=0, le=100)
    required_for_status: ScoreStatus
    maximum_status: ScoreStatus


class RoomAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    room_id: str
    room_name: str
    room_type: str
    zone: str
    area_m2: float
    clear_dimension_m: float
    aspect_ratio: float | None
    external_wall_contact: bool
    external_opening: bool
    status: FindingStatus
    finding_rule_ids: tuple[str, ...]


class PlanMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    room_count: int
    bedroom_count: int
    bathroom_count: int
    habitable_room_count: int
    wet_room_count: int
    external_wall_room_count: int
    external_opening_room_count: int
    disconnected_room_count: int
    unreachable_room_count: int
    door_graph_edges: int
    wall_adjacency_edges: int
    footprint_area_m2: float
    total_room_area_m2: float
    circulation_area_m2: float
    circulation_ratio: float
    wet_cluster_count: int
    evaluation_coverage: float


class ArchitecturalQualityAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    assessment_version: str
    disclaimer: str = DISCLAIMER
    raw_weighted_score: float | None = Field(default=None, ge=0, le=100)
    evidence_coverage: float = Field(ge=0, le=1)
    coverage_adjusted_score: float | None = Field(default=None, ge=0, le=100)
    overall_score: float | None
    score_status: ScoreStatus
    status_constraints: tuple[StatusConstraint, ...]
    category_floor_failures: tuple[CategoryFloorFailure, ...]
    category_scores: dict[QualityCategory, CategoryScore]
    # Backward-compatible name for evidence coverage. This is not a
    # statistical confidence estimate.
    evaluation_confidence: float = Field(ge=0, le=1)
    evaluated_weight: float = Field(ge=0)
    total_weight: float = Field(gt=0)
    evaluated_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    not_evaluable_checks: int
    findings: tuple[QualityFinding, ...]
    room_assessments: tuple[RoomAssessment, ...]
    plan_metrics: PlanMetrics
    criteria_profile: CriteriaProfile
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def consistent_coverage_fields(self) -> ArchitecturalQualityAssessment:
        if self.evidence_coverage != self.evaluation_confidence:
            raise ValueError("evidence_coverage and evaluation_confidence must match")
        if self.overall_score is not None and self.coverage_adjusted_score is None:
            raise ValueError("a rated overall score requires a coverage-adjusted score")
        if (
            self.overall_score is not None
            and self.coverage_adjusted_score is not None
            and self.overall_score > self.coverage_adjusted_score
        ):
            raise ValueError("overall_score cannot exceed coverage_adjusted_score")
        return self
