"""Canonical SHA-256 helpers shared by M7.1 storage and validation."""

from __future__ import annotations

import hashlib
import json

from saudi_plot_design.library.models import (
    LibraryManifest,
    ProjectCasePackage,
    ReviewPackageManifest,
    SourceBundleManifest,
    TemplateFeaturePackage,
)


def canonical_json_bytes(payload) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_payload(payload) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def calculate_source_bundle_fingerprint(bundle: SourceBundleManifest) -> str:
    return sha256_payload(
        {
            "source_bundle_schema_version": bundle.source_bundle_schema_version,
            "assets": [asset.model_dump(mode="json") for asset in bundle.assets],
        }
    )


def calculate_feature_fingerprint(features: TemplateFeaturePackage) -> str:
    return sha256_payload(
        features.model_dump(mode="json", exclude={"case_version", "feature_fingerprint"})
    )


def calculate_review_binding_fingerprint(package: ProjectCasePackage) -> str:
    """Bind review to source/canonical/features/policy evidence, not lifecycle fields."""
    # Revocation targets the reviewed content and invalidates active use, but
    # does not change which underlying content was reviewed. Other rights
    # fields remain part of the binding.
    rights = package.usage_rights.model_dump(mode="json", exclude={"template_use_revoked"})
    return sha256_payload(
        {
            "case_id": package.case_id,
            "project_type": package.project_type,
            "country": package.country,
            "city": package.city,
            "architectural_character": package.architectural_character,
            "confidentiality": package.confidentiality.model_dump(mode="json"),
            "usage_rights": rights,
            "source_fingerprints": list(package.source_fingerprints),
            "source_bundle_fingerprint": package.source_bundle_fingerprint,
            "canonical_case_fingerprint": package.canonical_case_fingerprint,
            "canonical_artifact": (
                package.canonical_artifact.model_dump(mode="json")
                if package.canonical_artifact
                else None
            ),
            "template_eligible": package.template_eligible,
            "template_ineligibility_reasons": list(package.template_ineligibility_reasons),
            "validation_summary": package.validation_summary.model_dump(mode="json"),
            "quality_summary": package.quality_summary.model_dump(mode="json"),
            "feature_fingerprint": (
                package.extracted_features.fingerprint if package.extracted_features else None
            ),
            "provenance": package.provenance.model_dump(mode="json"),
        }
    )


def calculate_package_fingerprint(package: ProjectCasePackage) -> str:
    return sha256_payload(package.model_dump(mode="json", exclude={"package_fingerprint"}))


def calculate_manifest_root_fingerprint(manifest: LibraryManifest) -> str:
    """Fingerprint the manifest's own metadata without recursive self-hashing."""
    return sha256_payload(manifest.model_dump(mode="json", exclude={"root_fingerprint"}))


def calculate_review_package_root_fingerprint(manifest: ReviewPackageManifest) -> str:
    """Same non-recursive metadata binding for the review-package manifest."""
    return sha256_payload(manifest.model_dump(mode="json", exclude={"root_fingerprint"}))


def finalize_package(package: ProjectCasePackage) -> ProjectCasePackage:
    binding = calculate_review_binding_fingerprint(package)
    bound = package.model_copy(update={"review_binding_fingerprint": binding})
    fingerprint = calculate_package_fingerprint(bound)
    return bound.model_copy(update={"package_fingerprint": fingerprint})


__all__ = [
    "calculate_feature_fingerprint",
    "calculate_manifest_root_fingerprint",
    "calculate_package_fingerprint",
    "calculate_review_package_root_fingerprint",
    "calculate_review_binding_fingerprint",
    "calculate_source_bundle_fingerprint",
    "canonical_json_bytes",
    "finalize_package",
    "sha256_payload",
]
