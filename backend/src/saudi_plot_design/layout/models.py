"""Immutable audit models for the bounded M6.2 layout search.

The engine is an internal deterministic concept-layout heuristic.  These
models intentionally make candidate rejection, trade-offs, and selection
traceable; they do not represent architectural or regulatory approval.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from saudi_plot_design.model import Concept, ValidationReport
from saudi_plot_design.output import DISCLAIMER
from saudi_plot_design.quality.models import ArchitecturalQualityAssessment
from saudi_plot_design.route_semantics import RoutePenaltySummary


ENGINE_VERSION = "1.1.0"
AUDIT_SCHEMA_VERSION = 2


class SearchConfig(BaseModel):
    """Versioned, explicitly bounded search configuration."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = AUDIT_SCHEMA_VERSION
    max_candidates: int = Field(default=32, ge=1, le=256)
    max_transformation_depth: int = Field(default=5, ge=0, le=8)


class GeometryChange(BaseModel):
    """A reversible full before/after snapshot of one changed object."""

    model_config = ConfigDict(frozen=True)

    object_type: str
    object_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class TransformationAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    transformation_id: str
    description: str
    affected_room_ids: tuple[str, ...]
    affected_opening_ids: tuple[str, ...]
    changes: tuple[GeometryChange, ...]


class CandidateRejection(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    explanation: str


class FindingRegression(BaseModel):
    """Baseline-relative per-rule status comparison used by the guard."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    category: str
    severity: str
    baseline_status: str
    candidate_status: str
    disposition: str
    explanation: str


class LayoutCandidate(BaseModel):
    """One generated candidate, including invalid and duplicate attempts."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    candidate_id: str
    parent_candidate_id: str | None
    transformation_ids: tuple[str, ...]
    geometry_fingerprint: str | None
    concept: Concept | None
    validation: ValidationReport | None
    quality_assessment: ArchitecturalQualityAssessment | None
    route_penalties: RoutePenaltySummary | None = None
    transformation_audit: tuple[TransformationAudit, ...] = ()
    finding_regressions: tuple[FindingRegression, ...] = ()
    rejection: CandidateRejection | None = None
    duplicate_of_candidate_id: str | None = None
    eligible_for_selection: bool = False
    selection_rank: tuple[Any, ...] | None = None

    @property
    def is_valid(self) -> bool:
        return (
            self.rejection is None
            and self.duplicate_of_candidate_id is None
            and self.concept is not None
            and self.concept.is_valid
            and self.validation is not None
            and self.validation.passed
            and self.quality_assessment is not None
        )


class FindingComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str
    baseline_status: str
    selected_status: str
    change: str


class LayoutOptimizationResult(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    schema_version: int = AUDIT_SCHEMA_VERSION
    engine_version: str = ENGINE_VERSION
    disclaimer: str = DISCLAIMER
    heuristic_notice: str
    config: SearchConfig
    ranking_rules: tuple[str, ...]
    regression_policy: tuple[str, ...]
    candidates: tuple[LayoutCandidate, ...]
    selected_candidate_id: str
    finding_comparison: tuple[FindingComparison, ...]
    limitations: tuple[str, ...]

    @property
    def baseline_candidate(self) -> LayoutCandidate:
        return self.candidates[0]

    @property
    def selected_candidate(self) -> LayoutCandidate:
        return next(
            candidate
            for candidate in self.candidates
            if candidate.candidate_id == self.selected_candidate_id
        )

    @property
    def selected_concept(self) -> Concept:
        concept = self.selected_candidate.concept
        if concept is None:  # protected by engine selection invariants
            raise RuntimeError("selected layout candidate has no concept")
        return concept

    @property
    def generated_candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def valid_candidate_count(self) -> int:
        return sum(candidate.is_valid for candidate in self.candidates)

    @property
    def rejected_candidate_count(self) -> int:
        return sum(not candidate.is_valid for candidate in self.candidates)
