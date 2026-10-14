"""Deterministic registry and approved-template active-index derivation."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from saudi_plot_design.library.models import (
    SYNTHETIC_FIXTURE_DISCLAIMER,
    ActiveTemplateEntry,
    ActiveTemplateIndex,
    LibraryRegistry,
    LibraryValidationFinding,
    LibraryValidationReport,
    LifecycleState,
    RegistryEntry,
)
from saudi_plot_design.library.storage import (
    build_library_manifest,
    collect_case_versions,
    write_root_json,
    write_root_text,
)
from saudi_plot_design.library.validation import (
    active_template_ineligibility_reasons,
    validate_active_index,
    validate_project_package,
)


def chain_contains_cycle(supersedes_map: dict[str, str | None]) -> bool:
    """True if any supersession walk revisits a version (cyclic component)."""
    for start in supersedes_map:
        seen: set[str] = set()
        node: str | None = start
        while node is not None and node in supersedes_map:
            if node in seen:
                return True
            seen.add(node)
            node = supersedes_map[node]
    return False


def derive_library_state(
    root: str | Path, *, generated_at: str
) -> tuple[LibraryRegistry, ActiveTemplateIndex, LibraryValidationReport]:
    """Recompute registry, active index, and validation without writing."""
    versions, corruption_findings = collect_case_versions(root)
    corrupted_cases = {finding.case_id for finding in corruption_findings if finding.case_id}
    grouped = defaultdict(list)
    for item in versions:
        grouped[item[0].case_id].append(item)

    current_keys: set[tuple[str, str]] = set()
    global_findings: list[LibraryValidationFinding] = list(corruption_findings)
    for case_id, case_versions in sorted(grouped.items()):
        if case_id in corrupted_cases:
            # An unreadable version may be the newest (e.g. a revocation or
            # archive); selecting among the readable rest could silently
            # reactivate an older approved template. No current, none active.
            global_findings.append(
                LibraryValidationFinding(
                    check_id="M7V-CASE-UNREADABLE-VERSION",
                    severity="error",
                    case_id=case_id,
                    message=("case has unreadable stored versions; no current version selected"),
                )
            )
            continue
        superseded = {
            package.supersedes_case_version
            for package, _, _ in case_versions
            if package.supersedes_case_version is not None
        }
        candidates = [item for item in case_versions if item[0].case_version not in superseded]
        supersedes_map = {
            package.case_version: package.supersedes_case_version for package, _, _ in case_versions
        }
        has_cycle = chain_contains_cycle(supersedes_map)
        if has_cycle or not candidates:
            # A cyclic component — even one disconnected from a remaining
            # head — never resolves to a current version; the CLI resolver
            # applies the same rule.
            global_findings.append(
                LibraryValidationFinding(
                    check_id="M7V-VERSION-CYCLE",
                    severity="error",
                    case_id=case_id,
                    message=(
                        "version history contains a cycle or no head; no current version selected"
                    ),
                )
            )
        successor_counts = Counter(
            package.supersedes_case_version
            for package, _, _ in case_versions
            if package.supersedes_case_version is not None
        )
        shared_predecessors = sorted(
            version for version, count in successor_counts.items() if count > 1
        )
        known_versions = {package.case_version for package, _, _ in case_versions}
        broken_chain = False
        for package, _, _ in case_versions:
            if (
                package.supersedes_case_version is not None
                and package.supersedes_case_version not in known_versions
            ):
                broken_chain = True
                global_findings.append(
                    LibraryValidationFinding(
                        check_id="M7V-SUPERSEDES-MISSING",
                        severity="error",
                        case_id=case_id,
                        case_version=package.case_version,
                        message=(
                            "supersedes_case_version references a version absent from the library"
                        ),
                    )
                )
        heads = sorted(item[0].case_version for item in candidates)
        if len(heads) > 1 or shared_predecessors:
            # A forked chain (two heads, or two versions superseding the same
            # predecessor) is never silently resolved: no version is current,
            # none can be active, and validation fails.
            global_findings.append(
                LibraryValidationFinding(
                    check_id="M7V-VERSION-FORK",
                    severity="error",
                    case_id=case_id,
                    message=(
                        "version chain is ambiguous; no current version selected "
                        f"(heads: {heads}; shared predecessors: {shared_predecessors})"
                    ),
                )
            )
        elif candidates and not broken_chain and not has_cycle:
            # A version referencing a missing predecessor is a broken chain:
            # selecting it current could publish a template whose review
            # lineage can no longer be traced.
            current = max(
                candidates,
                key=lambda item: (item[0].creation_metadata.created_at, item[0].case_version),
            )[0]
            current_keys.add((case_id, current.case_version))

    registry_entries: list[RegistryEntry] = []
    active_entries: list[ActiveTemplateEntry] = []
    current_package_map = {}
    for package, bundle, features in versions:
        key = (package.case_id, package.case_version)
        is_current = key in current_keys
        findings = validate_project_package(package, bundle, features)
        global_findings.extend(findings)
        reasons = active_template_ineligibility_reasons(package, bundle, features)
        active = is_current and not reasons
        effective_lifecycle = package.lifecycle_state if is_current else LifecycleState.SUPERSEDED
        registry_entries.append(
            RegistryEntry(
                case_id=package.case_id,
                case_version=package.case_version,
                is_current=is_current,
                package_lifecycle_state=package.lifecycle_state,
                effective_lifecycle_state=effective_lifecycle,
                case_role=package.case_role,
                review_state=package.review_state,
                approval_state=(
                    package.review_decision.decision.value
                    if package.review_decision
                    else "not_approved"
                ),
                template_eligible=package.template_eligible,
                active_template=active,
                synthetic_test_fixture=package.provenance.synthetic_test_fixture,
                source_fingerprints=package.source_fingerprints,
                package_fingerprint=package.package_fingerprint,
                feature_package_fingerprint=(
                    features.feature_fingerprint if features is not None else None
                ),
                created_at=package.creation_metadata.created_at,
                warnings=tuple(reasons),
            )
        )
        if is_current:
            current_package_map[key] = (package, bundle, features)
        if active:
            assert package.review_decision is not None
            assert package.extracted_features is not None
            active_entries.append(
                ActiveTemplateEntry(
                    template_id=f"template:{package.case_id}:{package.case_version}",
                    case_id=package.case_id,
                    case_version=package.case_version,
                    project_type="residential_villa",
                    country=package.country,
                    city=package.city,
                    architectural_character=package.architectural_character or "",
                    package_fingerprint=package.package_fingerprint,
                    review_binding_fingerprint=package.review_binding_fingerprint,
                    feature_package_fingerprint=package.extracted_features.fingerprint,
                    feature_package_path=package.extracted_features.relative_path,
                    approved_by=package.review_decision.reviewer_id,
                    approved_on=package.review_decision.review_date,
                    synthetic_test_fixture=package.provenance.synthetic_test_fixture,
                    test_data_disclaimer=(
                        SYNTHETIC_FIXTURE_DISCLAIMER
                        if package.provenance.synthetic_test_fixture
                        else None
                    ),
                )
            )

    registry = LibraryRegistry(
        generated_at=generated_at,
        entries=tuple(
            sorted(registry_entries, key=lambda entry: (entry.case_id, entry.case_version))
        ),
    )
    index = ActiveTemplateIndex(
        generated_at=generated_at,
        entries=tuple(
            sorted(active_entries, key=lambda entry: (entry.case_id, entry.case_version))
        ),
    )
    global_findings.extend(validate_active_index(index, current_package_map))
    if any(entry.case_id.upper() == "TEST-OFFICE-001" for entry in index.entries):
        global_findings.append(
            LibraryValidationFinding(
                check_id="M7V-TEST-OFFICE-ACTIVE",
                severity="error",
                case_id="TEST-OFFICE-001",
                message="TEST-OFFICE-001 is permanently excluded from active templates",
            )
        )
    ordered_findings = tuple(
        sorted(
            global_findings,
            key=lambda finding: (
                finding.case_id or "",
                finding.case_version or "",
                finding.severity,
                finding.check_id,
                finding.message,
            ),
        )
    )
    validation = LibraryValidationReport(
        generated_at=generated_at,
        passed=not any(finding.severity == "error" for finding in ordered_findings),
        findings=ordered_findings,
        checked_case_versions=len(versions),
        active_template_count=len(index.entries),
    )
    return registry, index, validation


def rebuild_library(root: str | Path, *, generated_at: str):
    registry, index, validation = derive_library_state(root, generated_at=generated_at)
    write_root_json(root, "library_registry.json", registry.model_dump(mode="json"))
    write_root_json(root, "active_template_index.json", index.model_dump(mode="json"))
    write_root_json(root, "validation_report.json", validation.model_dump(mode="json"))
    write_root_text(root, "library_summary.md", _summary(registry, index, validation))
    manifest = build_library_manifest(root, generated_at=generated_at)
    return registry, index, validation, manifest


def _summary(
    registry: LibraryRegistry,
    index: ActiveTemplateIndex,
    validation: LibraryValidationReport,
) -> str:
    current = [entry for entry in registry.entries if entry.is_current]
    lines = [
        "# Project and Template Library Summary",
        "",
        "M7.1 local deterministic library. This output performs no template retrieval, ranking, adaptation, or design generation.",
        "",
        f"- Generated at (controlled metadata): `{registry.generated_at}`",
        f"- Case versions: **{len(registry.entries)}**",
        f"- Current cases: **{len(current)}**",
        f"- Active approved templates: **{len(index.entries)}**",
        f"- Validation: **{'passed' if validation.passed else 'failed'}**",
        "",
        "## Current cases",
        "",
        "| Case | Version | Role | Lifecycle | Review | Eligible | Active template |",
        "|---|---|---|---|---|---:|---:|",
    ]
    for entry in current:
        lines.append(
            f"| `{entry.case_id}` | `{entry.case_version}` | `{entry.case_role.value}` | "
            f"`{entry.effective_lifecycle_state.value}` | `{entry.review_state.value}` | "
            f"{str(entry.template_eligible).lower()} | {str(entry.active_template).lower()} |"
        )
    lines.extend(("", "## Active template index", ""))
    if index.entries:
        for entry in index.entries:
            if entry.synthetic_test_fixture:
                lines.append(f"- `{entry.template_id}` — {SYNTHETIC_FIXTURE_DISCLAIMER}")
            else:
                lines.append(f"- `{entry.template_id}`")
    else:
        lines.append(
            "- Empty: no case passed every approval, eligibility, rights, and feature gate."
        )
    lines.extend(
        (
            "",
            "TEST-OFFICE-001 is an ingestion stress test and is permanently excluded from the active residential-villa template index.",
            "",
        )
    )
    return "\n".join(lines)


__all__ = ["chain_contains_cycle", "derive_library_state", "rebuild_library"]
