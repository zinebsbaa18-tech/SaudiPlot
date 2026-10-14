"""Frozen M7.1 schemas for source bundles, case versions, and indexes."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    field_validator,
    model_validator,
)

SOURCE_BUNDLE_SCHEMA_VERSION = 1
PROJECT_PACKAGE_SCHEMA_VERSION = 1
FEATURE_PACKAGE_SCHEMA_VERSION = 1
# Registry v2 added package_lifecycle_state; manifest v2 added
# root_fingerprint. Root artifacts are derived, so no migration exists:
# older layouts are rejected and regenerated via `library rebuild-index`.
REGISTRY_SCHEMA_VERSION = 3
ACTIVE_INDEX_SCHEMA_VERSION = 2
LIBRARY_VALIDATION_SCHEMA_VERSION = 1
LIBRARY_MANIFEST_SCHEMA_VERSION = 2
REVIEW_PACKAGE_SCHEMA_VERSION = 1
CORRECTIONS_SCHEMA_VERSION = 1
ARCHITECT_DECISION_SCHEMA_VERSION = 1
SHA256_PATTERN = r"^[0-9a-f]{64}$"
VERSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
CASE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"


def _validate_iso_timestamp(value: str) -> str:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("generated_at must be an ISO-8601 timestamp") from None
    return value


class CaseRole(str, Enum):
    SOURCE_PROJECT = "source_project"
    INGESTION_STRESS_TEST = "ingestion_stress_test"
    ARCHITECTURAL_REFERENCE = "architectural_reference"
    RESIDENTIAL_VILLA_CANDIDATE = "residential_villa_candidate"
    ARCHITECT_REVIEWED_REFERENCE = "architect_reviewed_reference"
    APPROVED_TEMPLATE = "approved_template"
    REJECTED = "rejected"
    ARCHIVED = "archived"
    EXCLUDED = "excluded"


class LifecycleState(str, Enum):
    INGESTED = "ingested"
    REQUIRES_REVIEW = "requires_review"
    CORRECTED = "corrected"
    ARCHITECT_REVIEWED = "architect_reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"
    EXCLUDED = "excluded"


class ReviewState(str, Enum):
    NOT_REVIEWED = "not_reviewed"
    REQUIRES_REVIEW = "requires_review"
    ARCHITECT_REVIEWED = "architect_reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class ReviewDecisionType(str, Enum):
    REQUIRES_REVISION = "requires_revision"
    ARCHITECT_REVIEWED = "architect_reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class AssetFormat(str, Enum):
    IFC = "ifc"
    RVT = "rvt"
    DWG = "dwg"
    PDF = "pdf"
    IMAGE = "image"
    SPECIFICATION = "specification"
    METADATA = "metadata"
    REVIEW_DECISION = "review_decision"
    OTHER = "other"


class ParserStatus(str, Enum):
    PARSED = "parsed"
    CATALOGUED_NOT_PARSED = "catalogued_not_parsed"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"


class OriginalPathPolicy(str, Enum):
    OMITTED = "omitted"
    ANONYMIZED_DISPLAY_NAME = "anonymized_display_name"
    EXTERNAL_REFERENCE_ONLY = "external_reference_only"


class FeatureStatus(str, Enum):
    EXTRACTED = "extracted"
    SOURCE_MISSING = "source_missing"
    NOT_APPLICABLE = "not_applicable"
    REQUIRES_REVIEW = "requires_review"


class CreationMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    created_at: str
    created_by: str = Field(min_length=1)
    source: str = Field(min_length=1)

    @field_validator("created_at")
    @classmethod
    def valid_timestamp(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("created_at must be an ISO-8601 timestamp") from None
        return value


class UsageRights(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ingestion_permitted: StrictBool
    internal_review_permitted: StrictBool
    template_use_permitted: StrictBool
    template_use_revoked: StrictBool = False
    rights_basis: str = Field(min_length=1)


class Confidentiality(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["public", "internal", "confidential"]
    anonymized: StrictBool
    shareable_outputs_permitted: StrictBool


class SourceAsset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    asset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    display_name: str = Field(min_length=1)
    format: AssetFormat
    role: str = Field(min_length=1)
    parser_status: ParserStatus
    size_bytes: int | None = Field(default=None, ge=0)
    sha256: str = Field(pattern=SHA256_PATTERN)
    confidentiality_status: Literal["public", "internal", "confidential"]
    usage_rights_status: Literal["confirmed", "unconfirmed"]
    original_path_policy: OriginalPathPolicy
    external_reference_id: str | None = None
    derived_artifact_references: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def no_absolute_reference(self) -> SourceAsset:
        values = (self.display_name, self.external_reference_id or "")
        if any(_looks_absolute_path(value) for value in values):
            raise ValueError("source asset output must not contain an absolute path")
        return self


class SourceBundleManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_bundle_schema_version: int = SOURCE_BUNDLE_SCHEMA_VERSION
    case_id: str = Field(pattern=CASE_ID_PATTERN)
    case_version: str = Field(pattern=VERSION_PATTERN)
    assets: tuple[SourceAsset, ...]
    bundle_fingerprint: str = Field(pattern=SHA256_PATTERN)
    creation_metadata: CreationMetadata

    @model_validator(mode="after")
    def stable_assets(self) -> SourceBundleManifest:
        ids = tuple(asset.asset_id for asset in self.assets)
        if ids != tuple(sorted(ids)):
            raise ValueError("source assets must be ordered by asset_id")
        if len(ids) != len(set(ids)):
            raise ValueError("source asset ids must be unique")
        return self


class CanonicalArtifactReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_type: str = "m6a_architectural_design_case"
    schema_version: int
    safe_reference_id: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    source_review_binding_fingerprint: str = Field(min_length=1)

    @field_validator("safe_reference_id")
    @classmethod
    def portable_reference(cls, value: str) -> str:
        if _looks_absolute_path(value) or "private_cases/" in value.replace("\\", "/").lower():
            raise ValueError("canonical artifact reference must be portable and non-private")
        return value


class ValidationSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: StrictBool
    check_count: int = Field(ge=0)
    failed_check_ids: tuple[str, ...] = ()
    source: str = Field(min_length=1)


class QualitySummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    assessment_version: str
    raw_score: float | None = Field(default=None, ge=0, le=100)
    effective_score: float | None = Field(default=None, ge=0, le=100)
    evidence_coverage: float | None = Field(default=None, ge=0, le=1)
    score_status: str
    category_scores: dict[str, float | None]
    blocking_finding_ids: tuple[str, ...]
    major_finding_ids: tuple[str, ...]
    limitations: tuple[str, ...]


class ProvenanceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance_type: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    synthetic_test_fixture: StrictBool = False
    limitations: tuple[str, ...] = ()

    @field_validator("source_reference")
    @classmethod
    def safe_source_reference(cls, value: str) -> str:
        if _looks_absolute_path(value) or "private_cases/" in value.replace("\\", "/").lower():
            raise ValueError("provenance source reference must not expose a private path")
        return value


class FeatureReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    relative_path: str = Field(min_length=1)
    fingerprint: str = Field(pattern=SHA256_PATTERN)
    feature_groups: tuple[str, ...]

    @field_validator("relative_path")
    @classmethod
    def relative_only(cls, value: str) -> str:
        if _looks_absolute_path(value) or ".." in value.replace("\\", "/").split("/"):
            raise ValueError("feature reference must be a safe relative path")
        return value.replace("\\", "/")


class ReviewDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: ReviewDecisionType
    reviewer_id: str = Field(min_length=1)
    review_date: str
    bound_fingerprint: str = Field(pattern=SHA256_PATTERN)
    template_use_approved: StrictBool
    rationale: str = Field(min_length=1)

    @field_validator("review_date")
    @classmethod
    def valid_review_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError("review_date must be an ISO date") from None
        return value

    @model_validator(mode="after")
    def explicit_template_use_only_on_approval(self) -> ReviewDecision:
        if self.decision is not ReviewDecisionType.APPROVED and self.template_use_approved:
            raise ValueError("template_use_approved may be true only for an approved decision")
        return self


class ProjectCasePackage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    package_schema_version: int = PROJECT_PACKAGE_SCHEMA_VERSION
    case_id: str = Field(pattern=CASE_ID_PATTERN)
    case_version: str = Field(pattern=VERSION_PATTERN)
    display_name: str = Field(min_length=1)
    case_role: CaseRole
    lifecycle_state: LifecycleState
    review_state: ReviewState
    project_type: str = Field(min_length=1)
    country: str = Field(min_length=1)
    city: str | None
    architectural_character: str | None
    confidentiality: Confidentiality
    usage_rights: UsageRights
    source_fingerprints: tuple[str, ...]
    source_bundle_fingerprint: str = Field(pattern=SHA256_PATTERN)
    canonical_case_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    canonical_artifact: CanonicalArtifactReference | None
    review_binding_fingerprint: str = Field(pattern=SHA256_PATTERN)
    review_decision: ReviewDecision | None
    template_eligible: StrictBool
    template_ineligibility_reasons: tuple[str, ...]
    validation_summary: ValidationSummary
    quality_summary: QualitySummary
    provenance: ProvenanceRecord
    extracted_features: FeatureReference | None
    creation_metadata: CreationMetadata
    supersedes_case_version: str | None = Field(default=None, pattern=VERSION_PATTERN)
    package_fingerprint: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def stable_source_fields(self) -> ProjectCasePackage:
        if self.source_fingerprints != tuple(sorted(set(self.source_fingerprints))):
            raise ValueError("source_fingerprints must be unique and sorted")
        if self.template_ineligibility_reasons != tuple(
            sorted(set(self.template_ineligibility_reasons))
        ):
            raise ValueError("template ineligibility reasons must be unique and sorted")
        if self.template_eligible and self.template_ineligibility_reasons:
            raise ValueError("eligible packages cannot carry ineligibility reasons")
        return self


class FeatureValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    feature_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    group: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    value: JsonValue
    unit: str
    status: FeatureStatus
    evidence_source: str = Field(min_length=1)
    review_status: str = Field(min_length=1)


class TemplateFeaturePackage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    feature_schema_version: int = FEATURE_PACKAGE_SCHEMA_VERSION
    case_id: str = Field(pattern=CASE_ID_PATTERN)
    case_version: str = Field(pattern=VERSION_PATTERN)
    canonical_case_fingerprint: str = Field(pattern=SHA256_PATTERN)
    provenance_type: str
    features: tuple[FeatureValue, ...]
    limitations: tuple[str, ...]
    feature_fingerprint: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def stable_features(self) -> TemplateFeaturePackage:
        ids = tuple(feature.feature_id for feature in self.features)
        if ids != tuple(sorted(ids)):
            raise ValueError("features must be ordered by feature_id")
        if len(ids) != len(set(ids)):
            raise ValueError("feature ids must be unique")
        return self


class RegistryEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    case_version: str
    is_current: StrictBool
    package_lifecycle_state: LifecycleState
    effective_lifecycle_state: LifecycleState
    case_role: CaseRole
    review_state: ReviewState
    approval_state: str
    template_eligible: StrictBool
    active_template: StrictBool
    synthetic_test_fixture: StrictBool
    source_fingerprints: tuple[str, ...]
    package_fingerprint: str = Field(pattern=SHA256_PATTERN)
    feature_package_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    created_at: str
    warnings: tuple[str, ...]


class LibraryRegistry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    registry_schema_version: int = REGISTRY_SCHEMA_VERSION
    generated_at: str
    entries: tuple[RegistryEntry, ...]

    _valid_generated_at = field_validator("generated_at")(_validate_iso_timestamp)

    @model_validator(mode="after")
    def stable_entries(self) -> LibraryRegistry:
        keys = tuple((entry.case_id, entry.case_version) for entry in self.entries)
        if keys != tuple(sorted(keys)):
            raise ValueError("registry entries must be ordered by case id and version")
        if len(keys) != len(set(keys)):
            raise ValueError("registry entries must be unique")
        return self


class ActiveTemplateEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    template_id: str
    case_id: str
    case_version: str
    project_type: Literal["residential_villa"]
    country: str
    city: str | None
    architectural_character: str
    package_fingerprint: str = Field(pattern=SHA256_PATTERN)
    review_binding_fingerprint: str = Field(pattern=SHA256_PATTERN)
    feature_package_fingerprint: str = Field(pattern=SHA256_PATTERN)
    feature_package_path: str
    approved_by: str
    approved_on: str
    synthetic_test_fixture: StrictBool
    test_data_disclaimer: str | None = None

    @model_validator(mode="after")
    def synthetic_entries_carry_the_verbatim_disclaimer(self) -> ActiveTemplateEntry:
        if self.synthetic_test_fixture:
            if self.test_data_disclaimer != SYNTHETIC_FIXTURE_DISCLAIMER:
                raise ValueError(
                    "synthetic test fixtures must carry the verbatim test-data disclaimer"
                )
        elif self.test_data_disclaimer is not None:
            raise ValueError("only synthetic test fixtures may carry the test-data disclaimer")
        return self


class ActiveTemplateIndex(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    active_index_schema_version: int = ACTIVE_INDEX_SCHEMA_VERSION
    generated_at: str
    entries: tuple[ActiveTemplateEntry, ...]

    _valid_generated_at = field_validator("generated_at")(_validate_iso_timestamp)

    @model_validator(mode="after")
    def stable_entries(self) -> ActiveTemplateIndex:
        keys = tuple((entry.case_id, entry.case_version) for entry in self.entries)
        if keys != tuple(sorted(keys)):
            raise ValueError("active template entries must be ordered")
        if len(keys) != len(set(keys)):
            raise ValueError("active template entries must be unique")
        return self


class LibraryValidationFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: str
    severity: Literal["error", "warning"]
    case_id: str | None = None
    case_version: str | None = None
    message: str


class LibraryValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    validation_schema_version: int = LIBRARY_VALIDATION_SCHEMA_VERSION
    generated_at: str
    passed: StrictBool
    findings: tuple[LibraryValidationFinding, ...]
    checked_case_versions: int = Field(ge=0)
    active_template_count: int = Field(ge=0)

    _valid_generated_at = field_validator("generated_at")(_validate_iso_timestamp)


class ArtifactRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    relative_path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("relative_path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        # No managed artifact path contains a colon; rejecting them all keeps
        # Windows drive-relative segments out of any join, wherever they sit.
        if _looks_absolute_path(value) or ":" in normalized or ".." in normalized.split("/"):
            raise ValueError("manifest artifact path must be a safe relative path")
        return normalized


class LibraryManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    library_manifest_schema_version: int = LIBRARY_MANIFEST_SCHEMA_VERSION
    generated_at: str
    artifacts: tuple[ArtifactRecord, ...]
    # Non-recursive integrity binding: SHA-256 over the canonical manifest
    # content EXCLUDING this field, so the controlled metadata (generated_at,
    # schema version) cannot be edited without detection.
    root_fingerprint: str = Field(pattern=SHA256_PATTERN)

    _valid_generated_at = field_validator("generated_at")(_validate_iso_timestamp)

    @model_validator(mode="after")
    def stable_artifacts(self) -> LibraryManifest:
        paths = tuple(record.relative_path for record in self.artifacts)
        if paths != tuple(sorted(paths)):
            raise ValueError("manifest artifacts must be ordered by relative path")
        if len(paths) != len(set(paths)):
            raise ValueError("manifest artifact paths must be unique")
        return self


SYNTHETIC_FIXTURE_DISCLAIMER = (
    "TEST DATA only. Not a real project, not a professional architectural design, "
    "and not evidence of regulatory, cultural, municipal, or permit approval."
)


class CorrectionType(str, Enum):
    ROOM_NAME = "room_name"
    ROOM_TYPE = "room_type"
    ZONE = "zone"
    ENTRANCE_CLASSIFICATION = "entrance_classification"
    DOOR_SPACE_CONNECTIVITY = "door_space_connectivity"
    ADJACENCY_RELATIONSHIP = "adjacency_relationship"
    ROUTE_INTERPRETATION = "route_interpretation"
    ACCEPTED_SOURCE_LIMITATION = "accepted_source_limitation"
    IGNORED_ELEMENT = "ignored_element"
    REVIEWER_COMMENT = "reviewer_comment"


class ArchitectCorrection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correction_type: CorrectionType
    target_id: str = Field(min_length=1)
    old_value: JsonValue
    new_value: JsonValue
    reviewer_id: str = Field(min_length=1)
    review_date: str
    reason: str = Field(min_length=1)
    source_evidence: str = Field(min_length=1)

    @field_validator("reviewer_id", "reason", "source_evidence")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value

    @field_validator("review_date")
    @classmethod
    def valid_review_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError("review_date must be an ISO date") from None
        return value


class ArchitectCorrectionsDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    corrections_schema_version: int = CORRECTIONS_SCHEMA_VERSION
    case_id: str = Field(pattern=CASE_ID_PATTERN)
    case_version: str = Field(pattern=VERSION_PATTERN)
    review_binding_fingerprint: str = Field(pattern=SHA256_PATTERN)
    corrections: tuple[ArchitectCorrection, ...]
    notes: str = ""


class ArchitectDecisionDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_schema_version: int = ARCHITECT_DECISION_SCHEMA_VERSION
    case_id: str = Field(pattern=CASE_ID_PATTERN)
    case_version: str = Field(pattern=VERSION_PATTERN)
    decision: Literal["requires_revision", "architect_reviewed", "rejected", "approved_template"]
    reviewer_id: str = Field(min_length=1)
    review_date: str
    bound_fingerprint: str = Field(pattern=SHA256_PATTERN)
    template_use_approved: StrictBool = False
    rationale: str = Field(min_length=1)

    @field_validator("reviewer_id", "rationale")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value

    @field_validator("review_date")
    @classmethod
    def valid_review_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError("review_date must be an ISO date") from None
        return value

    @model_validator(mode="after")
    def explicit_template_use_only_on_approval(self) -> ArchitectDecisionDocument:
        if self.decision != "approved_template" and self.template_use_approved:
            raise ValueError("template_use_approved may be true only for approved_template")
        return self


class ReviewPackageManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    review_package_schema_version: int = REVIEW_PACKAGE_SCHEMA_VERSION
    case_id: str = Field(pattern=CASE_ID_PATTERN)
    case_version: str = Field(pattern=VERSION_PATTERN)
    generated_at: str
    review_binding_fingerprint: str = Field(pattern=SHA256_PATTERN)
    artifacts: tuple[ArtifactRecord, ...]
    # Same non-recursive integrity binding as the library manifest.
    root_fingerprint: str = Field(pattern=SHA256_PATTERN)

    _valid_generated_at = field_validator("generated_at")(_validate_iso_timestamp)

    @model_validator(mode="after")
    def stable_artifacts(self) -> ReviewPackageManifest:
        paths = tuple(record.relative_path for record in self.artifacts)
        if paths != tuple(sorted(paths)):
            raise ValueError("review package artifacts must be ordered by relative path")
        if len(paths) != len(set(paths)):
            raise ValueError("review package artifact paths must be unique")
        return self


def _looks_absolute_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    # A second-character colon also covers Windows drive-RELATIVE forms such
    # as "C:file.json", which pathlib joins by replacing the base path.
    return normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":")
