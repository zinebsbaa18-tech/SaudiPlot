"""Canonical Architectural Design Case model (M6A).

Every extracted object retains its IFC GlobalId for source traceability.
Classifications are never silent guesses: each carries method, confidence,
source, and reviewer status. Review state and objective eligibility jointly
gate template use.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, StrictBool

from saudi_plot_design.model import ValidationReport

CASE_SCHEMA_VERSION = 2


class CaseState(str, Enum):
    INGESTED = "ingested"
    REQUIRES_REVIEW = "requires_review"
    CORRECTED = "corrected"
    ARCHITECT_REVIEWED = "architect_reviewed"
    APPROVED_TEMPLATE = "approved_template"
    REJECTED = "rejected"


class Zone(str, Enum):
    GUEST_PUBLIC = "guest_public"
    FAMILY = "family"
    PRIVATE_BEDROOMS = "private_bedrooms"
    SERVICE = "service"
    WET = "wet"
    CIRCULATION = "circulation"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class SpaceType(str, Enum):
    MENS_MAJLIS = "mens_majlis"
    WOMENS_MAJLIS = "womens_majlis"
    LIVING = "living"
    DINING = "dining"
    KITCHEN = "kitchen"
    MASTER_BEDROOM = "master_bedroom"
    BEDROOM = "bedroom"
    BATHROOM = "bathroom"
    MAID_ROOM = "maid_room"
    LAUNDRY = "laundry"
    STORAGE = "storage"
    CORRIDOR = "corridor"
    STAIR = "stair"
    ELEVATOR = "elevator"
    OTHER = "other"
    UNKNOWN = "unknown"


class EntranceType(str, Enum):
    MAIN_FAMILY = "main_family_entrance"
    MENS_MAJLIS = "mens_majlis_entrance"
    SERVICE = "service_entrance"
    DRIVER = "driver_entrance"
    UNKNOWN = "unknown"


class Classification(BaseModel):
    """A reviewable, never-silent inference."""

    model_config = ConfigDict(frozen=True)

    value: str
    method: str  # "name_keyword" | "manual_correction" | "metadata" | "unclassified"
    confidence: float  # 0.0-1.0; manual corrections are 1.0
    source: str  # what the inference was derived from (e.g. the IFC name)
    reviewer_status: str = "requires_review"  # or "reviewer_confirmed"


class CaseMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    project_type: str
    # Explicit purpose of this case. Missing stays unknown; it is never
    # silently treated as permission to derive a template.
    case_role: str | None = None
    country: str
    city: str
    district: str | None = None
    architectural_character: str
    source_format: str
    authoring_software: str
    number_of_floors: int
    approval_status: str
    approved_by: str | None
    # Strict booleans: the privacy/legal gates must be the literal JSON
    # true/false - coerced strings like "yes" must not pass them.
    usage_rights_confirmed: StrictBool
    confidential: StrictBool
    anonymization_required: StrictBool
    quality_rating: str
    notes: str = ""


class Level(BaseModel):
    model_config = ConfigDict(frozen=True)

    ifc_global_id: str
    name: str
    elevation_m: float | None  # None + warning when the source omits it


class Space(BaseModel):
    model_config = ConfigDict(frozen=True)

    ifc_global_id: str
    name: str
    long_name: str | None
    level_id: str  # Level.ifc_global_id
    area_m2: float | None  # None + warning when the source has no quantity
    height_m: float | None
    space_type: Classification
    zone: Classification
    boundary_wall_ids: tuple[str, ...] = ()  # IfcWall GlobalIds bounding this space
    is_external: bool = False  # the space has at least one EXTERNAL boundary


class CaseWall(BaseModel):
    model_config = ConfigDict(frozen=True)

    ifc_global_id: str
    name: str
    level_id: str
    start: tuple[float, float] | None  # world meters; None + warning if no axis
    end: tuple[float, float] | None
    length_m: float | None
    thickness_m: float | None
    height_m: float | None
    is_external: bool
    material: str | None
    bounded_space_ids: tuple[str, ...] = ()


class CaseSlab(BaseModel):
    model_config = ConfigDict(frozen=True)

    ifc_global_id: str
    name: str
    level_id: str
    thickness_m: float | None
    area_m2: float | None


class CaseOpening(BaseModel):
    model_config = ConfigDict(frozen=True)

    ifc_global_id: str
    name: str
    kind: str  # "door" | "window"
    level_id: str
    host_wall_id: str | None  # None + warning when no host relationship
    width_m: float | None
    height_m: float | None
    sill_height_m: float | None
    connects_space_ids: tuple[str, ...] = ()
    is_external: bool = False


class Entrance(BaseModel):
    model_config = ConfigDict(frozen=True)

    door_id: str  # CaseOpening.ifc_global_id
    entrance_type: Classification
    into_space_id: str | None


class GraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    a: str
    b: str
    via: str | None = None  # wall/door GlobalId that creates the relationship


class CaseGraphs(BaseModel):
    model_config = ConfigDict(frozen=True)

    room_adjacency: tuple[GraphEdge, ...]
    circulation: tuple[GraphEdge, ...]  # door-connected
    zone_adjacency: tuple[GraphEdge, ...]
    entrance_paths: dict[str, tuple[str, ...]]  # entrance door id -> reachable space ids
    guest_path: tuple[str, ...]
    family_path: tuple[str, ...]
    service_path: tuple[str, ...]
    wet_groups: tuple[tuple[str, ...], ...]


class CaseMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    net_room_area_m2: float
    circulation_area_m2: float
    circulation_percent: float | None
    zone_area_ratios: dict[str, float]
    external_walls_per_habitable_room: dict[str, int]
    entrance_counts: dict[str, int]
    bedroom_count: int
    bathroom_count: int
    average_room_aspect_ratio: float | None
    # Missing source areas make area-derived metrics undercounts; they are
    # flagged explicitly instead of being silently treated as zero.
    spaces_without_area: tuple[str, ...] = ()
    area_metrics_complete: bool = True
    note: str = "Descriptive metrics only - no automatic architectural quality claim is made."


class SourceProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_directory_recorded: str  # anonymized-safe display path (never copied)
    source_format: str
    ifc_schema: str
    source_fingerprint: str  # sha256 of model.ifc bytes
    metadata_fingerprint: str
    # Binds a human review decision to the exact reviewed content (source +
    # metadata + corrections); review_decision.json must echo it back.
    review_binding_fingerprint: str = ""
    ownership_status: str
    permitted_usage: str
    confidentiality_status: str
    anonymization_status: str
    project_code: str
    reviewer: str | None
    review_date: str | None = None
    approval_status: str


class ArchitecturalDesignCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = CASE_SCHEMA_VERSION
    case_id: str
    state: CaseState
    template_eligible: bool = False
    template_ineligibility_reasons: tuple[str, ...] = ()
    metadata: CaseMetadata
    provenance: SourceProvenance
    building_type: str
    site_note: str | None
    levels: tuple[Level, ...]
    spaces: tuple[Space, ...]
    walls: tuple[CaseWall, ...]
    slabs: tuple[CaseSlab, ...]
    doors: tuple[CaseOpening, ...]
    windows: tuple[CaseOpening, ...]
    entrances: tuple[Entrance, ...]
    graphs: CaseGraphs
    facade_openings: tuple[str, ...]  # external opening GlobalIds
    metrics: CaseMetrics
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]
    validation: ValidationReport | None = None


class TemplateUseBlocked(RuntimeError):
    """Raised when generator code attempts to use a non-approved case."""

    def __init__(self, message: str, reasons: tuple[str, ...] = ()):
        self.template_ineligibility_reasons = reasons
        super().__init__(message)


def assert_template_usable(case: ArchitecturalDesignCase) -> None:
    """Defense-in-depth gate: require approval and current eligibility."""
    if case.state is not CaseState.APPROVED_TEMPLATE:
        raise TemplateUseBlocked(
            f"case '{case.case_id}' is in state '{case.state.value}' - only "
            f"'approved_template' cases may be used; human architect review "
            f"and explicit approval metadata are required",
            (f"state_not_approved_template:{case.state.value}",),
        )
    from saudi_plot_design.cases.eligibility import evaluate_template_eligibility

    eligibility = evaluate_template_eligibility(case)
    if not eligibility.template_eligible:
        reasons = eligibility.template_ineligibility_reasons
        raise TemplateUseBlocked(
            f"case '{case.case_id}' is approved_template but is objectively "
            f"template-ineligible: {list(reasons)}",
            reasons,
        )
