"""Machine-readable package and active-index validation for M7.1."""

from __future__ import annotations

import json
import re

from saudi_plot_design.cases.eligibility import SAUDI_COUNTRY_VALUES
from saudi_plot_design.library.fingerprints import (
    calculate_feature_fingerprint,
    calculate_package_fingerprint,
    calculate_review_binding_fingerprint,
    calculate_source_bundle_fingerprint,
)
from saudi_plot_design.library.models import (
    FEATURE_PACKAGE_SCHEMA_VERSION,
    PROJECT_PACKAGE_SCHEMA_VERSION,
    SOURCE_BUNDLE_SCHEMA_VERSION,
    ActiveTemplateIndex,
    CaseRole,
    LibraryValidationFinding,
    LifecycleState,
    ParserStatus,
    ProjectCasePackage,
    ReviewDecisionType,
    ReviewState,
    SourceBundleManifest,
    TemplateFeaturePackage,
)


def validate_project_package(
    package: ProjectCasePackage,
    bundle: SourceBundleManifest,
    features: TemplateFeaturePackage | None,
) -> tuple[LibraryValidationFinding, ...]:
    findings: list[LibraryValidationFinding] = []

    def add(check_id: str, message: str, severity: str = "error") -> None:
        findings.append(
            LibraryValidationFinding(
                check_id=check_id,
                severity=severity,
                case_id=package.case_id,
                case_version=package.case_version,
                message=message,
            )
        )

    if package.package_schema_version != PROJECT_PACKAGE_SCHEMA_VERSION:
        add("M7V-SCHEMA-PACKAGE", "unsupported project package schema version")
    if bundle.source_bundle_schema_version != SOURCE_BUNDLE_SCHEMA_VERSION:
        add("M7V-SCHEMA-BUNDLE", "unsupported source bundle schema version")
    if features is not None and features.feature_schema_version != FEATURE_PACKAGE_SCHEMA_VERSION:
        add("M7V-SCHEMA-FEATURE", "unsupported feature package schema version")
    if (bundle.case_id, bundle.case_version) != (package.case_id, package.case_version):
        add("M7V-IDENTITY-BUNDLE", "source bundle case id/version does not match package")
    # The bundle fingerprint covers only assets; bind its creation metadata
    # to the package so it cannot be silently rewritten in place.
    if bundle.creation_metadata != package.creation_metadata:
        add("M7V-BUNDLE-METADATA", "source bundle creation metadata does not match the package")
    if calculate_source_bundle_fingerprint(bundle) != bundle.bundle_fingerprint:
        add("M7V-HASH-BUNDLE", "source bundle fingerprint does not match its assets")
    if package.source_bundle_fingerprint != bundle.bundle_fingerprint:
        add("M7V-HASH-BUNDLE-REF", "package source bundle fingerprint is stale")
    asset_hashes = {asset.sha256 for asset in bundle.assets}
    if not set(package.source_fingerprints).issubset(asset_hashes):
        add("M7V-HASH-SOURCE", "package source fingerprints are absent from source bundle")
    if any(asset.usage_rights_status != "confirmed" for asset in bundle.assets):
        add("M7V-RIGHTS-ASSET", "one or more source assets have unconfirmed usage rights")
    for asset in bundle.assets:
        if asset.parser_status is ParserStatus.FAILED:
            add("M7V-PARSER-FAILED", f"source asset '{asset.asset_id}' parser status is failed")
        elif asset.parser_status is ParserStatus.CATALOGUED_NOT_PARSED:
            add(
                "M7V-PARSER-UNSUPPORTED",
                f"source asset '{asset.asset_id}' is catalogued but not parsed",
                "warning",
            )
        if asset.size_bytes is None:
            add(
                "M7V-ASSET-SIZE-UNAVAILABLE",
                f"source asset '{asset.asset_id}' size is unavailable in safe artifacts",
                "warning",
            )
    if package.canonical_artifact:
        if package.canonical_case_fingerprint != package.canonical_artifact.sha256:
            add("M7V-HASH-CANONICAL", "canonical case fingerprint conflicts with its reference")
    elif package.canonical_case_fingerprint is not None:
        add("M7V-CANONICAL-REF", "canonical fingerprint exists without an artifact reference")
    if calculate_review_binding_fingerprint(package) != package.review_binding_fingerprint:
        add("M7V-REVIEW-BINDING", "review binding fingerprint is stale")
    if calculate_package_fingerprint(package) != package.package_fingerprint:
        add("M7V-HASH-PACKAGE", "project package fingerprint is stale")
    if package.review_decision:
        if package.review_decision.bound_fingerprint != package.review_binding_fingerprint:
            add("M7V-STALE-APPROVAL", "review decision is bound to different case content")
        if (
            package.review_decision.decision is ReviewDecisionType.APPROVED
            and not package.review_decision.template_use_approved
        ):
            add("M7V-APPROVAL-EXPLICIT", "approved decision lacks explicit template-use approval")
        if (
            package.review_decision.decision is ReviewDecisionType.REVOKED
            and not package.usage_rights.template_use_revoked
        ):
            add("M7V-REVOCATION-RIGHTS", "revoked decision lacks the rights-revoked flag")
    elif package.review_state in {ReviewState.ARCHITECT_REVIEWED, ReviewState.APPROVED}:
        add("M7V-REVIEW-MISSING", "reviewed state has no review decision")
    if not package.usage_rights.ingestion_permitted:
        add("M7V-RIGHTS-INGEST", "ingestion permission is not confirmed")
    if not package.usage_rights.internal_review_permitted:
        add("M7V-RIGHTS-REVIEW", "internal review permission is not confirmed")
    if package.template_eligible and package.template_ineligibility_reasons:
        add("M7V-ELIGIBILITY-CONFLICT", "eligible package carries ineligibility reasons")
    if package.template_eligible and package.project_type != "residential_villa":
        add("M7V-ELIGIBILITY-PROJECT", "non-villa project is marked template eligible")
    if package.template_eligible and _country_token(package.country) not in SAUDI_COUNTRY_VALUES:
        add("M7V-ELIGIBILITY-COUNTRY", "non-Saudi project is marked template eligible")
    if package.template_eligible and not package.validation_summary.passed:
        add("M7V-ELIGIBILITY-VALIDATION", "failed source validation is marked eligible")
    # The known synthetic fixture must never shed its test-only provenance;
    # a contradicted marker would present test data as a real project.
    if (
        package.case_id.upper() == "SYNTHETIC-VILLA-TEST-001"
        and not package.provenance.synthetic_test_fixture
    ):
        add(
            "M7V-SYNTHETIC-PROVENANCE",
            "known synthetic fixture case is not marked synthetic_test_fixture",
        )

    if package.extracted_features is None:
        if features is not None:
            add("M7V-FEATURE-UNREFERENCED", "feature package exists but is not referenced")
    elif features is None:
        add("M7V-FEATURE-MISSING", "referenced feature package is missing")
    else:
        if (features.case_id, features.case_version) != (package.case_id, package.case_version):
            add("M7V-IDENTITY-FEATURE", "feature package case id/version does not match")
        if features.canonical_case_fingerprint != package.canonical_case_fingerprint:
            add("M7V-FEATURE-CANONICAL", "feature package references different canonical case")
        if calculate_feature_fingerprint(features) != features.feature_fingerprint:
            add("M7V-HASH-FEATURE", "feature package fingerprint is stale")
        if package.extracted_features.fingerprint != features.feature_fingerprint:
            add("M7V-HASH-FEATURE-REF", "package feature fingerprint is stale")
        expected_path = feature_relative_path(package.case_id, package.case_version)
        if package.extracted_features.relative_path != expected_path:
            add("M7V-FEATURE-PATH", "feature package reference path is not canonical")
        forbidden_features = ("embedding", "vector", "similarity", "ranking")
        for feature in features.features:
            if any(token in feature.feature_id for token in forbidden_features):
                add("M7V-NO-RETRIEVAL", f"forbidden retrieval feature '{feature.feature_id}'")

    serialized = json.dumps(
        {
            "package": package.model_dump(mode="json"),
            "bundle": bundle.model_dump(mode="json"),
            "features": features.model_dump(mode="json") if features else None,
        },
        ensure_ascii=False,
    )
    if _contains_forbidden_private_path(serialized):
        add("M7V-PRIVACY-PATH", "shareable library artifacts contain a private or absolute path")
    return tuple(sorted(findings, key=_finding_key))


