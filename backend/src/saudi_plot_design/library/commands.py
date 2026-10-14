"""M7.1 lifecycle operations and the ``spd library`` command surface."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from saudi_plot_design.cases.eligibility import evaluate_template_eligibility
from saudi_plot_design.cases.models import CASE_SCHEMA_VERSION, ArchitecturalDesignCase, CaseState
from saudi_plot_design.library.feature_extraction import (
    FEATURE_GROUPS,
    extract_case_features,
    quality_summary,
)
from saudi_plot_design.library.fingerprints import finalize_package
from saudi_plot_design.library.models import (
    CaseRole,
    CanonicalArtifactReference,
    Confidentiality,
    CreationMetadata,
    FeatureReference,
    LibraryValidationReport,
    LifecycleState,
    ProjectCasePackage,
    ProvenanceRecord,
    ReviewDecision,
    ReviewDecisionType,
    ReviewState,
    UsageRights,
    ValidationSummary,
)
from saudi_plot_design.library.registry import (
    chain_contains_cycle,
    derive_library_state,
    rebuild_library,
)
from saudi_plot_design.library.source_bundle import (
    catalog_source_asset,
    sha256_file,
    source_bundle_from_assets,
    source_bundle_from_m6a_case,
)
from saudi_plot_design.library.storage import (
    derive_library_manifest,
    iter_case_versions,
    json_bytes,
    load_case_version,
    verify_library_manifest,
    write_case_version,
)
from saudi_plot_design.library.validation import (
    approval_use_ineligibility_reasons,
    feature_relative_path,
)
from saudi_plot_design.model import SpdInputError

LIBRARY_NOTICE = (
    "M7.1 local library foundation: no template retrieval, ranking, adaptation, "
    "or design generation is performed."
)
_ZERO_HASH = "0" * 64
_M6A_SAFE_ARTIFACTS = frozenset(
    {
        "adjacency_graph.json",
        "architectural_case.json",
        "circulation_graph.json",
        "elements.json",
        "facade_openings.json",
        "metrics.json",
        "plan_preview.svg",
        "review_corrections_template.json",
        "spaces.json",
        "validation_report.json",
    }
)


def ingest_source_bundle(
    *,
    library_root: str | Path,
    asset_paths: tuple[str | Path, ...],
    case_id: str,
    case_version: str,
    display_name: str,
    project_type: str,
    country: str,
    city: str | None,
    architectural_character: str | None,
    creation_metadata: CreationMetadata,
    usage_rights: UsageRights,
    confidentiality: Confidentiality,
    supersedes_case_version: str | None = None,
    dry_run: bool = False,
) -> tuple[ProjectCasePackage, bool]:
    if not usage_rights.ingestion_permitted or not usage_rights.internal_review_permitted:
        raise SpdInputError(
            "source ingestion requires explicit ingestion and internal-review usage rights"
        )
    if not asset_paths:
        raise SpdInputError("at least one --asset is required")
    assets = tuple(
        catalog_source_asset(
            path,
            confidential=confidentiality.status == "confidential",
            usage_rights_confirmed=usage_rights.ingestion_permitted,
        )
        for path in asset_paths
    )
    bundle = source_bundle_from_assets(
        case_id=case_id,
        case_version=case_version,
        assets=assets,
        creation_metadata=creation_metadata,
    )
    package = ProjectCasePackage(
        case_id=case_id,
        case_version=case_version,
        display_name=(
            "Confidential project" if confidentiality.status == "confidential" else display_name
        ),
        case_role=CaseRole.SOURCE_PROJECT,
        lifecycle_state=LifecycleState.INGESTED,
        review_state=ReviewState.NOT_REVIEWED,
        project_type=project_type,
        country=country,
        city=city,
        architectural_character=architectural_character,
        confidentiality=confidentiality,
        usage_rights=usage_rights,
        source_fingerprints=tuple(sorted(asset.sha256 for asset in assets)),
        source_bundle_fingerprint=bundle.bundle_fingerprint,
        canonical_case_fingerprint=None,
        canonical_artifact=None,
        review_binding_fingerprint=_ZERO_HASH,
        review_decision=None,
        template_eligible=False,
        template_ineligibility_reasons=(
            "architect_review_required",
            "canonical_case_missing",
            "feature_package_missing",
        ),
        validation_summary=ValidationSummary(
            passed=True,
            check_count=len(assets),
            failed_check_ids=(),
            source="m7_source_bundle_catalogue",
        ),
        quality_summary=quality_summary(None),
        provenance=ProvenanceRecord(
            provenance_type="user_supplied_source_bundle",
            source_system="m7_source_bundle_catalogue",
            source_reference=f"source-bundle:{bundle.bundle_fingerprint}",
            statement="External source assets were fingerprinted in place and were not copied.",
            limitations=(
                "Cataloguing does not establish architectural quality or template suitability.",
            ),
        ),
        extracted_features=None,
        creation_metadata=creation_metadata,
        supersedes_case_version=supersedes_case_version,
        package_fingerprint=_ZERO_HASH,
    )
    package = finalize_package(package)
    created = write_case_version(library_root, package, bundle, None, dry_run=dry_run)
    # An idempotent replay must not rewrite healthy root artifacts, but a
    # retry after an interrupted first attempt must finish the rebuild.
    if not dry_run:
        if created:
            rebuild_library(library_root, generated_at=creation_metadata.created_at)
        else:
            _ensure_roots_current(library_root, generated_at=creation_metadata.created_at)
    return package, created


def import_m6a_artifacts(
    *,
    library_root: str | Path,
    artifact_root: str | Path,
    case_version: str,
    case_role: CaseRole,
    creation_metadata: CreationMetadata,
    template_use_permitted: bool,
    shareable_outputs_permitted: bool,
    rights_basis: str,
    synthetic_test_fixture: bool = False,
    supersedes_case_version: str | None = None,
    dry_run: bool = False,
) -> tuple[ProjectCasePackage, bool]:
    if case_role in {
        CaseRole.APPROVED_TEMPLATE,
        CaseRole.ARCHITECT_REVIEWED_REFERENCE,
        CaseRole.REJECTED,
        CaseRole.ARCHIVED,
    }:
        raise SpdInputError(
            "M6A import cannot infer review or approval; use a candidate, reference, stress-test, or excluded role"
        )
    artifact_root = Path(artifact_root)
    resolved_artifact_root = artifact_root.resolve(strict=False)
    if "private_cases" in {
        part.lower() for part in (*artifact_root.parts, *resolved_artifact_root.parts)
    }:
        raise SpdInputError(
            "import-case accepts safe generated M6A artifacts, not private source paths"
        )
    canonical_path = artifact_root / "architectural_case.json"
    manifest_path = artifact_root / "case_manifest.json"
    if not canonical_path.is_file() or not manifest_path.is_file():
        raise SpdInputError(
            "M6A safe artifact set requires architectural_case.json and case_manifest.json"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpdInputError(f"M6A safe artifact set failed schema validation: {exc}") from None
    if not isinstance(manifest, dict):
        raise SpdInputError("M6A case manifest must be a JSON object")

    files_sha256 = manifest.get("files_sha256")
    if not isinstance(files_sha256, dict) or set(files_sha256) != _M6A_SAFE_ARTIFACTS:
        raise SpdInputError("M6A files_sha256 keys do not match the required safe artifact set")
    canonical_name = "architectural_case.json"
    canonical_bytes = b""
    for name in sorted(_M6A_SAFE_ARTIFACTS):
        expected = files_sha256[name]
        if (
            not isinstance(expected, str)
            or len(expected) != 64
            or any(character not in "0123456789abcdef" for character in expected)
        ):
            raise SpdInputError(f"M6A safe artifact hash is invalid: {name}")
        path = artifact_root / name
        if not path.is_file():
            raise SpdInputError(f"M6A safe artifact is missing: {name}")
        # The canonical artifact is read exactly once; the verified bytes are
        # the same bytes that get parsed and fingerprinted below, so a swap
        # between check and use cannot import unverified content.
        if name == canonical_name:
            canonical_bytes = path.read_bytes()
            actual = hashlib.sha256(canonical_bytes).hexdigest()
        else:
            actual = sha256_file(path)
        if actual != expected:
            raise SpdInputError(f"M6A safe artifact hash mismatch: {name}")

    try:
        case = ArchitecturalDesignCase.model_validate_json(canonical_bytes)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise SpdInputError(f"M6A safe artifact set failed schema validation: {exc}") from None
    if manifest.get("case_id") != case.case_id:
        raise SpdInputError("M6A case manifest and canonical case id do not match")
    # A hash-consistent artifact set with a different schema version would be
    # interpreted with the wrong feature and eligibility semantics.
    if case.schema_version != CASE_SCHEMA_VERSION:
        raise SpdInputError(
            f"unsupported M6A case schema version {case.schema_version}; "
            f"this M7.1 import supports schema version {CASE_SCHEMA_VERSION}"
        )
    if manifest.get("schema_version") != case.schema_version:
        raise SpdInputError("M6A case manifest and canonical schema versions do not match")
    if not case.metadata.usage_rights_confirmed:
        raise SpdInputError("M6A case usage rights are not confirmed")

    canonical_fingerprint = hashlib.sha256(canonical_bytes).hexdigest()
    eligibility = evaluate_template_eligibility(case)
    bundle = source_bundle_from_m6a_case(
        case,
        case_version=case_version,
        creation_metadata=creation_metadata,
    )
    features = extract_case_features(
        case,
        case_version=case_version,
        canonical_case_fingerprint=canonical_fingerprint,
    )
    validation = case.validation
    if validation is None:
        raise SpdInputError("M6A canonical case has no validation report")
    confidentiality = Confidentiality(
        status="confidential" if case.metadata.confidential else "internal",
        # Anonymization is only performed when M6A required it; a
        # non-confidential case keeps its identifiers and is NOT anonymized.
        anonymized=case.metadata.anonymization_required,
        shareable_outputs_permitted=shareable_outputs_permitted,
    )
    usage_rights = UsageRights(
        ingestion_permitted=True,
        internal_review_permitted=True,
        template_use_permitted=template_use_permitted,
        template_use_revoked=False,
        rights_basis=rights_basis,
    )
    lifecycle = (
        LifecycleState.CORRECTED
        if case.state is CaseState.CORRECTED
        else LifecycleState.REQUIRES_REVIEW
    )
    package = ProjectCasePackage(
        case_id=case.case_id,
        case_version=case_version,
        display_name=("Confidential project" if case.metadata.confidential else case.case_id),
        case_role=case_role,
        lifecycle_state=lifecycle,
        review_state=ReviewState.REQUIRES_REVIEW,
        project_type=case.metadata.project_type,
        country=case.metadata.country,
        city=None if case.metadata.anonymization_required else case.metadata.city,
        architectural_character=case.metadata.architectural_character,
        confidentiality=confidentiality,
        usage_rights=usage_rights,
        source_fingerprints=(case.provenance.source_fingerprint,),
        source_bundle_fingerprint=bundle.bundle_fingerprint,
        canonical_case_fingerprint=canonical_fingerprint,
        canonical_artifact=CanonicalArtifactReference(
            schema_version=case.schema_version,
            safe_reference_id=f"m6a-safe-artifact:{canonical_fingerprint}",
            sha256=canonical_fingerprint,
            source_review_binding_fingerprint=case.provenance.review_binding_fingerprint,
        ),
        review_binding_fingerprint=_ZERO_HASH,
        review_decision=None,
        template_eligible=eligibility.template_eligible,
        template_ineligibility_reasons=tuple(sorted(eligibility.template_ineligibility_reasons)),
        validation_summary=ValidationSummary(
            passed=validation.passed,
            check_count=len(validation.checks),
            failed_check_ids=tuple(sorted(check.id for check in validation.failures())),
            source="m6a_validation_report",
        ),
        quality_summary=quality_summary(None),
        provenance=ProvenanceRecord(
            provenance_type=(
                "synthetic_test_fixture" if synthetic_test_fixture else "m6a_safe_artifact_import"
            ),
            source_system="saudi_plot_design.cases",
            source_reference=f"m6a-safe-artifact:{canonical_fingerprint}",
            statement=(
                "Synthetic test fixture only; not a real project or professional design."
                if synthetic_test_fixture
                else "The M7 package references the verified M6A canonical artifact and source "
                "fingerprint; no source model was copied."
            ),
            synthetic_test_fixture=synthetic_test_fixture,
            limitations=(
                "M6A review state does not create M7 approval.",
                "M6A geometry omissions remain omissions in extracted features.",
            ),
        ),
        extracted_features=FeatureReference(
            relative_path=feature_relative_path(case.case_id, case_version),
            fingerprint=features.feature_fingerprint,
            feature_groups=FEATURE_GROUPS,
        ),
        creation_metadata=creation_metadata,
        supersedes_case_version=supersedes_case_version,
        package_fingerprint=_ZERO_HASH,
    )
    package = finalize_package(package)
    created = write_case_version(library_root, package, bundle, features, dry_run=dry_run)
    # An idempotent replay must not rewrite healthy root artifacts, but a
    # retry after an interrupted first attempt must finish the rebuild.
    if not dry_run:
        if created:
            rebuild_library(library_root, generated_at=creation_metadata.created_at)
        else:
            _ensure_roots_current(library_root, generated_at=creation_metadata.created_at)
    return package, created


def apply_review(
    *,
    library_root: str | Path,
    case_id: str,
    from_version: str,
    new_version: str,
    decision_type: ReviewDecisionType,
    reviewer_id: str,
    review_date: str,
    bound_fingerprint: str,
    rationale: str,
    template_use_approved: bool,
    creation_metadata: CreationMetadata,
    dry_run: bool = False,
) -> tuple[ProjectCasePackage, bool]:
    package, bundle, features = load_case_version(library_root, case_id, from_version)
    if bound_fingerprint != package.review_binding_fingerprint:
        raise SpdInputError(
            "review decision fingerprint is stale; review the current package and bind to its review_binding_fingerprint"
        )
    if decision_type is ReviewDecisionType.APPROVED:
        # The same decision-independent gates as the active index, so a case
        # that cannot become an active template cannot be approved as one.
        provisional_reasons = list(approval_use_ineligibility_reasons(package, bundle, features))
        if not template_use_approved:
            provisional_reasons.append("template_use_not_explicitly_approved")
        if provisional_reasons:
            raise SpdInputError(
                "approved template prohibited: "
                + json.dumps(sorted(set(provisional_reasons)), separators=(",", ":"))
            )
        role = CaseRole.APPROVED_TEMPLATE
        lifecycle = LifecycleState.APPROVED
        review_state = ReviewState.APPROVED
    elif decision_type is ReviewDecisionType.ARCHITECT_REVIEWED:
        role = (
            CaseRole.ARCHITECT_REVIEWED_REFERENCE
            if package.case_role is CaseRole.RESIDENTIAL_VILLA_CANDIDATE
            else package.case_role
        )
        lifecycle = LifecycleState.ARCHITECT_REVIEWED
        review_state = ReviewState.ARCHITECT_REVIEWED
    elif decision_type is ReviewDecisionType.REJECTED:
        role = CaseRole.REJECTED
        lifecycle = LifecycleState.REJECTED
        review_state = ReviewState.REJECTED
    elif decision_type is ReviewDecisionType.REQUIRES_REVISION:
        # The decision is recorded, but the case explicitly remains awaiting
        # revision and re-review; role is unchanged.
        role = package.case_role
        lifecycle = LifecycleState.REQUIRES_REVIEW
        review_state = ReviewState.REQUIRES_REVIEW
    else:
        role = CaseRole.EXCLUDED
        lifecycle = LifecycleState.EXCLUDED
        review_state = ReviewState.REVOKED

    updated_rights = (
        package.usage_rights.model_copy(update={"template_use_revoked": True})
        if decision_type is ReviewDecisionType.REVOKED
        else package.usage_rights
    )

    decision = ReviewDecision(
        decision=decision_type,
        reviewer_id=reviewer_id,
        review_date=review_date,
        bound_fingerprint=bound_fingerprint,
        template_use_approved=template_use_approved,
        rationale=rationale,
    )
    feature_reference = (
        package.extracted_features.model_copy(
            update={"relative_path": feature_relative_path(case_id, new_version)}
        )
        if package.extracted_features
        else None
    )
    updated = package.model_copy(
        update={
            "case_version": new_version,
            "case_role": role,
            "lifecycle_state": lifecycle,
            "review_state": review_state,
            "review_decision": decision,
            "usage_rights": updated_rights,
            "extracted_features": feature_reference,
            "creation_metadata": creation_metadata,
            "supersedes_case_version": from_version,
            "package_fingerprint": _ZERO_HASH,
        }
    )
    updated = finalize_package(updated)
    # Role/lifecycle/review do not alter reviewed content; a different binding
    # here would mean the transition unexpectedly changed evidence.
    if updated.review_binding_fingerprint != bound_fingerprint:
        raise SpdInputError("review transition changed bound case evidence unexpectedly")
    new_bundle = bundle.model_copy(
        update={"case_version": new_version, "creation_metadata": creation_metadata}
    )
    new_features = features.model_copy(update={"case_version": new_version}) if features else None
    created = write_case_version(library_root, updated, new_bundle, new_features, dry_run=dry_run)
    # Healthy roots stay untouched on replay; interrupted rebuilds resume.
    if not dry_run:
        if created:
            rebuild_library(library_root, generated_at=creation_metadata.created_at)
        else:
            _ensure_roots_current(library_root, generated_at=creation_metadata.created_at)
    return updated, created


def archive_case(
    *,
    library_root: str | Path,
    case_id: str,
    from_version: str,
    new_version: str,
    creation_metadata: CreationMetadata,
) -> tuple[ProjectCasePackage, bool]:
    package, bundle, features = load_case_version(library_root, case_id, from_version)
    feature_reference = (
        package.extracted_features.model_copy(
            update={"relative_path": feature_relative_path(case_id, new_version)}
        )
        if package.extracted_features
        else None
    )
    updated = finalize_package(
        package.model_copy(
            update={
                "case_version": new_version,
                "case_role": CaseRole.ARCHIVED,
                "lifecycle_state": LifecycleState.ARCHIVED,
                "extracted_features": feature_reference,
                "creation_metadata": creation_metadata,
                "supersedes_case_version": from_version,
                "package_fingerprint": _ZERO_HASH,
            }
        )
    )
    new_bundle = bundle.model_copy(
        update={"case_version": new_version, "creation_metadata": creation_metadata}
    )
    new_features = features.model_copy(update={"case_version": new_version}) if features else None
    created = write_case_version(library_root, updated, new_bundle, new_features)
    # Healthy roots stay untouched on replay; interrupted rebuilds resume.
    if created:
        rebuild_library(library_root, generated_at=creation_metadata.created_at)
    else:
        _ensure_roots_current(library_root, generated_at=creation_metadata.created_at)
    return updated, created


def apply_architect_corrections(
    *,
    library_root: str | Path,
    corrections_path: str | Path,
    case_id: str,
    from_version: str,
    new_version: str,
    creation_metadata: CreationMetadata,
    dry_run: bool = False,
) -> tuple[ProjectCasePackage, bool]:
    """Validate an architect corrections document and persist a new version."""
    from saudi_plot_design.library.corrections import (
        build_corrected_version,
        load_corrections_document,
        validate_corrections,
    )

    document = load_corrections_document(corrections_path)
    package, bundle, features = load_case_version(library_root, case_id, from_version)
    validate_corrections(document, package, features)
    assert features is not None
    corrected_package, corrected_bundle, corrected_features = build_corrected_version(
        package,
        bundle,
        features,
        document,
        new_version=new_version,
        creation_metadata=creation_metadata,
    )
    created = write_case_version(
        library_root, corrected_package, corrected_bundle, corrected_features, dry_run=dry_run
    )
    if not dry_run:
        if created:
            rebuild_library(library_root, generated_at=creation_metadata.created_at)
        else:
            _ensure_roots_current(library_root, generated_at=creation_metadata.created_at)
    return corrected_package, created


def apply_architect_decision(
    *,
    library_root: str | Path,
    decision_path: str | Path,
    case_id: str,
    from_version: str,
    new_version: str,
    creation_metadata: CreationMetadata,
    dry_run: bool = False,
) -> tuple[ProjectCasePackage, bool]:
    """Apply a filled architect decision document through the review gates."""
    from saudi_plot_design.library.models import (
        ARCHITECT_DECISION_SCHEMA_VERSION,
        ArchitectDecisionDocument,
    )

    path = Path(decision_path)
    if not path.is_file():
        raise SpdInputError(f"decision file not found: {path.name or '<unnamed>'}")
    try:
        document = ArchitectDecisionDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise SpdInputError(f"decision file is unreadable: {exc}") from None
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        raise SpdInputError(
            f"decision file failed schema validation: {location}: {first['msg']}"
        ) from None
    if document.decision_schema_version != ARCHITECT_DECISION_SCHEMA_VERSION:
        raise SpdInputError(
            f"unsupported decision schema version {document.decision_schema_version}"
        )
    if (document.case_id, document.case_version) != (case_id, from_version):
        raise SpdInputError(
            "decision document targets a different case/version: "
            f"{document.case_id}/{document.case_version}"
        )
    if not document.reviewer_id.strip():
        raise SpdInputError("decision reviewer identity must not be blank")
    decision_type = {
        "requires_revision": ReviewDecisionType.REQUIRES_REVISION,
        "architect_reviewed": ReviewDecisionType.ARCHITECT_REVIEWED,
        "rejected": ReviewDecisionType.REJECTED,
        "approved_template": ReviewDecisionType.APPROVED,
    }[document.decision]
    return apply_review(
        library_root=library_root,
        case_id=case_id,
        from_version=from_version,
        new_version=new_version,
        decision_type=decision_type,
        reviewer_id=document.reviewer_id,
        review_date=document.review_date,
        bound_fingerprint=document.bound_fingerprint,
        rationale=document.rationale,
        template_use_approved=document.template_use_approved,
        creation_metadata=creation_metadata,
        dry_run=dry_run,
    )


def review_status_payload(library_root: str | Path, case_id: str, case_version: str) -> dict:
    from saudi_plot_design.library.corrections import corrections_recorded

    package, _bundle, features = load_case_version(library_root, case_id, case_version)
    registry, index, _validation = derive_library_state(
        library_root, generated_at=_stored_generated_at(library_root)
    )
    entry = next(
        (
            item
            for item in registry.entries
            if (item.case_id, item.case_version) == (case_id, case_version)
        ),
        None,
    )
    active_keys = {(item.case_id, item.case_version) for item in index.entries}
    decision = package.review_decision
    return {
        "notice": LIBRARY_NOTICE,
        "case_id": package.case_id,
        "case_version": package.case_version,
        "case_role": package.case_role.value,
        "lifecycle_state": package.lifecycle_state.value,
        "effective_lifecycle_state": (
            entry.effective_lifecycle_state.value if entry else "unknown"
        ),
        "review_state": package.review_state.value,
        "is_current": bool(entry and entry.is_current),
        "active_template": (case_id, case_version) in active_keys,
        "template_eligible": package.template_eligible,
        "review_binding_fingerprint": package.review_binding_fingerprint,
        "synthetic_test_fixture": package.provenance.synthetic_test_fixture,
        "corrections_recorded": len(corrections_recorded(features)),
        "decision": (
            {
                "decision": decision.decision.value,
                "reviewer_id": decision.reviewer_id,
                "review_date": decision.review_date,
                "template_use_approved": decision.template_use_approved,
            }
            if decision
            else None
        ),
    }


def add_library_subparser(subparsers) -> None:
    library = subparsers.add_parser(
        "library",
        help="manage the deterministic local project/template library (M7.1)",
        description=LIBRARY_NOTICE,
    )
    commands = library.add_subparsers(dest="library_command", required=True)

    ingest = commands.add_parser("ingest", help="catalog external source assets without copying")
    _add_root(ingest)
    ingest.add_argument("--asset", action="append", type=Path, required=True)
    _add_project_identity(ingest)
    _add_rights(ingest)
    _add_creation(ingest)
    ingest.add_argument("--supersedes")
    ingest.add_argument("--dry-run", action="store_true")
    _add_json(ingest)

    import_case = commands.add_parser("import-case", help="import a safe M6A artifact set")
    _add_root(import_case)
    import_case.add_argument("--artifacts", type=Path, required=True)
    import_case.add_argument("--case-version", required=True)
    import_case.add_argument(
        "--case-role",
        choices=tuple(role.value for role in CaseRole),
        required=True,
    )
    import_case.add_argument("--template-use-permitted", action="store_true")
    import_case.add_argument("--shareable-outputs-permitted", action="store_true")
    import_case.add_argument("--rights-basis", required=True)
    import_case.add_argument("--synthetic-test-fixture", action="store_true")
    import_case.add_argument("--supersedes")
    import_case.add_argument("--dry-run", action="store_true")
    _add_creation(import_case)
    _add_json(import_case)

    list_command = commands.add_parser("list", help="list registry entries")
    _add_root(list_command)
    _add_json(list_command)

    show = commands.add_parser("show", help="show one case/version package")
    _add_root(show)
    show.add_argument("--case-id", required=True)
    show.add_argument("--case-version")
    _add_json(show)

    review = commands.add_parser("apply-review", help="attach a fingerprint-bound review")
    _add_root(review)
    review.add_argument("--case-id", required=True)
    review.add_argument("--from-version", required=True)
    review.add_argument("--new-version", required=True)
    review.add_argument(
        "--decision",
        choices=tuple(decision.value for decision in ReviewDecisionType),
        required=True,
    )
    review.add_argument("--reviewed-by", required=True)
    review.add_argument("--review-date", required=True)
    review.add_argument("--bound-fingerprint", required=True)
    review.add_argument("--rationale", required=True)
    review.add_argument("--approve-template-use", action="store_true")
    _add_creation(review)
    _add_json(review)

    archive = commands.add_parser("archive", help="archive via a new immutable version")
    _add_root(archive)
    archive.add_argument("--case-id", required=True)
    archive.add_argument("--from-version", required=True)
    archive.add_argument("--new-version", required=True)
    _add_creation(archive)
    _add_json(archive)

    rebuild = commands.add_parser("rebuild-index", help="rebuild registry and active index")
    _add_root(rebuild)
    rebuild.add_argument("--generated-at", required=True)
    _add_json(rebuild)

    validate = commands.add_parser("validate", help="verify schemas, indexes, hashes, and sizes")
    _add_root(validate)
    _add_json(validate)

    prepare = commands.add_parser(
        "prepare-review", help="render the deterministic architect-review package"
    )
    _add_root(prepare)
    prepare.add_argument("--case-id", required=True)
    prepare.add_argument("--case-version")
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--dry-run", action="store_true")
    _add_json(prepare)

    validate_package = commands.add_parser(
        "validate-review-package", help="verify a review package's manifest and hashes"
    )
    validate_package.add_argument("--package", type=Path, required=True)
    _add_json(validate_package)

    corrections = commands.add_parser(
        "apply-corrections", help="apply an architect corrections document as a new version"
    )
    _add_root(corrections)
    corrections.add_argument("--case-id", required=True)
    corrections.add_argument("--from-version", required=True)
    corrections.add_argument("--new-version", required=True)
    corrections.add_argument("--corrections", type=Path, required=True)
    corrections.add_argument("--dry-run", action="store_true")
    _add_creation(corrections)
    _add_json(corrections)

    decision = commands.add_parser(
        "apply-architect-decision", help="apply a filled architect decision document"
    )
    _add_root(decision)
    decision.add_argument("--case-id", required=True)
    decision.add_argument("--from-version", required=True)
    decision.add_argument("--new-version", required=True)
    decision.add_argument("--decision-file", type=Path, required=True)
    decision.add_argument("--dry-run", action="store_true")
    _add_creation(decision)
    _add_json(decision)

    status = commands.add_parser(
        "show-review-status", help="show the review status of a case version"
    )
    _add_root(status)
    status.add_argument("--case-id", required=True)
    status.add_argument("--case-version")
    _add_json(status)


def run_library_command(args: argparse.Namespace) -> int:
    command = args.library_command
    if command == "ingest":
        package, created = ingest_source_bundle(
            library_root=args.library_root,
            asset_paths=tuple(args.asset),
            case_id=args.case_id,
            case_version=args.case_version,
            display_name=args.display_name,
            project_type=args.project_type,
            country=args.country,
            city=args.city,
            architectural_character=args.architectural_character,
            creation_metadata=_creation(args),
            usage_rights=_rights(args),
            confidentiality=_confidentiality(args),
            supersedes_case_version=args.supersedes,
            dry_run=args.dry_run,
        )
        return _emit_operation(args, package, created, args.dry_run)
    if command == "import-case":
        package, created = import_m6a_artifacts(
            library_root=args.library_root,
            artifact_root=args.artifacts,
            case_version=args.case_version,
            case_role=CaseRole(args.case_role),
            creation_metadata=_creation(args),
            template_use_permitted=args.template_use_permitted,
            shareable_outputs_permitted=args.shareable_outputs_permitted,
            rights_basis=args.rights_basis,
            synthetic_test_fixture=args.synthetic_test_fixture,
            supersedes_case_version=args.supersedes,
            dry_run=args.dry_run,
        )
        return _emit_operation(args, package, created, args.dry_run)
    if command == "list":
        # Derive registry state so a superseded historical version can never
        # masquerade as the current or active approved template.
        registry, index, validation = derive_library_state(
            args.library_root, generated_at=_stored_generated_at(args.library_root)
        )
        active_keys = {(entry.case_id, entry.case_version) for entry in index.entries}
        entries = [
            {
                "case_id": entry.case_id,
                "case_version": entry.case_version,
                "case_role": entry.case_role.value,
                "package_lifecycle_state": entry.package_lifecycle_state.value,
                "effective_lifecycle_state": entry.effective_lifecycle_state.value,
                "review_state": entry.review_state.value,
                "template_eligible": entry.template_eligible,
                "is_current": entry.is_current,
                "superseded": not entry.is_current,
                "active_template": (entry.case_id, entry.case_version) in active_keys,
            }
            for entry in registry.entries
        ]
        return _emit(
            args,
            {
                "notice": LIBRARY_NOTICE,
                "validation_passed": validation.passed,
                "entries": entries,
            },
        )
    if command == "show":
        version = args.case_version or _current_version(args.library_root, args.case_id)
        package, _, _ = load_case_version(args.library_root, args.case_id, version)
        return _emit(args, package.model_dump(mode="json"))
    if command == "apply-review":
        package, created = apply_review(
            library_root=args.library_root,
            case_id=args.case_id,
            from_version=args.from_version,
            new_version=args.new_version,
            decision_type=ReviewDecisionType(args.decision),
            reviewer_id=args.reviewed_by,
            review_date=args.review_date,
            bound_fingerprint=args.bound_fingerprint,
            rationale=args.rationale,
            template_use_approved=args.approve_template_use,
            creation_metadata=_creation(args),
        )
        return _emit_operation(args, package, created, False)
    if command == "archive":
        package, created = archive_case(
            library_root=args.library_root,
            case_id=args.case_id,
            from_version=args.from_version,
            new_version=args.new_version,
            creation_metadata=_creation(args),
        )
        return _emit_operation(args, package, created, False)
    if command == "rebuild-index":
        registry, index, validation, manifest = rebuild_library(
            args.library_root, generated_at=args.generated_at
        )
        _emit(
            args,
            {
                "notice": LIBRARY_NOTICE,
                "case_versions": len(registry.entries),
                "active_templates": len(index.entries),
                "validation_passed": validation.passed,
                "manifest_artifacts": len(manifest.artifacts),
            },
        )
        return 0 if validation.passed else 3
    if command == "validate":
        # Recompute the whole library state so version-chain, active-index,
        # and TEST-OFFICE findings are enforced, not just per-package checks.
        _registry, _index, validation, stale_root_artifacts = _derive_state_and_stale_roots(
            args.library_root
        )
        errors = [
            finding.model_dump(mode="json")
            for finding in validation.findings
            if finding.severity == "error"
        ]
        manifest_errors = list(verify_library_manifest(args.library_root))
        payload = {
            "notice": LIBRARY_NOTICE,
            "passed": not errors and not stale_root_artifacts and not manifest_errors,
            "library_errors": errors,
            "stale_root_artifacts": stale_root_artifacts,
            "manifest_errors": manifest_errors,
        }
        _emit(args, payload)
        return 0 if payload["passed"] else 3
    if command == "prepare-review":
        from saudi_plot_design.library.review import prepare_review_package

        version = args.case_version or _current_version(args.library_root, args.case_id)
        manifest = prepare_review_package(
            args.library_root,
            args.out,
            case_id=args.case_id,
            case_version=version,
            dry_run=args.dry_run,
        )
        return _emit(
            args,
            {
                "notice": LIBRARY_NOTICE,
                "case_id": manifest.case_id,
                "case_version": manifest.case_version,
                "generated_at": manifest.generated_at,
                "review_binding_fingerprint": manifest.review_binding_fingerprint,
                "artifact_count": len(manifest.artifacts) + 1,
                "disposition": "dry_run" if args.dry_run else "written",
            },
        )
    if command == "validate-review-package":
        from saudi_plot_design.library.review import validate_review_package

        errors = list(validate_review_package(args.package))
        payload = {
            "notice": LIBRARY_NOTICE,
            "passed": not errors,
            "errors": errors,
        }
        _emit(args, payload)
        return 0 if payload["passed"] else 3
    if command == "apply-corrections":
        package, created = apply_architect_corrections(
            library_root=args.library_root,
            corrections_path=args.corrections,
            case_id=args.case_id,
            from_version=args.from_version,
            new_version=args.new_version,
            creation_metadata=_creation(args),
            dry_run=args.dry_run,
        )
        return _emit_operation(args, package, created, args.dry_run)
    if command == "apply-architect-decision":
        package, created = apply_architect_decision(
            library_root=args.library_root,
            decision_path=args.decision_file,
            case_id=args.case_id,
            from_version=args.from_version,
            new_version=args.new_version,
            creation_metadata=_creation(args),
            dry_run=args.dry_run,
        )
        return _emit_operation(args, package, created, args.dry_run)
    if command == "show-review-status":
        version = args.case_version or _current_version(args.library_root, args.case_id)
        return _emit(args, review_status_payload(args.library_root, args.case_id, version))
    raise SpdInputError(f"unsupported library command: {command}")


def _add_root(parser) -> None:
    parser.add_argument("--library-root", type=Path, required=True)


def _add_json(parser) -> None:
    parser.add_argument("--json", action="store_true", dest="json_output")


def _add_creation(parser) -> None:
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--created-by", required=True)


def _add_project_identity(parser) -> None:
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--case-version", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--project-type", required=True)
    parser.add_argument("--country", required=True)
    parser.add_argument("--city")
    parser.add_argument("--architectural-character")


def _add_rights(parser) -> None:
    parser.add_argument("--usage-rights-confirmed", action="store_true", required=True)
    parser.add_argument("--internal-review-permitted", action="store_true", required=True)
    parser.add_argument("--template-use-permitted", action="store_true")
    parser.add_argument("--rights-basis", required=True)
    parser.add_argument("--confidential", action="store_true")
    parser.add_argument("--shareable-outputs-permitted", action="store_true")


def _creation(args) -> CreationMetadata:
    return CreationMetadata(
        created_at=args.created_at,
        created_by=args.created_by,
        source="spd_library_cli",
    )


def _rights(args) -> UsageRights:
    return UsageRights(
        ingestion_permitted=args.usage_rights_confirmed,
        internal_review_permitted=args.internal_review_permitted,
        template_use_permitted=args.template_use_permitted,
        template_use_revoked=False,
        rights_basis=args.rights_basis,
    )


def _confidentiality(args) -> Confidentiality:
    return Confidentiality(
        status="confidential" if args.confidential else "internal",
        anonymized=args.confidential,
        shareable_outputs_permitted=args.shareable_outputs_permitted,
    )


def _derive_state_and_stale_roots(library_root):
    """Derive registry/index/validation and list stale or missing roots."""
    registry, index, validation = derive_library_state(
        library_root, generated_at=_stored_generated_at(library_root)
    )
    stale: list[str] = []
    for name, model in (
        ("library_registry.json", registry),
        ("active_template_index.json", index),
        ("validation_report.json", validation),
    ):
        path = Path(library_root) / name
        if not path.is_file():
            stale.append(f"missing root artifact: {name}")
        elif path.read_bytes() != json_bytes(model.model_dump(mode="json")):
            stale.append(f"stale root artifact: {name}")
    # The manifest cannot hash itself, so rederive the manifest expected for
    # the controlled timestamp and disk state; editing only its generated_at
    # (or any metadata) is a stale root artifact.
    manifest_path = Path(library_root) / "library_manifest.json"
    if not manifest_path.is_file():
        stale.append("missing root artifact: library_manifest.json")
    else:
        expected_manifest = derive_library_manifest(
            library_root, generated_at=_stored_generated_at(library_root)
        )
        if manifest_path.read_bytes() != json_bytes(expected_manifest.model_dump(mode="json")):
            stale.append("stale root artifact: library_manifest.json")
    return registry, index, validation, stale


def _ensure_roots_current(library_root, *, generated_at: str) -> None:
    """Repair roots after an idempotent replay without touching healthy ones.

    A crash between the immutable version write and the root rebuild leaves
    stale roots; the exact retry gets ``created=False`` and must finish the
    interrupted rebuild instead of silently reporting success. A root-only
    repair triggered by an OLD replay must not roll healthy controlled
    timestamps backward, so the newer of the stored root timestamp and the
    replay timestamp is used.
    """
    registry, _, _, stale = _derive_state_and_stale_roots(library_root)
    if not stale:
        return
    # The ONLY automatic repair is completing THIS operation's interrupted
    # rebuild, which is unambiguous exactly when the replay is at least as
    # new as every controlled event on record: stored version creation
    # metadata and every parseable root timestamp claim. Untrusted claims
    # never set the rebuild timestamp, but a NEWER claim - even a tampered
    # one - vetoes auto-repair so the evidence is preserved for validate and
    # an explicit rebuild, never rolled back or laundered.
    replay = _comparable_timestamp(generated_at)
    veto_claims = [
        *(entry.created_at for entry in registry.entries),
        *_parseable_root_timestamps(library_root),
    ]
    if all(replay >= _comparable_timestamp(value) for value in veto_claims):
        rebuild_library(library_root, generated_at=generated_at)
        return
    raise SpdInputError(
        "library root artifacts are stale or inconsistent, and this replayed "
        "operation predates newer controlled library state; repair explicitly "
        "with 'spd library rebuild-index --generated-at <timestamp>'"
    )


def _comparable_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _parseable_root_timestamps(library_root) -> list[str]:
    """Every parseable generated_at claim across ALL five root artifacts."""
    root = Path(library_root)
    claims: list[str] = []
    for name in (
        "library_registry.json",
        "active_template_index.json",
        "validation_report.json",
        "library_manifest.json",
    ):
        claimed = _read_stored_generated_at(root / name)
        if claimed is not None:
            claims.append(claimed)
    summary_claim = _read_summary_generated_at(root / "library_summary.md")
    if summary_claim is not None:
        claims.append(summary_claim)
    return claims


def _read_summary_generated_at(path: Path) -> str | None:
    """Parse the summary's controlled timestamp line; None when unusable."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = re.search(r"Generated at \(controlled metadata\): `([^`]+)`", text)
    if match is None:
        return None
    value = match.group(1)
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def _read_stored_generated_at(path: Path) -> str | None:
    """Best-effort generated_at from a root artifact; None when unusable."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Covers JSONDecodeError and UnicodeDecodeError: a tampered artifact
        # must degrade gracefully, not crash validation.
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("generated_at")
    if not isinstance(value, str):
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def _stored_generated_at(root) -> str:
    """Reuse the stored registry timestamp so recomputation is byte-comparable."""
    value = _read_stored_generated_at(Path(root) / "library_registry.json")
    return value if value is not None else "1970-01-01T00:00:00+00:00"


def _current_version(root, case_id: str) -> str:
    matching = [package for package, _, _ in iter_case_versions(root) if package.case_id == case_id]
    if not matching:
        raise SpdInputError(f"library case not found: {case_id}")
    superseded = {
        package.supersedes_case_version for package in matching if package.supersedes_case_version
    }
    successor_counts = Counter(
        package.supersedes_case_version for package in matching if package.supersedes_case_version
    )
    candidates = [package for package in matching if package.case_version not in superseded]
    known_versions = {package.case_version for package in matching}
    broken_chain = any(
        package.supersedes_case_version is not None
        and package.supersedes_case_version not in known_versions
        for package in matching
    )
    has_cycle = chain_contains_cycle(
        {package.case_version: package.supersedes_case_version for package in matching}
    )
    # Same no-current invariant as registry derivation: an ambiguous or
    # broken chain (fork, shared predecessor, cycle, missing predecessor)
    # never silently resolves to a head.
    if (
        len(candidates) != 1
        or broken_chain
        or has_cycle
        or any(count > 1 for count in successor_counts.values())
    ):
        raise SpdInputError(
            f"case '{case_id}' has an ambiguous version chain; pass --case-version explicitly"
        )
    return candidates[0].case_version


def _is_active_template(root, case_id: str, case_version: str) -> bool:
    """Read the rebuilt active index; operations must report the real state."""
    path = Path(root) / "active_template_index.json"
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return False
    return any(
        isinstance(entry, dict)
        and entry.get("case_id") == case_id
        and entry.get("case_version") == case_version
        for entry in entries
    )


def _emit_operation(args, package: ProjectCasePackage, created: bool, dry_run: bool) -> int:
    active = (
        False
        if dry_run
        else _is_active_template(args.library_root, package.case_id, package.case_version)
    )
    payload = {
        "notice": LIBRARY_NOTICE,
        "case_id": package.case_id,
        "case_version": package.case_version,
        "case_role": package.case_role.value,
        "lifecycle_state": package.lifecycle_state.value,
        "review_state": package.review_state.value,
        "template_eligible": package.template_eligible,
        "active_template": active,
        "package_fingerprint": package.package_fingerprint,
        "review_binding_fingerprint": package.review_binding_fingerprint,
        "disposition": "dry_run" if dry_run else ("created" if created else "idempotent"),
    }
    if dry_run:
        return _emit(args, payload)
    # A mutation must never report success over a library whose rebuilt
    # validation failed; the resulting state is unsafe to consume.
    passed, errors = _stored_validation_status(args.library_root)
    payload["library_validation_passed"] = passed
    if not passed:
        payload["library_errors"] = errors
    _emit(args, payload)
    return 0 if passed else 3


def _stored_validation_status(root) -> tuple[bool, list[dict]]:
    """Read the validation report the mutation's root rebuild just wrote."""
    path = Path(root) / "validation_report.json"
    try:
        report = LibraryValidationReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, [
            {
                "check_id": "M7V-REPORT-UNREADABLE",
                "severity": "error",
                "message": f"stored validation report is unreadable: {exc}",
            }
        ]
    errors = [
        finding.model_dump(mode="json")
        for finding in report.findings
        if finding.severity == "error"
    ]
    return report.passed, errors


def _emit(args, payload: dict) -> int:
    if args.json_output:
        print(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
    else:
        if "case_id" in payload:
            print(
                f"{payload['case_id']} {payload.get('case_version', '')}: "
                f"{payload.get('disposition', payload.get('lifecycle_state', 'ok'))}"
            )
            print(f"  role: {payload.get('case_role', 'n/a')}")
            print(f"  template eligible: {str(payload.get('template_eligible', False)).lower()}")
        elif "entries" in payload:
            print(LIBRARY_NOTICE)
            for entry in payload["entries"]:
                status = "current" if entry["is_current"] else "superseded"
                active = "active-template" if entry["active_template"] else "inactive"
                print(
                    f"  {entry['case_id']}/{entry['case_version']} {entry['case_role']} "
                    f"package={entry['package_lifecycle_state']} "
                    f"effective={entry['effective_lifecycle_state']} "
                    f"[{status}, {active}]"
                )
        else:
            print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


__all__ = [
    "LIBRARY_NOTICE",
    "add_library_subparser",
    "apply_architect_corrections",
    "apply_architect_decision",
    "apply_review",
    "archive_case",
    "import_m6a_artifacts",
    "ingest_source_bundle",
    "review_status_payload",
    "run_library_command",
]
