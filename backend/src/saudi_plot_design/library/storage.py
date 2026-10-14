"""Immutable filesystem storage and artifact-manifest verification for M7.1."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from pydantic import ValidationError

from saudi_plot_design.library.models import (
    CASE_ID_PATTERN,
    LIBRARY_MANIFEST_SCHEMA_VERSION,
    VERSION_PATTERN,
    ArtifactRecord,
    LibraryManifest,
    LibraryValidationFinding,
    LibraryValidationReport,
    ProjectCasePackage,
    SourceBundleManifest,
    TemplateFeaturePackage,
)
from saudi_plot_design.library.fingerprints import calculate_manifest_root_fingerprint
from saudi_plot_design.library.validation import validate_project_package
from saudi_plot_design.model import SpdInputError

ROOT_ARTIFACTS = (
    "active_template_index.json",
    "library_manifest.json",
    "library_registry.json",
    "library_summary.md",
    "validation_report.json",
)
MANAGED_DIRECTORIES = (
    "project_packages",
    "feature_packages",
    "source_bundle_manifests",
)


class LibraryConflictError(SpdInputError):
    """An immutable case/version path already contains different bytes."""


_CASE_ID_RE = re.compile(CASE_ID_PATTERN)
_VERSION_RE = re.compile(VERSION_PATTERN)
_WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{digit}" for digit in "123456789"}
    | {f"lpt{digit}" for digit in "123456789"}
)


def require_safe_case_identifiers(case_id: str, case_version: str) -> None:
    """Reject identifiers that cannot be safe single path components.

    Transition helpers build packages with ``model_copy``, which skips model
    validation, so the storage boundary re-checks before any path is built.
    Windows device names (``CON``, ``NUL``, ``COM1``, ...) and trailing dots
    are rejected because they fail or alias another path on Windows.
    """
    for label, value, pattern in (
        ("case id", case_id, _CASE_ID_RE),
        ("case version", case_version, _VERSION_RE),
    ):
        if not pattern.fullmatch(value):
            raise SpdInputError(f"invalid library {label}: {value!r}")
        if value.endswith("."):
            raise SpdInputError(f"library {label} must not end with a dot: {value!r}")
        if value.split(".", 1)[0].lower() in _WINDOWS_RESERVED_NAMES:
            raise SpdInputError(f"library {label} is a reserved Windows device name: {value!r}")


def project_version_dir(root: str | Path, case_id: str, case_version: str) -> Path:
    return Path(root) / "project_packages" / case_id / case_version


def feature_version_dir(root: str | Path, case_id: str, case_version: str) -> Path:
    return Path(root) / "feature_packages" / case_id / case_version


def bundle_version_dir(root: str | Path, case_id: str, case_version: str) -> Path:
    return Path(root) / "source_bundle_manifests" / case_id / case_version


def ensure_safe_library_root(root: str | Path) -> Path:
    root = Path(root)
    resolved = root.resolve(strict=False)
    if "private_cases" in {part.lower() for part in (*root.parts, *resolved.parts)}:
        raise SpdInputError("library root must not be inside private_cases")
    return root


def json_bytes(payload) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def write_case_version(
    root: str | Path,
    package: ProjectCasePackage,
    bundle: SourceBundleManifest,
    features: TemplateFeaturePackage | None,
    *,
    dry_run: bool = False,
) -> bool:
    """Write a version once; return False for an identical idempotent replay."""
    root = ensure_safe_library_root(root)
    require_safe_case_identifiers(package.case_id, package.case_version)
    _reject_case_aliasing(root, package.case_id, package.case_version)
    findings = validate_project_package(package, bundle, features)
    error_ids = sorted({finding.check_id for finding in findings if finding.severity == "error"})
    if error_ids:
        # Never persist a package that fails validation: an error here can
        # mean private paths or broken integrity inside shareable artifacts.
        raise SpdInputError(
            "case version failed library validation and was not written: " + ", ".join(error_ids)
        )
    validation = LibraryValidationReport(
        generated_at=package.creation_metadata.created_at,
        passed=True,
        findings=findings,
        checked_case_versions=1,
        active_template_count=0,
    )
    project_dir = project_version_dir(root, package.case_id, package.case_version)
    feature_dir = feature_version_dir(root, package.case_id, package.case_version)
    bundle_dir = bundle_version_dir(root, package.case_id, package.case_version)
    desired: dict[Path, bytes] = {
        project_dir / "project_case_package.json": json_bytes(package.model_dump(mode="json")),
        project_dir / "provenance.json": json_bytes(package.provenance.model_dump(mode="json")),
        project_dir / "validation.json": json_bytes(validation.model_dump(mode="json")),
        bundle_dir / "asset_manifest.json": json_bytes(bundle.model_dump(mode="json")),
    }
    if features is not None:
        desired[feature_dir / "template_features.json"] = json_bytes(
            features.model_dump(mode="json")
        )

    case_root = root / "project_packages" / package.case_id

    def require_valid_supersession() -> None:
        # The chain is always evaluated against every OTHER stored version, so
        # a partially written (or merely pre-created) target directory can
        # never let a stale retry bypass the lineage check and fork the case.
        existing_payloads = [
            payload
            for path in sorted(case_root.glob("*/project_case_package.json"))
            for payload in (json.loads(path.read_text(encoding="utf-8")),)
            if payload.get("case_version") != package.case_version
        ]
        if existing_payloads:
            existing_versions = {payload["case_version"] for payload in existing_payloads}
            superseded_versions = {
                payload["supersedes_case_version"]
                for payload in existing_payloads
                if payload.get("supersedes_case_version")
            }
            current_versions = existing_versions - superseded_versions
            if package.supersedes_case_version is None:
                raise LibraryConflictError(
                    f"case '{package.case_id}' already exists; a different immutable version "
                    "must explicitly supersede the current version"
                )
            if package.supersedes_case_version not in current_versions:
                raise LibraryConflictError(
                    f"case '{package.case_id}' version '{package.case_version}' must supersede "
                    f"a current version; current versions are {sorted(current_versions)}"
                )
        elif package.supersedes_case_version is not None:
            raise LibraryConflictError(
                f"case '{package.case_id}' has no stored versions; its first version cannot "
                f"supersede '{package.supersedes_case_version}'"
            )

    existing = [path for path in desired if path.exists()]
    version_dirs = (project_dir, bundle_dir, feature_dir)
    any_version_dir = any(path.exists() for path in version_dirs)
    if existing or any_version_dir:
        expected_dirs = {project_dir, bundle_dir}
        if features is not None:
            expected_dirs.add(feature_dir)
        actual_files = {
            path
            for directory in expected_dirs
            if directory.is_dir()
            for path in directory.rglob("*")
            if path.is_file()
        }
        present_content_matches = all(
            not path.exists() or (path.is_file() and path.read_bytes() == content)
            for path, content in desired.items()
        )
        if present_content_matches and actual_files.issubset(desired):
            missing = [path for path in desired if not path.exists()]
            if not missing:
                return False
            # Every artifact already on disk is byte-identical to this exact
            # replay, so the earlier write was interrupted before all immutable
            # artifacts reached disk. Completing it never changes content, but
            # it must still supersede the case's real current version.
            require_valid_supersession()
            if dry_run:
                return True
            for path in missing:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(desired[path])
            return True
        raise LibraryConflictError(
            f"case '{package.case_id}' version '{package.case_version}' already exists "
            "with different content; immutable versions cannot be overwritten"
        )
    require_valid_supersession()
    if dry_run:
        return True

    created_dirs: list[Path] = []
    try:
        for directory in (project_dir, bundle_dir, *((feature_dir,) if features else ())):
            directory.mkdir(parents=True, exist_ok=False)
            created_dirs.append(directory)
        for path, content in desired.items():
            path.write_bytes(content)
    except BaseException:
        for directory in reversed(created_dirs):
            shutil.rmtree(directory, ignore_errors=True)
        raise
    return True


def load_case_version(
    root: str | Path, case_id: str, case_version: str
) -> tuple[ProjectCasePackage, SourceBundleManifest, TemplateFeaturePackage | None]:
    root = ensure_safe_library_root(root)
    require_safe_case_identifiers(case_id, case_version)
    project_dir = project_version_dir(root, case_id, case_version)
    package_path = project_dir / "project_case_package.json"
    provenance_path = project_dir / "provenance.json"
    validation_path = project_dir / "validation.json"
    bundle_path = bundle_version_dir(root, case_id, case_version) / "asset_manifest.json"
    feature_path = feature_version_dir(root, case_id, case_version) / "template_features.json"
    if not package_path.is_file() or not bundle_path.is_file():
        raise SpdInputError(f"library case/version not found: {case_id}/{case_version}")
    # Every immutable per-version artifact is required; a version stripped of
    # provenance or validation must never be silently re-blessed by a rebuild.
    if not provenance_path.is_file() or not validation_path.is_file():
        raise SpdInputError(
            f"stored library case/version is incomplete: {case_id}/{case_version}: "
            "provenance.json and validation.json are required"
        )
    try:
        package_text = package_path.read_text(encoding="utf-8")
        bundle_text = bundle_path.read_text(encoding="utf-8")
        provenance_text = provenance_path.read_text(encoding="utf-8")
        validation_text = validation_path.read_text(encoding="utf-8")
        feature_text = feature_path.read_text(encoding="utf-8") if feature_path.is_file() else None
    except (OSError, UnicodeDecodeError) as exc:
        raise SpdInputError(
            f"stored library case/version is unreadable: {case_id}/{case_version}: {exc}"
        ) from None
    try:
        package = ProjectCasePackage.model_validate_json(package_text)
        bundle = SourceBundleManifest.model_validate_json(bundle_text)
        stored_validation = LibraryValidationReport.model_validate_json(validation_text)
        features = (
            TemplateFeaturePackage.model_validate_json(feature_text)
            if feature_text is not None
            else None
        )
    except ValidationError as exc:
        raise SpdInputError(
            f"stored library case/version failed schema validation: {case_id}/{case_version}: "
            f"{exc.errors()[0]['msg']}"
        ) from None
    # The stored identity must match the directory it lives under, or renamed
    # and copied version directories would register under their internal ids
    # while the manifest records the physical paths.
    if (package.case_id, package.case_version) != (case_id, case_version):
        raise SpdInputError(
            f"stored library case/version is inconsistent: {case_id}/{case_version}: "
            f"package identity is {package.case_id}/{package.case_version}"
        )
    try:
        provenance_payload = json.loads(provenance_text)
    except json.JSONDecodeError as exc:
        raise SpdInputError(
            f"stored library case/version is unreadable: {case_id}/{case_version}: {exc}"
        ) from None
    if provenance_payload != package.provenance.model_dump(mode="json"):
        raise SpdInputError(
            f"stored library case/version is inconsistent: {case_id}/{case_version}: "
            "provenance.json does not match the stored package"
        )
    # The per-version report is deterministic from the stored artifacts, so a
    # schema-valid edit of validation.json (or any artifact it covers) is
    # detected instead of being re-blessed by the next manifest rebuild.
    expected_validation = LibraryValidationReport(
        generated_at=package.creation_metadata.created_at,
        passed=True,
        findings=validate_project_package(package, bundle, features),
        checked_case_versions=1,
        active_template_count=0,
    )
    if stored_validation != expected_validation:
        raise SpdInputError(
            f"stored library case/version is inconsistent: {case_id}/{case_version}: "
            "validation.json does not match the stored artifacts"
        )
    return package, bundle, features


def collect_case_versions(
    root: str | Path,
) -> tuple[
    tuple[tuple[ProjectCasePackage, SourceBundleManifest, TemplateFeaturePackage | None], ...],
    tuple[LibraryValidationFinding, ...],
]:
    """Load every stored version; corruption becomes findings, not exceptions.

    ``library validate`` must report unreadable or schema-invalid stored
    artifacts as machine-readable validation failures (exit 3) rather than
    classifying them as caller input errors or crashing.
    """
    root = ensure_safe_library_root(root)
    # Enumerate versions across ALL managed trees: a version whose package
    # file was deleted (bundle/features/provenance left behind) must be
    # reported as unreadable, not silently dropped.
    discovered: set[tuple[str, str]] = set()
    for directory in MANAGED_DIRECTORIES:
        base = root / directory
        if not base.is_dir():
            continue
        for case_dir in base.iterdir():
            if not case_dir.is_dir():
                continue
            for version_dir in case_dir.iterdir():
                if version_dir.is_dir():
                    discovered.add((case_dir.name, version_dir.name))
    keys = sorted(discovered)
    versions = []
    findings = []
    for case_id, case_version in keys:
        try:
            versions.append(load_case_version(root, case_id, case_version))
        except SpdInputError as exc:
            findings.append(
                LibraryValidationFinding(
                    check_id="M7V-STORED-ARTIFACT-UNREADABLE",
                    severity="error",
                    case_id=case_id,
                    case_version=case_version,
                    message=str(exc),
                )
            )
    return tuple(versions), tuple(findings)


def iter_case_versions(
    root: str | Path,
) -> tuple[tuple[ProjectCasePackage, SourceBundleManifest, TemplateFeaturePackage | None], ...]:
    root = ensure_safe_library_root(root)
    base = root / "project_packages"
    if not base.exists():
        return ()
    keys = sorted(
        (path.parent.parent.name, path.parent.name)
        for path in base.glob("*/*/project_case_package.json")
    )
    return tuple(load_case_version(root, case_id, case_version) for case_id, case_version in keys)


def write_root_json(root: str | Path, name: str, payload) -> Path:
    if name not in ROOT_ARTIFACTS:
        raise ValueError(f"unmanaged root artifact: {name}")
    root = ensure_safe_library_root(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_bytes(json_bytes(payload))
    return path


def write_root_text(root: str | Path, name: str, content: str) -> Path:
    if name not in ROOT_ARTIFACTS:
        raise ValueError(f"unmanaged root artifact: {name}")
    root = ensure_safe_library_root(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def derive_library_manifest(root: str | Path, *, generated_at: str) -> LibraryManifest:
    """Recompute the manifest expected for the current disk state, no writes."""
    root = ensure_safe_library_root(root)
    # Exclude ONLY the root manifest itself; a nested file that happens to be
    # named library_manifest.json must be recorded like any other artifact.
    root_manifest = root / "library_manifest.json"
    records = tuple(
        ArtifactRecord(
            relative_path=path.relative_to(root).as_posix(),
            size_bytes=path.stat().st_size,
            sha256=_sha256(path),
        )
        for path in _managed_files(root)
        if path != root_manifest
    )
    manifest = LibraryManifest(
        generated_at=generated_at, artifacts=records, root_fingerprint="0" * 64
    )
    return manifest.model_copy(
        update={"root_fingerprint": calculate_manifest_root_fingerprint(manifest)}
    )


def build_library_manifest(root: str | Path, *, generated_at: str) -> LibraryManifest:
    manifest = derive_library_manifest(root, generated_at=generated_at)
    write_root_json(root, "library_manifest.json", manifest.model_dump(mode="json"))
    return manifest


def verify_library_manifest(root: str | Path) -> tuple[str, ...]:
    root = ensure_safe_library_root(root)
    path = root / "library_manifest.json"
    if not path.is_file():
        return ("missing library_manifest.json",)
    try:
        manifest = LibraryManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValidationError, json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        return (f"invalid library_manifest.json: {exc}",)
    if manifest.library_manifest_schema_version != LIBRARY_MANIFEST_SCHEMA_VERSION:
        return (
            "invalid library_manifest.json: unsupported schema version "
            f"{manifest.library_manifest_schema_version}",
        )
    if calculate_manifest_root_fingerprint(manifest) != manifest.root_fingerprint:
        return (
            "invalid library_manifest.json: root fingerprint does not match the "
            "manifest metadata (generated_at or records were modified)",
        )
    errors: list[str] = []
    recorded = {record.relative_path for record in manifest.artifacts}
    actual = {
        item.relative_to(root).as_posix()
        for item in _managed_files(root)
        if item != root / "library_manifest.json"
    }
    for relative in sorted(recorded - actual):
        errors.append(f"missing artifact: {relative}")
    for relative in sorted(actual - recorded):
        errors.append(f"unrecorded artifact: {relative}")
    for record in manifest.artifacts:
        artifact = root / record.relative_path
        if not artifact.is_file():
            continue
        if artifact.stat().st_size != record.size_bytes:
            errors.append(f"size mismatch: {record.relative_path}")
        if _sha256(artifact) != record.sha256:
            errors.append(f"hash mismatch: {record.relative_path}")
    return tuple(errors)


def _reject_case_aliasing(root: Path, case_id: str, case_version: str) -> None:
    """Reject identifiers that differ from stored ones only by letter case.

    Case-insensitive filesystems (Windows, default macOS) would silently map
    both spellings onto one immutable directory.
    """
    case_base = root / "project_packages"
    sibling = _case_folded_conflict(case_base, case_id)
    if sibling is not None:
        raise LibraryConflictError(
            f"case id '{case_id}' differs only by letter case from stored case '{sibling}'"
        )
    version_sibling = _case_folded_conflict(case_base / case_id, case_version)
    if version_sibling is not None:
        raise LibraryConflictError(
            f"case '{case_id}' version '{case_version}' differs only by letter case "
            f"from stored version '{version_sibling}'"
        )


def _case_folded_conflict(parent: Path, name: str) -> str | None:
    if not parent.is_dir():
        return None
    for child in parent.iterdir():
        if child.name != name and child.name.lower() == name.lower():
            return child.name
    return None


def _managed_files(root: Path) -> list[Path]:
    files = [root / name for name in ROOT_ARTIFACTS if (root / name).is_file()]
    for directory in MANAGED_DIRECTORIES:
        base = root / directory
        if base.exists():
            files.extend(path for path in base.rglob("*") if path.is_file())
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "LibraryConflictError",
    "build_library_manifest",
    "bundle_version_dir",
    "collect_case_versions",
    "derive_library_manifest",
    "ensure_safe_library_root",
    "feature_version_dir",
    "iter_case_versions",
    "json_bytes",
    "load_case_version",
    "project_version_dir",
    "require_safe_case_identifiers",
    "verify_library_manifest",
    "write_case_version",
    "write_root_json",
    "write_root_text",
]