def approval_use_ineligibility_reasons(
    package: ProjectCasePackage,
    bundle: SourceBundleManifest,
    features: TemplateFeaturePackage | None,
) -> tuple[str, ...]:
    """Decision-independent template-use gates.

    Shared verbatim by the approval transition and the active-index gate so
    the two can never diverge: a case that could not be an active template
    must not be approvable as one either.
    """
    reasons: list[str] = []
    if package.case_id.upper() == "TEST-OFFICE-001":
        reasons.append("permanent_test_office_exclusion")
    if not package.template_eligible:
        reasons.extend(package.template_ineligibility_reasons or ("template_ineligible",))
    if package.project_type != "residential_villa":
        reasons.append(f"project_type_not_residential_villa:{package.project_type}")
    if _country_token(package.country) not in SAUDI_COUNTRY_VALUES:
        reasons.append(f"country_not_saudi_arabia:{_country_token(package.country)}")
    if not package.architectural_character:
        reasons.append("architectural_character_missing")
    if not package.validation_summary.passed:
        reasons.append("source_validation_failed")
    if not package.usage_rights.ingestion_permitted:
        reasons.append("ingestion_rights_missing")
    if not package.usage_rights.internal_review_permitted:
        reasons.append("review_rights_missing")
    if not package.usage_rights.template_use_permitted:
        reasons.append("template_use_permission_missing")
    if package.usage_rights.template_use_revoked:
        reasons.append("template_use_revoked")
    if (
        package.confidentiality.status == "confidential"
        and not package.confidentiality.shareable_outputs_permitted
    ):
        reasons.append("confidential_shareable_output_permission_missing")
    if package.extracted_features is None or features is None:
        reasons.append("feature_package_missing")
    errors = [
        finding
        for finding in validate_project_package(package, bundle, features)
        if finding.severity == "error"
    ]
    if errors:
        reasons.append("library_validation_failed")
    return tuple(sorted(set(reasons)))


