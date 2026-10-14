"""Privacy-safe source asset cataloguing for the M7.1 library."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from saudi_plot_design.cases.models import ArchitecturalDesignCase
from saudi_plot_design.library.models import (
    AssetFormat,
    CreationMetadata,
    OriginalPathPolicy,
    ParserStatus,
    SourceAsset,
    SourceBundleManifest,
)
from saudi_plot_design.model import SpdInputError

_ZERO_HASH = "0" * 64
_IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
_SPEC_SUFFIXES = {".doc", ".docx", ".odt", ".rtf", ".txt"}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_asset_format(path: str | Path, role: str | None = None) -> AssetFormat:
    path = Path(path)
    suffix = path.suffix.lower()
    role_token = (role or "").lower()
    if "review" in role_token:
        return AssetFormat.REVIEW_DECISION
    if "metadata" in role_token:
        return AssetFormat.METADATA
    if suffix == ".ifc":
        return AssetFormat.IFC
    if suffix == ".rvt":
        return AssetFormat.RVT
    if suffix == ".dwg":
        return AssetFormat.DWG
    if suffix == ".pdf":
        return AssetFormat.PDF
    if suffix in _IMAGE_SUFFIXES:
        return AssetFormat.IMAGE
    if suffix in _SPEC_SUFFIXES:
        return AssetFormat.SPECIFICATION
    if suffix == ".json":
        return AssetFormat.METADATA
    return AssetFormat.OTHER


def default_asset_role(asset_format: AssetFormat) -> str:
    if asset_format in {AssetFormat.IFC, AssetFormat.RVT, AssetFormat.DWG}:
        return "source_model"
    if asset_format is AssetFormat.REVIEW_DECISION:
        return "review_decision"
    if asset_format is AssetFormat.METADATA:
        return "metadata"
    if asset_format is AssetFormat.SPECIFICATION:
        return "specification"
    return "reference_asset"


def catalog_source_asset(
    path: str | Path,
    *,
    role: str | None = None,
    confidential: bool,
    usage_rights_confirmed: bool,
    parser_status: ParserStatus | None = None,
    derived_artifact_references: tuple[str, ...] = (),
) -> SourceAsset:
    """Fingerprint one external asset without retaining or copying its path."""
    path = Path(path)
    if not path.is_file():
        raise SpdInputError(f"source asset not found: {path.name or '<unnamed>'}")
    digest = sha256_file(path)
    asset_format = infer_asset_format(path, role)
    resolved_role = role or default_asset_role(asset_format)
    if parser_status is None:
        parser_status = (
            ParserStatus.NOT_APPLICABLE
            if asset_format in {AssetFormat.METADATA, AssetFormat.REVIEW_DECISION}
            else ParserStatus.CATALOGUED_NOT_PARSED
        )
    suffix = path.suffix.lower()
    display_name = f"confidential-{digest[:12]}{suffix}" if confidential else path.name
    warnings: list[str] = []
    if parser_status is ParserStatus.CATALOGUED_NOT_PARSED:
        warnings.append(f"{asset_format.value}_catalogued_not_parsed_in_m7_1")
    if not usage_rights_confirmed:
        warnings.append("usage_rights_unconfirmed")
    role_token = "".join(character if character.isalnum() else "-" for character in resolved_role)
    asset_id = f"{role_token.strip('-').lower()}-{digest[:16]}"
    return SourceAsset(
        asset_id=asset_id,
        display_name=display_name,
        format=asset_format,
        role=resolved_role,
        parser_status=parser_status,
        size_bytes=path.stat().st_size,
        sha256=digest,
        confidentiality_status="confidential" if confidential else "internal",
        usage_rights_status="confirmed" if usage_rights_confirmed else "unconfirmed",
        original_path_policy=(
            OriginalPathPolicy.ANONYMIZED_DISPLAY_NAME
            if confidential
            else OriginalPathPolicy.EXTERNAL_REFERENCE_ONLY
        ),
        external_reference_id=f"external-asset:{digest}",
        derived_artifact_references=tuple(sorted(derived_artifact_references)),
        warnings=tuple(sorted(warnings)),
    )


def source_bundle_from_assets(
    *,
    case_id: str,
    case_version: str,
    assets: tuple[SourceAsset, ...],
    creation_metadata: CreationMetadata,
) -> SourceBundleManifest:
    bundle = SourceBundleManifest(
        case_id=case_id,
        case_version=case_version,
        assets=tuple(sorted(assets, key=lambda asset: asset.asset_id)),
        bundle_fingerprint=_ZERO_HASH,
        creation_metadata=creation_metadata,
    )
    payload = {
        "source_bundle_schema_version": bundle.source_bundle_schema_version,
        "assets": [asset.model_dump(mode="json") for asset in bundle.assets],
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    return bundle.model_copy(update={"bundle_fingerprint": fingerprint})


def source_bundle_from_m6a_case(
    case: ArchitecturalDesignCase,
    *,
    case_version: str,
    creation_metadata: CreationMetadata,
) -> SourceBundleManifest:
    """Reference an M6A IFC source by hash; never reopen or copy the source."""
    confidential = case.metadata.confidential
    source_asset = SourceAsset(
        asset_id=f"source-model-{case.provenance.source_fingerprint[:16]}",
        display_name=("confidential.ifc" if confidential else f"{case.case_id.lower()}-source.ifc"),
        format=AssetFormat.IFC,
        role="source_model",
        parser_status=ParserStatus.PARSED,
        # M6A's safe artifact set intentionally does not disclose source size.
        size_bytes=None,
        sha256=case.provenance.source_fingerprint,
        confidentiality_status="confidential" if confidential else "internal",
        usage_rights_status=(
            "confirmed" if case.metadata.usage_rights_confirmed else "unconfirmed"
        ),
        original_path_policy=OriginalPathPolicy.OMITTED,
        external_reference_id=f"m6a-source:{case.provenance.source_fingerprint}",
        derived_artifact_references=("m6a:architectural_case.json",),
        warnings=("source_size_not_available_in_m6a_safe_artifacts",),
    )
    return source_bundle_from_assets(
        case_id=case.case_id,
        case_version=case_version,
        assets=(source_asset,),
        creation_metadata=creation_metadata,
    )


__all__ = [
    "catalog_source_asset",
    "default_asset_role",
    "infer_asset_format",
    "sha256_file",
    "source_bundle_from_assets",
    "source_bundle_from_m6a_case",
]
