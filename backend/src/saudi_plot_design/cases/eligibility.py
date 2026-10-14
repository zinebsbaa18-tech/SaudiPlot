"""Deterministic Saudi residential-villa template eligibility (M6A).

Eligibility describes whether an ingested case is a permissible template
candidate. It is deliberately separate from the human review state: an
eligible case is never automatically approved, while an ineligible case may
still be ingested, corrected, or architect-reviewed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from saudi_plot_design.model import SpdInputError

if TYPE_CHECKING:
    from saudi_plot_design.cases.models import ArchitecturalDesignCase

RESIDENTIAL_VILLA_PROJECT_TYPE = "residential_villa"
RESIDENTIAL_VILLA_CANDIDATE_ROLE = "residential_villa_template_candidate"
SAUDI_COUNTRY_VALUES = frozenset(
    {
        "ksa",
        "kingdom_of_saudi_arabia",
        "sa",
        "sau",
        "saudi_arabia",
    }
)
BEDROOM_SPACE_TYPES = frozenset({"bedroom", "master_bedroom"})
INAPPLICABLE_CHARACTER_VALUES = frozenset(
    {
        "not_applicable",
        "not_applicable_for_saudi_villa_training",
        "unknown",
    }
)


@dataclass(frozen=True)
class TemplateEligibility:
    """Stable, serializable result of the template-candidate policy."""

    template_eligible: bool
    template_ineligibility_reasons: tuple[str, ...]

    def as_case_update(self) -> dict[str, bool | tuple[str, ...]]:
        return {
            "template_eligible": self.template_eligible,
            "template_ineligibility_reasons": self.template_ineligibility_reasons,
        }


class TemplateEligibilityError(SpdInputError):
    """An approved-template decision targeted an ineligible case."""

    def __init__(self, reasons: tuple[str, ...]):
        self.template_ineligibility_reasons = reasons
        payload = json.dumps(
            {
                "template_eligible": False,
                "template_ineligibility_reasons": list(reasons),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        super().__init__(f"approved_template prohibited by template eligibility: {payload}")


def evaluate_template_eligibility(case: ArchitecturalDesignCase) -> TemplateEligibility:
    """Evaluate eligibility from current case content without trusting stored flags."""
    reasons: list[str] = []
    metadata = case.metadata

    project_type = _token(metadata.project_type)
    if project_type != RESIDENTIAL_VILLA_PROJECT_TYPE:
        reasons.append(f"project_type_not_residential_villa:{project_type or 'missing'}")

    country = _token(metadata.country)
    if country not in SAUDI_COUNTRY_VALUES:
        reasons.append(f"country_not_saudi_arabia:{country or 'missing'}")

    declared_role = _declared_case_role(metadata.case_role, metadata.notes)
    if declared_role != RESIDENTIAL_VILLA_CANDIDATE_ROLE:
        reasons.append(f"declared_case_role_ineligible:{declared_role or 'missing'}")

    character = _token(metadata.architectural_character)
    if not character or character in INAPPLICABLE_CHARACTER_VALUES:
        reasons.append(f"architectural_character_not_applicable:{character or 'missing'}")

    if metadata.number_of_floors <= 0:
        reasons.append("residential_villa_floor_count_not_positive")

    space_types = {space.space_type.value for space in case.spaces}
    if not space_types.intersection(BEDROOM_SPACE_TYPES):
        reasons.append("residential_program_missing_bedroom")
    if "bathroom" not in space_types:
        reasons.append("residential_program_missing_bathroom")

    if not metadata.usage_rights_confirmed:
        reasons.append("usage_rights_not_confirmed")

    # Recompute validation so defense-in-depth callers do not trust a stale
    # report attached to a historically or manually modified case.
    from saudi_plot_design.cases.validation import validate_case

    validation = validate_case(case)
    for check in sorted(validation.failures(), key=lambda item: item.id):
        reasons.append(f"blocking_validation_failure:{check.id}")

    from saudi_plot_design.cases.models import CaseState

    if case.state is CaseState.REJECTED:
        reasons.append("case_state_rejected")
    if case.state in {CaseState.ARCHITECT_REVIEWED, CaseState.APPROVED_TEMPLATE}:
        if not case.provenance.reviewer:
            reasons.append("architect_review_record_missing_reviewer")
        if not _valid_iso_date(case.provenance.review_date):
            reasons.append("architect_review_record_invalid_date")
        if not case.provenance.review_binding_fingerprint:
            reasons.append("architect_review_binding_missing")

    ordered = tuple(reasons)
    return TemplateEligibility(
        template_eligible=not ordered,
        template_ineligibility_reasons=ordered,
    )


def record_template_eligibility(case: ArchitecturalDesignCase) -> ArchitecturalDesignCase:
    """Return the case with eligibility fields refreshed from current content."""
    return case.model_copy(update=evaluate_template_eligibility(case).as_case_update())


def _declared_case_role(case_role: str | None, notes: str) -> str | None:
    if case_role is not None and case_role.strip():
        return _token(case_role)
    notes_token = _token(notes)
    if "stress_test" in notes_token or "stress_testing" in notes_token:
        return "ingestion_stress_test"
    if "do_not_use" in notes_token and "template" in notes_token:
        return "not_for_template_use"
    return None


def _token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _valid_iso_date(value: str | None) -> bool:
    if not value:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True