def active_template_ineligibility_reasons(
    package: ProjectCasePackage,
    bundle: SourceBundleManifest,
    features: TemplateFeaturePackage | None,
) -> tuple[str, ...]:
    reasons: list[str] = list(approval_use_ineligibility_reasons(package, bundle, features))
    if package.case_role is not CaseRole.APPROVED_TEMPLATE:
        reasons.append(f"case_role_not_approved_template:{package.case_role.value}")
    if package.lifecycle_state is not LifecycleState.APPROVED:
        reasons.append(f"lifecycle_not_approved:{package.lifecycle_state.value}")
    if package.review_state is not ReviewState.APPROVED:
        reasons.append(f"review_state_not_approved:{package.review_state.value}")
    if not package.review_decision:
        reasons.append("review_decision_missing")
    elif package.review_decision.decision is not ReviewDecisionType.APPROVED:
        reasons.append(f"review_decision_not_approved:{package.review_decision.decision.value}")
    else:
        if package.review_decision.bound_fingerprint != package.review_binding_fingerprint:
            reasons.append("stale_review_binding")
        if not package.review_decision.template_use_approved:
            reasons.append("template_use_not_explicitly_approved")
    return tuple(sorted(set(reasons)))


def validate_active_index(
    index: ActiveTemplateIndex,
    packages: dict[
        tuple[str, str],
        tuple[ProjectCasePackage, SourceBundleManifest, TemplateFeaturePackage | None],
    ],
) -> tuple[LibraryValidationFinding, ...]:
    findings: list[LibraryValidationFinding] = []
    indexed = {(entry.case_id, entry.case_version) for entry in index.entries}
    for key, (package, bundle, features) in sorted(packages.items()):
        reasons = active_template_ineligibility_reasons(package, bundle, features)
        should_be_active = not reasons
        if should_be_active and key not in indexed:
            findings.append(
                _finding("M7V-INDEX-MISSING", package, "eligible approved template is absent")
            )
        if reasons and key in indexed:
            findings.append(
                _finding(
                    "M7V-INDEX-INELIGIBLE",
                    package,
                    "ineligible case is active: " + ", ".join(reasons),
                )
            )
    for entry in index.entries:
        if (entry.case_id, entry.case_version) not in packages:
            findings.append(
                LibraryValidationFinding(
                    check_id="M7V-INDEX-DANGLING",
                    severity="error",
                    case_id=entry.case_id,
                    case_version=entry.case_version,
                    message="active index entry has no package",
                )
            )
    return tuple(sorted(findings, key=_finding_key))


def feature_relative_path(case_id: str, case_version: str) -> str:
    return f"feature_packages/{case_id}/{case_version}/template_features.json"


def _finding(check_id: str, package: ProjectCasePackage, message: str):
    return LibraryValidationFinding(
        check_id=check_id,
        severity="error",
        case_id=package.case_id,
        case_version=package.case_version,
        message=message,
    )


def _country_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _contains_forbidden_private_path(value: str) -> bool:
    """Reject filesystem-path shapes in shareable artifacts, conservatively.

    Free-form fields (rights basis, rationale, statements) carry no field
    validator, so this serialized scan must catch every path form: POSIX
    absolute under ANY root, UNC (``//server``), Windows drive-absolute
    (``c:/x``), and drive-relative (``c:x``).
    """
    normalized = value.replace("\\", "/").lower()
    if "private_cases/" in normalized:
        return True
    # URLs are legitimate external references, not filesystem paths — except
    # file:// URLs, which ARE filesystem paths and stay subject to the scan.
    # The scheme must be 2+ characters: a JSON-escaped Windows drive path
    # (C:\x -> c://x after normalization) must not pass as a one-letter URL.
    scrubbed = re.sub(r'(?<![a-z0-9])(?!file://)[a-z][a-z0-9+.-]+://[^\s"]*', "", normalized)
    # Boundary = start or any non-token character, so paths after punctuation
    # ("source=(/srv/x", "path=/opt/x") are caught, and the character after
    # the separator may be anything path-like, including non-ASCII.
    return bool(re.search(r'(?:^|[^a-z0-9_.~-])(?:/+[^\s"/]|[a-z]:[^\s"])', scrubbed))


def _finding_key(finding: LibraryValidationFinding):
    return (
        finding.case_id or "",
        finding.case_version or "",
        finding.severity,
        finding.check_id,
        finding.message,
    )


__all__ = [
    "active_template_ineligibility_reasons",
    "approval_use_ineligibility_reasons",
    "feature_relative_path",
    "validate_active_index",
    "validate_project_package",
]
