"""M7.2 architect corrections: validation and corrected-version construction.

Corrections never modify source files or previously stored versions. They are
recorded as an overlay feature (``corrections.records``) in a NEW immutable
case version; the original extracted values remain verbatim, and the changed
feature fingerprint makes every prior review decision stale.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from saudi_plot_design.library.fingerprints import (
    calculate_feature_fingerprint,
    finalize_package,
)
from saudi_plot_design.library.models import (
    CORRECTIONS_SCHEMA_VERSION,
    ArchitectCorrectionsDocument,
    CaseRole,
    CorrectionType,
    CreationMetadata,
    FeatureStatus,
    FeatureValue,
    LifecycleState,
    ProjectCasePackage,
    ReviewState,
    SourceBundleManifest,
    TemplateFeaturePackage,
)
from saudi_plot_design.library.review import (
    CORRECTIONS_FEATURE_ID,
    correction_targets,
    feature_map,
)
from saudi_plot_design.library.validation import feature_relative_path
from saudi_plot_design.model import SpdInputError

CORRECTIONS_FEATURE_GROUP = "architect_corrections"

_TARGET_POOLS: dict[CorrectionType, tuple[str, ...]] = {
    CorrectionType.ROOM_NAME: ("rooms",),
    CorrectionType.ROOM_TYPE: ("rooms",),
    CorrectionType.ZONE: ("rooms",),
    CorrectionType.ENTRANCE_CLASSIFICATION: ("entrances",),
    CorrectionType.DOOR_SPACE_CONNECTIVITY: ("entrances", "openings"),
    CorrectionType.ADJACENCY_RELATIONSHIP: ("adjacency_pairs",),
    CorrectionType.ROUTE_INTERPRETATION: ("routes",),
    CorrectionType.ACCEPTED_SOURCE_LIMITATION: ("limitations",),
    CorrectionType.IGNORED_ELEMENT: ("rooms", "entrances", "openings"),
    CorrectionType.REVIEWER_COMMENT: (
        "rooms",
        "entrances",
        "openings",
        "adjacency_pairs",
        "routes",
        "case",
    ),
}
# Corrections whose old_value can be cross-checked against the stored data.
_VERIFIED_OLD_VALUES = {
    CorrectionType.ROOM_TYPE,
    CorrectionType.ZONE,
    CorrectionType.ENTRANCE_CLASSIFICATION,
}


def load_corrections_document(path: str | Path) -> ArchitectCorrectionsDocument:
    path = Path(path)
    if not path.is_file():
        raise SpdInputError(f"corrections file not found: {path.name or '<unnamed>'}")
    try:
        document = ArchitectCorrectionsDocument.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise SpdInputError(f"corrections file is unreadable: {exc}") from None
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        raise SpdInputError(
            f"corrections file failed schema validation: {location}: {first['msg']}"
        ) from None
    if document.corrections_schema_version != CORRECTIONS_SCHEMA_VERSION:
        raise SpdInputError(
            f"unsupported corrections schema version {document.corrections_schema_version}"
        )
    return document


def validate_corrections(
    document: ArchitectCorrectionsDocument,
    package: ProjectCasePackage,
    features: TemplateFeaturePackage | None,
) -> None:
    if (document.case_id, document.case_version) != (package.case_id, package.case_version):
        raise SpdInputError(
            "corrections document targets a different case/version: "
            f"{document.case_id}/{document.case_version}"
        )
    if document.review_binding_fingerprint != package.review_binding_fingerprint:
        raise SpdInputError(
            "corrections document is stale; it is bound to different case content "
            "than the current review_binding_fingerprint"
        )
    if not document.corrections:
        raise SpdInputError("corrections document contains no corrections")
    if features is None:
        raise SpdInputError(
            "case version has no extracted feature package; there is nothing to correct"
        )
    targets = correction_targets(package, features)
    seen: set[tuple[str, str]] = set()
    for correction in document.corrections:
        key = (correction.correction_type.value, correction.target_id)
        if key in seen:
            raise SpdInputError(
                "conflicting duplicate corrections for "
                f"{correction.correction_type.value}:{correction.target_id}"
            )
        seen.add(key)
        pools = _TARGET_POOLS[correction.correction_type]
        valid = {value for pool in pools for value in targets.get(pool, ())}
        if correction.target_id not in valid:
            raise SpdInputError(
                f"correction references an unknown canonical id: "
                f"{correction.correction_type.value}:{correction.target_id}"
            )
        _verify_old_value(correction, features)


def build_corrected_version(
    package: ProjectCasePackage,
    bundle: SourceBundleManifest,
    features: TemplateFeaturePackage,
    document: ArchitectCorrectionsDocument,
    *,
    new_version: str,
    creation_metadata: CreationMetadata,
) -> tuple[ProjectCasePackage, SourceBundleManifest, TemplateFeaturePackage]:
    """Build the corrected immutable version; the caller persists it."""
    new_records = [
        correction.model_dump(mode="json")
        for correction in sorted(
            document.corrections,
            key=lambda item: (item.review_date, item.correction_type.value, item.target_id),
        )
    ]
    existing = [
        feature for feature in features.features if feature.feature_id == CORRECTIONS_FEATURE_ID
    ]
    if existing:
        previous = list(existing[0].value or [])
        records = previous + new_records
    else:
        records = new_records
    corrections_feature = FeatureValue(
        feature_id=CORRECTIONS_FEATURE_ID,
        group=CORRECTIONS_FEATURE_GROUP,
        value=records,
        unit="correction_list",
        status=FeatureStatus.EXTRACTED,
        evidence_source="architect_review_corrections",
        review_status="architect_corrected",
    )
    retained = tuple(
        feature for feature in features.features if feature.feature_id != CORRECTIONS_FEATURE_ID
    )
    ordered = tuple(
        sorted((*retained, corrections_feature), key=lambda feature: feature.feature_id)
    )
    corrected_features = features.model_copy(
        update={
            "case_version": new_version,
            "features": ordered,
            "feature_fingerprint": "0" * 64,
        }
    )
    corrected_features = corrected_features.model_copy(
        update={"feature_fingerprint": calculate_feature_fingerprint(corrected_features)}
    )

    role = package.case_role
    if role is CaseRole.APPROVED_TEMPLATE:
        # Corrected content is no longer the approved content.
        role = CaseRole.RESIDENTIAL_VILLA_CANDIDATE
    feature_groups = tuple(package.extracted_features.feature_groups)
    if CORRECTIONS_FEATURE_GROUP not in feature_groups:
        feature_groups = (*feature_groups, CORRECTIONS_FEATURE_GROUP)
    feature_reference = package.extracted_features.model_copy(
        update={
            "relative_path": feature_relative_path(package.case_id, new_version),
            "fingerprint": corrected_features.feature_fingerprint,
            "feature_groups": feature_groups,
        }
    )
    corrected_package = finalize_package(
        package.model_copy(
            update={
                "case_version": new_version,
                "case_role": role,
                "lifecycle_state": LifecycleState.CORRECTED,
                "review_state": ReviewState.REQUIRES_REVIEW,
                "review_decision": None,
                "extracted_features": feature_reference,
                "creation_metadata": creation_metadata,
                "supersedes_case_version": package.case_version,
                "package_fingerprint": "0" * 64,
            }
        )
    )
    corrected_bundle = bundle.model_copy(
        update={"case_version": new_version, "creation_metadata": creation_metadata}
    )
    if corrected_package.review_binding_fingerprint == package.review_binding_fingerprint:
        raise SpdInputError(
            "corrections did not change the review binding; prior approvals would not go stale"
        )
    return corrected_package, corrected_bundle, corrected_features


def corrections_recorded(features: TemplateFeaturePackage | None) -> tuple[dict, ...]:
    if features is None:
        return ()
    values = feature_map(features)
    records = values.get(CORRECTIONS_FEATURE_ID) or ()
    return tuple(record for record in records if isinstance(record, dict))


def _verify_old_value(correction, features: TemplateFeaturePackage) -> None:
    if correction.correction_type not in _VERIFIED_OLD_VALUES:
        return
    values = feature_map(features)
    current = None
    if correction.correction_type is CorrectionType.ROOM_TYPE:
        for room in values.get("room_geometry.rooms") or ():
            if str(room["room_id"]) == correction.target_id:
                current = room["room_type"]
    elif correction.correction_type is CorrectionType.ZONE:
        for item in values.get("zoning.room_assignments") or ():
            if str(item["room_id"]) == correction.target_id:
                current = item["zone"]
    elif correction.correction_type is CorrectionType.ENTRANCE_CLASSIFICATION:
        for item in values.get("entrances.inventory") or ():
            if str(item["door_id"]) == correction.target_id:
                current = item["entrance_type"]
    # Original extracted values are never modified, so a later correction must
    # chain from the EFFECTIVE value established by the recorded correction
    # history (append order; the newest record wins), not from the original.
    for record in values.get(CORRECTIONS_FEATURE_ID) or ():
        if (
            isinstance(record, dict)
            and record.get("correction_type") == correction.correction_type.value
            and record.get("target_id") == correction.target_id
        ):
            current = record.get("new_value")
    if current != correction.old_value:
        raise SpdInputError(
            f"correction old_value does not match the stored value for "
            f"{correction.correction_type.value}:{correction.target_id}: stored "
            f"{json.dumps(current, ensure_ascii=False)}"
        )


__all__ = [
    "CORRECTIONS_FEATURE_GROUP",
    "CORRECTIONS_FEATURE_ID",
    "build_corrected_version",
    "corrections_recorded",
    "load_corrections_document",
    "validate_corrections",
]
