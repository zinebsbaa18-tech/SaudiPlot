"""M7.1 project/template library lifecycle, privacy, and determinism tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

pytest.importorskip("ifcopenshell")

from m6a_ifc_fixture import build_case_dir
from m7_library_fixture import (
    build_office_stress_artifacts,
    build_reference_library,
    build_synthetic_villa_artifacts,
    metadata,
)

from saudi_plot_design.cases.eligibility import evaluate_template_eligibility
from saudi_plot_design.library.commands import (
    apply_review,
    archive_case,
    import_m6a_artifacts,
    ingest_source_bundle,
)
from saudi_plot_design.library.feature_extraction import extract_case_features
from saudi_plot_design.library.models import (
    AssetFormat,
    CaseRole,
    Confidentiality,
    LifecycleState,
    ParserStatus,
    ReviewDecisionType,
    ReviewState,
    SourceAsset,
    SourceBundleManifest,
    UsageRights,
)
from saudi_plot_design.library.registry import derive_library_state, rebuild_library
from saudi_plot_design.library.source_bundle import catalog_source_asset
from saudi_plot_design.library.storage import (
    LibraryConflictError,
    iter_case_versions,
    load_case_version,
    verify_library_manifest,
)
from saudi_plot_design.library.validation import (
    active_template_ineligibility_reasons,
    validate_project_package,
)
from saudi_plot_design.model import SpdInputError


@pytest.fixture(scope="module")
def reference(tmp_path_factory):
    root = tmp_path_factory.mktemp("m7-reference")
    library = root / "library"
    context = build_reference_library(library, root / "work")
    return library, context


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rights(*, template: bool = False, revoked: bool = False):
    return UsageRights(
        ingestion_permitted=True,
        internal_review_permitted=True,
        template_use_permitted=template,
        template_use_revoked=revoked,
        rights_basis="sanitized automated test fixture",
    )


def _confidentiality(*, confidential=False, shareable=True):
    return Confidentiality(
        status="confidential" if confidential else "internal",
        anonymized=confidential,
        shareable_outputs_permitted=shareable,
    )


# 1-7: source bundle schema and privacy ------------------------------------


def test_source_bundle_schema_rejects_unsorted_assets(tmp_path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.ifc"
    a.write_bytes(b"pdf")
    b.write_bytes(b"ifc")
    assets = (
        catalog_source_asset(a, confidential=False, usage_rights_confirmed=True),
        catalog_source_asset(b, confidential=False, usage_rights_confirmed=True),
    )
    assets = tuple(sorted(assets, key=lambda asset: asset.asset_id, reverse=True))
    with pytest.raises(ValidationError, match="ordered"):
        SourceBundleManifest(
            case_id="case-a",
            case_version="1.0.0",
            assets=assets,
            bundle_fingerprint="0" * 64,
            creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
        )


def test_ifc_source_registration_is_fingerprinted_not_parsed(tmp_path):
    path = tmp_path / "model.ifc"
    path.write_bytes(b"synthetic IFC placeholder")
    asset = catalog_source_asset(path, confidential=False, usage_rights_confirmed=True)
    assert asset.format is AssetFormat.IFC
    assert asset.parser_status is ParserStatus.CATALOGUED_NOT_PARSED
    assert asset.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("filename", "expected"),
    (("model.rvt", AssetFormat.RVT), ("model.dwg", AssetFormat.DWG)),
)
def test_unsupported_model_formats_are_catalogued_not_parsed(tmp_path, filename, expected):
    path = tmp_path / filename
    path.write_bytes(b"sanitized placeholder")
    asset = catalog_source_asset(path, confidential=False, usage_rights_confirmed=True)
    assert asset.format is expected
    assert asset.parser_status is ParserStatus.CATALOGUED_NOT_PARSED


@pytest.mark.parametrize(
    ("filename", "expected"),
    (("reference.pdf", AssetFormat.PDF), ("render.png", AssetFormat.IMAGE)),
)
def test_pdf_and_image_assets_are_catalogued_not_parsed(tmp_path, filename, expected):
    path = tmp_path / filename
    path.write_bytes(b"sanitized placeholder")
    asset = catalog_source_asset(path, confidential=False, usage_rights_confirmed=True)
    assert asset.format is expected
    assert asset.parser_status is ParserStatus.CATALOGUED_NOT_PARSED


def test_confidential_asset_path_is_anonymized(tmp_path):
    secret = tmp_path / "CLIENT-ADDRESS-PROJECT.rvt"
    secret.write_bytes(b"private test bytes")
    asset = catalog_source_asset(secret, confidential=True, usage_rights_confirmed=True)
    serialized = asset.model_dump_json()
    assert secret.name not in serialized
    assert str(tmp_path) not in serialized
    assert asset.display_name.startswith("confidential-")


def test_source_asset_rejects_absolute_external_reference():
    with pytest.raises(ValidationError, match="absolute path"):
        SourceAsset(
            asset_id="source-0000000000000000",
            display_name="model.ifc",
            format="ifc",
            role="source_model",
            parser_status="parsed",
            size_bytes=10,
            sha256="0" * 64,
            confidentiality_status="internal",
            usage_rights_status="confirmed",
            original_path_policy="external_reference_only",
            external_reference_id="C:/private/model.ifc",
        )


# 8-15: determinism, idempotence, immutability -----------------------------


def test_project_package_is_deterministic_across_roots(tmp_path):
    _, artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    packages = []
    for name in ("a", "b"):
        package, _ = import_m6a_artifacts(
            library_root=tmp_path / name,
            artifact_root=artifacts,
            case_version="1.0.0",
            case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
            creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
            template_use_permitted=True,
            shareable_outputs_permitted=True,
            rights_basis="synthetic fixture testing only",
            synthetic_test_fixture=True,
        )
        packages.append(package)
    assert packages[0] == packages[1]


@pytest.mark.parametrize("files_sha256", [{}, {"../outside.json": "0" * 64}])
def test_m6a_import_requires_exact_safe_manifest_file_set(tmp_path, files_sha256):
    _, artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    manifest_path = artifacts / "case_manifest.json"
    manifest = _read(manifest_path)
    manifest["files_sha256"] = files_sha256
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(SpdInputError, match="required safe artifact set") as error:
        import_m6a_artifacts(
            library_root=tmp_path / "library",
            artifact_root=artifacts,
            case_version="1.0.0",
            case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
            creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
            template_use_permitted=True,
            shareable_outputs_permitted=True,
            rights_basis="synthetic fixture testing only",
            synthetic_test_fixture=True,
        )
    assert "outside.json" not in str(error.value)


def test_feature_package_is_deterministic(reference):
    library, context = reference
    first = extract_case_features(
        context["villa_case"],
        case_version="x",
        canonical_case_fingerprint=context["candidate"].canonical_case_fingerprint,
    )
    second = extract_case_features(
        context["villa_case"],
        case_version="x",
        canonical_case_fingerprint=context["candidate"].canonical_case_fingerprint,
    )
    assert first == second
    stored = load_case_version(library, context["approved"].case_id, "1.1.0")[2]
    assert stored is not None and stored.feature_fingerprint == first.feature_fingerprint


def test_registry_and_active_index_are_deterministic(tmp_path):
    _, office_artifacts, _ = build_office_stress_artifacts(tmp_path / "shared-office")
    _, villa_artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "shared-villa")
    roots = []
    for name in ("a", "b"):
        root = tmp_path / name / "library"
        build_reference_library(
            root,
            tmp_path / name / "work",
            office_artifacts=office_artifacts,
            villa_artifacts=villa_artifacts,
        )
        roots.append(root)
    for filename in ("library_registry.json", "active_template_index.json"):
        assert (roots[0] / filename).read_bytes() == (roots[1] / filename).read_bytes()


def test_duplicate_identical_import_is_idempotent(tmp_path):
    _, artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    kwargs = dict(
        library_root=tmp_path / "library",
        artifact_root=artifacts,
        case_version="1.0.0",
        case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
        creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
        template_use_permitted=True,
        shareable_outputs_permitted=True,
        rights_basis="synthetic fixture testing only",
        synthetic_test_fixture=True,
    )
    _, created_first = import_m6a_artifacts(**kwargs)
    _, created_second = import_m6a_artifacts(**kwargs)
    assert created_first is True and created_second is False


def test_conflicting_duplicate_version_is_rejected(tmp_path):
    _, artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    common = dict(
        library_root=tmp_path / "library",
        artifact_root=artifacts,
        case_version="1.0.0",
        case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
        creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
        template_use_permitted=True,
        shareable_outputs_permitted=True,
        synthetic_test_fixture=True,
    )
    import_m6a_artifacts(**common, rights_basis="first")
    with pytest.raises(LibraryConflictError, match="immutable"):
        import_m6a_artifacts(**common, rights_basis="different")


def test_new_version_requires_explicit_current_supersession(tmp_path):
    _, artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    common = dict(
        library_root=tmp_path / "library",
        artifact_root=artifacts,
        case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
        creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
        template_use_permitted=True,
        shareable_outputs_permitted=True,
        rights_basis="synthetic fixture testing only",
        synthetic_test_fixture=True,
    )
    import_m6a_artifacts(**common, case_version="1.0.0")
    with pytest.raises(LibraryConflictError, match="explicitly supersede"):
        import_m6a_artifacts(**common, case_version="2.0.0")


def test_review_creates_new_immutable_version(reference):
    library, context = reference
    keys = {
        (package.case_id, package.case_version) for package, _, _ in iter_case_versions(library)
    }
    case_id = context["approved"].case_id
    assert (case_id, "1.0.0") in keys and (case_id, "1.1.0") in keys
    assert (
        load_case_version(library, case_id, "1.0.0")[0].review_state is ReviewState.REQUIRES_REVIEW
    )


def test_superseded_version_is_inactive(reference):
    library, context = reference
    registry = _read(library / "library_registry.json")
    old = next(
        entry
        for entry in registry["entries"]
        if entry["case_id"] == context["approved"].case_id and entry["case_version"] == "1.0.0"
    )
    assert old["is_current"] is False
    assert old["effective_lifecycle_state"] == "superseded"
    assert old["active_template"] is False


def test_stale_approval_binding_is_rejected(reference):
    library, context = reference
    with pytest.raises(SpdInputError, match="stale"):
        apply_review(
            library_root=library,
            case_id=context["candidate"].case_id,
            from_version="1.0.0",
            new_version="2.0.0",
            decision_type=ReviewDecisionType.APPROVED,
            reviewer_id="reviewer",
            review_date="2026-07-16",
            bound_fingerprint="f" * 64,
            rationale="test",
            template_use_approved=True,
            creation_metadata=metadata("2026-07-16T09:00:00+03:00"),
        )


# 16-25: approval, rights, exclusion, active index -------------------------


def test_eligible_synthetic_villa_can_be_explicitly_approved(reference):
    _, context = reference
    approved = context["approved"]
    assert approved.case_role is CaseRole.APPROVED_TEMPLATE
    assert approved.lifecycle_state is LifecycleState.APPROVED
    assert approved.review_state is ReviewState.APPROVED
    assert approved.provenance.synthetic_test_fixture is True


def test_ineligible_office_approval_is_rejected(tmp_path):
    _, artifacts, _ = build_office_stress_artifacts(tmp_path / "fixture")
    package, _ = import_m6a_artifacts(
        library_root=tmp_path / "library",
        artifact_root=artifacts,
        case_version="1.0.0",
        case_role=CaseRole.INGESTION_STRESS_TEST,
        creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
        template_use_permitted=True,
        shareable_outputs_permitted=True,
        rights_basis="ingestion test only",
    )
    with pytest.raises(SpdInputError, match="prohibited"):
        apply_review(
            library_root=tmp_path / "library",
            case_id=package.case_id,
            from_version=package.case_version,
            new_version="1.1.0",
            decision_type=ReviewDecisionType.APPROVED,
            reviewer_id="reviewer",
            review_date="2026-07-16",
            bound_fingerprint=package.review_binding_fingerprint,
            rationale="must fail",
            template_use_approved=True,
            creation_metadata=metadata("2026-07-16T08:01:00+03:00"),
        )


def test_stress_test_is_excluded_from_active_index(reference):
    library, _ = reference
    index = _read(library / "active_template_index.json")
    assert all(entry["case_id"] != "TEST-OFFICE-001" for entry in index["entries"])


def test_ingestion_requires_usage_rights(tmp_path):
    asset = tmp_path / "source.pdf"
    asset.write_bytes(b"safe")
    with pytest.raises(SpdInputError, match="usage rights"):
        ingest_source_bundle(
            library_root=tmp_path / "library",
            asset_paths=(asset,),
            case_id="source-1",
            case_version="1.0.0",
            display_name="Source",
            project_type="unknown",
            country="SA",
            city=None,
            architectural_character=None,
            creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
            usage_rights=UsageRights(
                ingestion_permitted=False,
                internal_review_permitted=True,
                template_use_permitted=False,
                rights_basis="missing ingestion permission",
            ),
            confidentiality=_confidentiality(),
        )


def test_template_use_permission_is_enforced(tmp_path):
    _, artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    package, _ = import_m6a_artifacts(
        library_root=tmp_path / "library",
        artifact_root=artifacts,
        case_version="1.0.0",
        case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
        creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
        template_use_permitted=False,
        shareable_outputs_permitted=True,
        rights_basis="ingestion only",
        synthetic_test_fixture=True,
    )
    with pytest.raises(SpdInputError, match="template_use_permission_missing"):
        apply_review(
            library_root=tmp_path / "library",
            case_id=package.case_id,
            from_version="1.0.0",
            new_version="1.1.0",
            decision_type=ReviewDecisionType.APPROVED,
            reviewer_id="reviewer",
            review_date="2026-07-16",
            bound_fingerprint=package.review_binding_fingerprint,
            rationale="must fail",
            template_use_approved=True,
            creation_metadata=metadata("2026-07-16T08:01:00+03:00"),
        )


def test_revoked_review_removes_template_from_index(tmp_path):
    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    approved = context["approved"]
    revoked, _ = apply_review(
        library_root=library,
        case_id=approved.case_id,
        from_version=approved.case_version,
        new_version="1.2.0",
        decision_type=ReviewDecisionType.REVOKED,
        reviewer_id="synthetic-test-reviewer",
        review_date="2026-07-16",
        bound_fingerprint=approved.review_binding_fingerprint,
        rationale="test revocation",
        template_use_approved=False,
        creation_metadata=metadata("2026-07-16T08:03:00+03:00"),
    )
    assert revoked.review_state is ReviewState.REVOKED
    assert revoked.usage_rights.template_use_revoked is True
    assert _read(library / "active_template_index.json")["entries"] == []


def test_failed_source_validation_is_excluded(tmp_path):
    from m6a_ifc_fixture import build_case_dir
    from saudi_plot_design.cases.pipeline import ingest_case

    source = build_case_dir(tmp_path / "bad", ifc_kwargs={"bad_area": True})
    artifacts = tmp_path / "bad-artifacts"
    ingest_case(source, artifacts)
    package, _ = import_m6a_artifacts(
        library_root=tmp_path / "library",
        artifact_root=artifacts,
        case_version="1.0.0",
        case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
        creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
        template_use_permitted=True,
        shareable_outputs_permitted=True,
        rights_basis="synthetic invalid fixture",
        synthetic_test_fixture=True,
    )
    assert not package.validation_summary.passed
    assert not package.template_eligible
    assert _read(tmp_path / "library" / "active_template_index.json")["entries"] == []


def test_missing_feature_package_is_excluded(tmp_path):
    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    feature = (
        library
        / "feature_packages"
        / context["approved"].case_id
        / context["approved"].case_version
        / "template_features.json"
    )
    feature.unlink()
    rebuild_library(library, generated_at="2026-07-16T08:03:00+03:00")
    assert _read(library / "active_template_index.json")["entries"] == []


def test_test_office_is_registered_requires_review_and_ineligible(reference):
    library, _ = reference
    office = load_case_version(library, "TEST-OFFICE-001", "1.0.0")[0]
    assert office.case_role is CaseRole.INGESTION_STRESS_TEST
    assert office.lifecycle_state is LifecycleState.REQUIRES_REVIEW
    assert office.review_state is ReviewState.REQUIRES_REVIEW
    assert office.template_eligible is False


def test_only_synthetic_fixture_is_active(reference):
    library, _ = reference
    entries = _read(library / "active_template_index.json")["entries"]
    assert [(entry["case_id"], entry["case_version"]) for entry in entries] == [
        ("SYNTHETIC-VILLA-TEST-001", "1.1.0")
    ]


# 26-33: feature groups and no retrieval ----------------------------------


def _feature_map(reference):
    library, context = reference
    features = load_case_version(library, context["approved"].case_id, "1.1.0")[2]
    assert features is not None
    return {feature.feature_id: feature for feature in features.features}


def test_program_features(reference):
    features = _feature_map(reference)
    assert features["program.bedroom_count"].value >= 1
    assert features["program.bathroom_count"].value >= 1
    assert features["program.majlis_present"].value is True


def test_zoning_features(reference):
    features = _feature_map(reference)
    assert features["zoning.room_assignments"].value
    assert "zoning.transition_matrix" in features


def test_adjacency_features(reference):
    features = _feature_map(reference)
    assert isinstance(features["topology.room_adjacency"].value, list)
    assert isinstance(features["topology.door_connectivity"].value, list)


def test_entrance_features_retain_actual_door_evidence(reference):
    inventory = _feature_map(reference)["entrances.inventory"].value
    assert inventory
    assert all(item["actual_door_evidence"] is True for item in inventory)


def test_wet_group_features(reference):
    groups = _feature_map(reference)["topology.wet_area_groups"].value
    assert isinstance(groups, list)


def test_facade_opening_features(reference):
    features = _feature_map(reference)
    assert features["facade.opening_inventory"].value
    assert features["facade.front_elevation_proportions"].value is None


def test_quality_feature_is_honestly_not_evaluated(reference):
    quality = _feature_map(reference)["quality.assessment"]
    assert quality.value["assessment_version"] == "not_evaluated"
    assert quality.status.value == "source_missing"


def test_no_embeddings_vector_ranking_or_similarity_features(reference):
    features = _feature_map(reference)
    serialized = json.dumps(sorted(features), ensure_ascii=False)
    for token in ("embedding", "vector", "ranking", "similarity"):
        assert token not in serialized


# 34-40+: CLI, manifests, privacy, existing eligibility -------------------


def test_cli_dry_run_writes_nothing(tmp_path, capsys):
    from saudi_plot_design.cli import main

    asset = tmp_path / "safe.pdf"
    asset.write_bytes(b"safe")
    library = tmp_path / "library"
    result = main(
        [
            "library",
            "ingest",
            "--library-root",
            str(library),
            "--asset",
            str(asset),
            "--case-id",
            "source-case",
            "--case-version",
            "1.0.0",
            "--display-name",
            "Source",
            "--project-type",
            "unknown",
            "--country",
            "SA",
            "--usage-rights-confirmed",
            "--internal-review-permitted",
            "--rights-basis",
            "test",
            "--created-at",
            "2026-07-16T08:00:00+03:00",
            "--created-by",
            "test",
            "--dry-run",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 0 and payload["disposition"] == "dry_run"
    assert not library.exists()


def test_cli_json_output_is_machine_readable(reference, capsys):
    from saudi_plot_design.cli import main

    library, _ = reference
    result = main(["library", "list", "--library-root", str(library), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert len(payload["entries"]) == 3


def test_library_validation_command(reference, capsys):
    from saudi_plot_design.cli import main

    library, _ = reference
    result = main(["library", "validate", "--library-root", str(library), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 0 and payload["passed"] is True


def test_library_manifest_hashes_and_sizes(reference):
    library, _ = reference
    assert verify_library_manifest(library) == ()
    manifest = _read(library / "library_manifest.json")
    for record in manifest["artifacts"]:
        path = library / record["relative_path"]
        assert path.stat().st_size == record["size_bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_no_source_model_is_copied_into_library(reference):
    library, _ = reference
    assert not list(library.rglob("*.ifc"))
    assert not list(library.rglob("*.rvt"))
    assert not list(library.rglob("*.dwg"))


def test_no_private_or_absolute_paths_in_shareable_outputs(reference):
    library, _ = reference
    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in library.rglob("*") if path.is_file()
    ).replace("\\", "/")
    assert "private_cases/" not in serialized
    assert str(library).replace("\\", "/") not in serialized


def test_existing_m6a_eligibility_is_reused(reference):
    _, context = reference
    assert evaluate_template_eligibility(context["villa_case"]).template_eligible is True
    office = context["office_case"]
    if office is not None:
        assert evaluate_template_eligibility(office).template_eligible is False


def test_active_reasons_separate_role_review_and_eligibility(reference):
    library, context = reference
    package, bundle, features = load_case_version(library, context["candidate"].case_id, "1.0.0")
    reasons = active_template_ineligibility_reasons(package, bundle, features)
    assert "case_role_not_approved_template:residential_villa_candidate" in reasons
    assert "review_state_not_approved:requires_review" in reasons
    assert package.template_eligible is True


def test_architect_review_without_approval_stays_inactive(tmp_path):
    _, artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    package, _ = import_m6a_artifacts(
        library_root=tmp_path / "library",
        artifact_root=artifacts,
        case_version="1.0.0",
        case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
        creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
        template_use_permitted=True,
        shareable_outputs_permitted=True,
        rights_basis="synthetic tests",
        synthetic_test_fixture=True,
    )
    reviewed, _ = apply_review(
        library_root=tmp_path / "library",
        case_id=package.case_id,
        from_version="1.0.0",
        new_version="1.1.0",
        decision_type=ReviewDecisionType.ARCHITECT_REVIEWED,
        reviewer_id="reviewer",
        review_date="2026-07-16",
        bound_fingerprint=package.review_binding_fingerprint,
        rationale="reviewed but not approved",
        template_use_approved=False,
        creation_metadata=metadata("2026-07-16T08:01:00+03:00"),
    )
    assert reviewed.review_state is ReviewState.ARCHITECT_REVIEWED
    assert _read(tmp_path / "library" / "active_template_index.json")["entries"] == []


def test_archive_creates_new_version_and_removes_active(tmp_path):
    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    archived, _ = archive_case(
        library_root=library,
        case_id=context["approved"].case_id,
        from_version="1.1.0",
        new_version="1.2.0",
        creation_metadata=metadata("2026-07-16T08:03:00+03:00"),
    )
    assert archived.case_role is CaseRole.ARCHIVED
    assert archived.lifecycle_state is LifecycleState.ARCHIVED
    assert _read(library / "active_template_index.json")["entries"] == []


# Review-fix regressions: path safety, library-wide validation, exit codes ---


@pytest.mark.parametrize("bad_version", ("../../escape", "1.1.0/nested", "..\\up"))
def test_transition_rejects_unsafe_new_version(tmp_path, bad_version):
    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    approved = context["approved"]
    case_dir = library / "project_packages" / approved.case_id
    before = sorted(path.name for path in case_dir.iterdir())
    with pytest.raises(SpdInputError, match="invalid library case version"):
        archive_case(
            library_root=library,
            case_id=approved.case_id,
            from_version=approved.case_version,
            new_version=bad_version,
            creation_metadata=metadata("2026-07-16T08:03:00+03:00"),
        )
    assert sorted(path.name for path in case_dir.iterdir()) == before
    assert not (library / "project_packages" / "escape").exists()


def test_load_rejects_unsafe_case_identifiers(reference):
    library, context = reference
    with pytest.raises(SpdInputError, match="invalid library case"):
        load_case_version(library, "../" + context["approved"].case_id, "1.1.0")
    with pytest.raises(SpdInputError, match="invalid library case"):
        load_case_version(library, context["approved"].case_id, "../1.1.0")


def test_first_version_cannot_supersede(tmp_path):
    _, artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    with pytest.raises(LibraryConflictError, match="first version cannot supersede"):
        import_m6a_artifacts(
            library_root=tmp_path / "library",
            artifact_root=artifacts,
            case_version="1.0.0",
            case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
            creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
            template_use_permitted=True,
            shareable_outputs_permitted=True,
            rights_basis="synthetic fixture testing only",
            synthetic_test_fixture=True,
            supersedes_case_version="0.9.0",
        )
    assert not (tmp_path / "library" / "project_packages").exists()


def _break_version_chain(library: Path, case_id: str) -> None:
    import shutil

    for directory in ("project_packages", "feature_packages", "source_bundle_manifests"):
        shutil.rmtree(library / directory / case_id / "1.0.0", ignore_errors=True)


def test_validate_detects_library_wide_errors(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    _break_version_chain(library, context["approved"].case_id)
    result = main(["library", "validate", "--library-root", str(library), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 3 and payload["passed"] is False
    assert any(
        finding["check_id"] == "M7V-SUPERSEDES-MISSING" for finding in payload["library_errors"]
    )
    assert payload["stale_root_artifacts"]


def test_validate_detects_tampered_active_index(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    build_reference_library(library, tmp_path / "work")
    index_path = library / "active_template_index.json"
    index = _read(index_path)
    index["entries"] = []
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = main(["library", "validate", "--library-root", str(library), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 3 and payload["passed"] is False
    assert "stale root artifact: active_template_index.json" in payload["stale_root_artifacts"]


@pytest.mark.parametrize("tampered", (b"[]\n", b"null\n", b"\xff\xfe not utf-8", b"{ broken"))
def test_validate_survives_tampered_registry_bytes(tmp_path, capsys, tampered):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    build_reference_library(library, tmp_path / "work")
    (library / "library_registry.json").write_bytes(tampered)
    result = main(["library", "validate", "--library-root", str(library), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 3 and payload["passed"] is False
    assert "stale root artifact: library_registry.json" in payload["stale_root_artifacts"]


def test_rebuild_index_reports_validation_failure(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    _break_version_chain(library, context["approved"].case_id)
    result = main(
        [
            "library",
            "rebuild-index",
            "--library-root",
            str(library),
            "--generated-at",
            "2026-07-16T09:00:00+03:00",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 3 and payload["validation_passed"] is False


def test_cli_invalid_created_at_is_input_error(tmp_path, capsys):
    from saudi_plot_design.cli import main

    asset = tmp_path / "safe.pdf"
    asset.write_bytes(b"safe")
    result = main(
        [
            "library",
            "ingest",
            "--library-root",
            str(tmp_path / "library"),
            "--asset",
            str(asset),
            "--case-id",
            "source-case",
            "--case-version",
            "1.0.0",
            "--display-name",
            "Source",
            "--project-type",
            "unknown",
            "--country",
            "SA",
            "--usage-rights-confirmed",
            "--internal-review-permitted",
            "--rights-basis",
            "test",
            "--created-at",
            "not-a-timestamp",
            "--created-by",
            "test",
        ]
    )
    captured = capsys.readouterr()
    assert result == 2
    assert "invalid library input" in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "library").exists()


@pytest.mark.parametrize(
    "bad_path",
    (
        "../outside.json",
        "C:/absolute/path.json",
        "/etc/passwd",
        "C:drive-relative.json",
        "nested/C:file.json",
        "C:\\windows\\style.json",
    ),
)
def test_manifest_record_rejects_unsafe_paths(bad_path):
    from saudi_plot_design.library.models import ArtifactRecord

    with pytest.raises(ValidationError, match="safe relative path"):
        ArtifactRecord(relative_path=bad_path, size_bytes=1, sha256="0" * 64)


@pytest.mark.parametrize("escape_path", ("../outside.json", "C:drive-relative-escape.json"))
def test_tampered_manifest_with_traversal_is_invalid(tmp_path, escape_path):
    library = tmp_path / "library"
    build_reference_library(library, tmp_path / "work")
    manifest_path = library / "library_manifest.json"
    manifest = _read(manifest_path)
    manifest["artifacts"][0]["relative_path"] = escape_path
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    errors = verify_library_manifest(library)
    assert errors and "invalid library_manifest.json" in errors[0]


# Adversarial closeout regressions --------------------------------------


@pytest.mark.parametrize(
    "private_value",
    (
        r"\\server\share\client",
        r"C:client\plan.dwg",
        "/srv/clients/plan.dwg",
        "C:/clients/plan.dwg",
        "/opt/projects/villa",
        "source=(/srv/client/file)",
        "path=/opt/project",
        "/مشاريع/عميل",
    ),
)
def test_private_path_forms_fail_validation_in_free_form_fields(reference, private_value):
    library, context = reference
    package, bundle, features = load_case_version(library, context["approved"].case_id, "1.1.0")
    tampered = package.model_copy(
        update={
            "usage_rights": package.usage_rights.model_copy(update={"rights_basis": private_value})
        }
    )
    findings = validate_project_package(tampered, bundle, features)
    assert any(finding.check_id == "M7V-PRIVACY-PATH" for finding in findings)


def test_version_fork_blocks_current_selection_and_active_index(tmp_path):
    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    case_id = context["approved"].case_id
    # Forge a fork: an internally consistent second version also claiming to
    # supersede 1.0.0 (which 1.1.0 already supersedes).
    _forge_consistent_version(library, case_id, "1.1.0", "1.2.0", "1.0.0")
    registry, index, validation = derive_library_state(
        library, generated_at="2026-07-16T09:00:00+03:00"
    )
    assert any(finding.check_id == "M7V-VERSION-FORK" for finding in validation.findings)
    assert not validation.passed
    assert index.entries == ()
    assert all(entry.is_current is False for entry in registry.entries if entry.case_id == case_id)


@pytest.mark.parametrize(
    ("value", "forbidden"),
    (
        ("https://example.com/license", False),
        ("licensed under https://example.com/terms?path=/x", False),
        ("see ftp://host/dir for terms", False),
        ("file:///srv/private/model.ifc", True),
        ("file://C:/private/model.ifc", True),
        # JSON-escaping doubles backslashes; a drive path must never be
        # mistaken for a one-letter URL scheme after normalization.
        ("C:\\clients\\plan.dwg", True),
        ("stored at C:\\\\clients\\\\plan.dwg", True),
    ),
)
def test_urls_are_not_private_paths_but_file_urls_are(reference, value, forbidden):
    library, context = reference
    package, bundle, features = load_case_version(library, context["approved"].case_id, "1.1.0")
    tampered = package.model_copy(
        update={"usage_rights": package.usage_rights.model_copy(update={"rights_basis": value})}
    )
    findings = validate_project_package(tampered, bundle, features)
    assert any(finding.check_id == "M7V-PRIVACY-PATH" for finding in findings) is forbidden


def test_self_superseding_version_selects_no_current(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    build_reference_library(library, tmp_path / "work")
    # Forge an internally consistent self-superseding version (a one-node
    # cycle) alongside the legitimate head.
    _forge_consistent_version(library, "TEST-OFFICE-001", "1.0.0", "2.0.0", "2.0.0")
    registry, _, validation = derive_library_state(
        library, generated_at="2026-07-16T09:00:00+03:00"
    )
    assert any(finding.check_id == "M7V-VERSION-CYCLE" for finding in validation.findings)
    assert all(
        entry.is_current is False
        for entry in registry.entries
        if entry.case_id == "TEST-OFFICE-001"
    )
    result = main(
        ["library", "show", "--library-root", str(library), "--case-id", "TEST-OFFICE-001"]
    )
    captured = capsys.readouterr()
    assert result == 2 and "ambiguous version chain" in captured.err


def test_unreadable_version_blocks_current_selection_for_its_case(tmp_path):
    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    case_id = context["approved"].case_id
    # Corrupt the NEWEST version; the older approved 1.0.0 chain must not
    # silently become current/active again.
    package_path = library / "project_packages" / case_id / "1.1.0" / "project_case_package.json"
    package_path.write_bytes(b"\xff\xfe corrupted")
    registry, index, validation = derive_library_state(
        library, generated_at="2026-07-16T09:00:00+03:00"
    )
    assert not validation.passed
    assert any(finding.check_id == "M7V-CASE-UNREADABLE-VERSION" for finding in validation.findings)
    assert index.entries == ()
    assert all(entry.is_current is False for entry in registry.entries if entry.case_id == case_id)


def test_show_without_version_rejects_forked_chain(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    case_id = context["approved"].case_id
    _forge_consistent_version(library, case_id, "1.1.0", "1.2.0", "1.0.0")
    result = main(["library", "show", "--library-root", str(library), "--case-id", case_id])
    captured = capsys.readouterr()
    assert result == 2
    assert "ambiguous version chain" in captured.err


def test_import_binds_canonical_fingerprint_to_verified_manifest_hash(tmp_path):
    _, artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    manifest = _read(artifacts / "case_manifest.json")
    package, _ = import_m6a_artifacts(
        library_root=tmp_path / "library",
        artifact_root=artifacts,
        case_version="1.0.0",
        case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
        creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
        template_use_permitted=True,
        shareable_outputs_permitted=True,
        rights_basis="synthetic fixture testing only",
        synthetic_test_fixture=True,
    )
    assert package.canonical_case_fingerprint == manifest["files_sha256"]["architectural_case.json"]


@pytest.mark.parametrize("corruption", (b"\xff\xfe not utf-8", b"{ broken json", b"[]"))
def test_corrupted_stored_package_is_a_validation_failure(tmp_path, capsys, corruption):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    package_path = (
        library
        / "project_packages"
        / context["approved"].case_id
        / "1.1.0"
        / "project_case_package.json"
    )
    package_path.write_bytes(corruption)
    result = main(["library", "validate", "--library-root", str(library), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 3 and payload["passed"] is False
    assert any(
        finding["check_id"] == "M7V-STORED-ARTIFACT-UNREADABLE"
        for finding in payload["library_errors"]
    )


def test_nested_manifest_filename_is_not_invisible(tmp_path):
    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    rogue = (
        library
        / "project_packages"
        / context["approved"].case_id
        / "1.1.0"
        / "library_manifest.json"
    )
    rogue.write_text("{}", encoding="utf-8")
    errors = verify_library_manifest(library)
    assert any(
        "unrecorded artifact" in error and "library_manifest.json" in error for error in errors
    )


@pytest.mark.parametrize(
    ("case_id", "case_version", "match"),
    (
        ("CON", "1.0.0", "reserved Windows device name"),
        ("com3.backup", "1.0.0", "reserved Windows device name"),
        ("source-case", "NUL", "reserved Windows device name"),
        ("source-case", "1.0.", "must not end with a dot"),
        ("case.", "1.0.0", "must not end with a dot"),
    ),
)
def test_windows_unsafe_identifiers_are_rejected(tmp_path, case_id, case_version, match):
    asset = tmp_path / "safe.pdf"
    asset.write_bytes(b"safe")
    with pytest.raises(SpdInputError, match=match):
        ingest_source_bundle(
            library_root=tmp_path / "library",
            asset_paths=(asset,),
            case_id=case_id,
            case_version=case_version,
            display_name="Source",
            project_type="unknown",
            country="SA",
            city=None,
            architectural_character=None,
            creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
            usage_rights=_rights(),
            confidentiality=_confidentiality(),
        )


def test_case_insensitive_identifier_aliasing_is_rejected(tmp_path):
    asset = tmp_path / "safe.pdf"
    asset.write_bytes(b"safe")
    common = dict(
        library_root=tmp_path / "library",
        asset_paths=(asset,),
        display_name="Source",
        project_type="unknown",
        country="SA",
        city=None,
        architectural_character=None,
        creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
        usage_rights=_rights(),
        confidentiality=_confidentiality(),
    )
    ingest_source_bundle(case_id="source-case", case_version="1.0.0", **common)
    with pytest.raises(LibraryConflictError, match="differs only by letter case"):
        ingest_source_bundle(case_id="SOURCE-CASE", case_version="1.0.0", **common)


def test_private_path_in_free_form_input_is_rejected_before_writing(tmp_path):
    asset = tmp_path / "safe.pdf"
    asset.write_bytes(b"safe")
    with pytest.raises(SpdInputError, match="M7V-PRIVACY-PATH"):
        ingest_source_bundle(
            library_root=tmp_path / "library",
            asset_paths=(asset,),
            case_id="source-case",
            case_version="1.0.0",
            display_name="Source",
            project_type="unknown",
            country="SA",
            city=None,
            architectural_character=None,
            creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
            usage_rights=UsageRights(
                ingestion_permitted=True,
                internal_review_permitted=True,
                template_use_permitted=False,
                rights_basis="/srv/clients/secret-agreement.pdf",
            ),
            confidentiality=_confidentiality(),
        )
    assert not (tmp_path / "library" / "project_packages").exists()


def test_missing_predecessor_blocks_current_and_active(tmp_path):
    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    case_id = context["approved"].case_id
    _break_version_chain(library, case_id)
    registry, index, validation = derive_library_state(
        library, generated_at="2026-07-16T09:00:00+03:00"
    )
    assert not validation.passed
    assert index.entries == ()
    assert all(entry.is_current is False for entry in registry.entries if entry.case_id == case_id)


def test_version_missing_its_package_file_is_reported(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    package_path = (
        library
        / "project_packages"
        / context["approved"].case_id
        / "1.1.0"
        / "project_case_package.json"
    )
    package_path.unlink()
    result = main(["library", "validate", "--library-root", str(library), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 3 and payload["passed"] is False
    assert any(
        finding["check_id"] == "M7V-STORED-ARTIFACT-UNREADABLE"
        and finding["case_version"] == "1.1.0"
        for finding in payload["library_errors"]
    )


def test_cli_approval_reports_real_active_state(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    _, villa_artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    candidate, _ = import_m6a_artifacts(
        library_root=library,
        artifact_root=villa_artifacts,
        case_version="1.0.0",
        case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
        creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
        template_use_permitted=True,
        shareable_outputs_permitted=True,
        rights_basis="synthetic fixture explicitly permitted for automated tests",
        synthetic_test_fixture=True,
    )
    result = main(
        [
            "library",
            "apply-review",
            "--library-root",
            str(library),
            "--case-id",
            candidate.case_id,
            "--from-version",
            "1.0.0",
            "--new-version",
            "1.1.0",
            "--decision",
            "approved",
            "--reviewed-by",
            "synthetic-test-reviewer",
            "--review-date",
            "2026-07-16",
            "--bound-fingerprint",
            candidate.review_binding_fingerprint,
            "--rationale",
            "Approved only for deterministic automated library tests.",
            "--approve-template-use",
            "--created-at",
            "2026-07-16T08:01:00+03:00",
            "--created-by",
            "test",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["active_template"] is True


@pytest.mark.parametrize("manifest_json", ("null", "[]", '"text"'))
def test_non_object_m6a_manifest_is_an_input_error(tmp_path, manifest_json):
    _, artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    (artifacts / "case_manifest.json").write_text(manifest_json, encoding="utf-8")
    with pytest.raises(SpdInputError, match="JSON object"):
        import_m6a_artifacts(
            library_root=tmp_path / "library",
            artifact_root=artifacts,
            case_version="1.0.0",
            case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
            creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
            template_use_permitted=True,
            shareable_outputs_permitted=True,
            rights_basis="synthetic fixture testing only",
            synthetic_test_fixture=True,
        )


@pytest.mark.parametrize("artifact", ("provenance.json", "validation.json"))
def test_version_missing_provenance_or_validation_is_reported(tmp_path, capsys, artifact):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    target = library / "project_packages" / context["approved"].case_id / "1.1.0" / artifact
    target.unlink()
    result = main(["library", "validate", "--library-root", str(library), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 3 and payload["passed"] is False
    assert any(
        finding["check_id"] == "M7V-STORED-ARTIFACT-UNREADABLE"
        for finding in payload["library_errors"]
    )


def test_mismatched_provenance_file_is_reported(tmp_path):
    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    target = (
        library / "project_packages" / context["approved"].case_id / "1.1.0" / "provenance.json"
    )
    payload = _read(target)
    payload["statement"] = "tampered statement"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(SpdInputError, match="does not match the stored package"):
        load_case_version(library, context["approved"].case_id, "1.1.0")


def test_non_utf8_manifest_is_invalid_not_a_crash(tmp_path):
    library = tmp_path / "library"
    build_reference_library(library, tmp_path / "work")
    (library / "library_manifest.json").write_bytes(b"\xff\xfe broken")
    errors = verify_library_manifest(library)
    assert errors and "invalid library_manifest.json" in errors[0]


def test_unsupported_manifest_schema_version_is_invalid(tmp_path):
    library = tmp_path / "library"
    build_reference_library(library, tmp_path / "work")
    manifest_path = library / "library_manifest.json"
    payload = _read(manifest_path)
    payload["library_manifest_schema_version"] = 3
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    errors = verify_library_manifest(library)
    assert errors and "unsupported schema version" in errors[0]


def test_old_v1_manifest_layout_is_rejected_not_misread(tmp_path):
    library = tmp_path / "library"
    build_reference_library(library, tmp_path / "work")
    manifest_path = library / "library_manifest.json"
    payload = _read(manifest_path)
    # Reconstruct the pre-fingerprint v1 layout.
    payload["library_manifest_schema_version"] = 1
    payload.pop("root_fingerprint")
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    errors = verify_library_manifest(library)
    assert errors and "invalid library_manifest.json" in errors[0]


def test_root_artifacts_carry_current_schema_versions(reference):
    from saudi_plot_design.library.models import (
        LIBRARY_MANIFEST_SCHEMA_VERSION,
        REGISTRY_SCHEMA_VERSION,
    )

    library, _ = reference
    registry = _read(library / "library_registry.json")
    manifest = _read(library / "library_manifest.json")
    assert registry["registry_schema_version"] == REGISTRY_SCHEMA_VERSION == 3
    assert manifest["library_manifest_schema_version"] == LIBRARY_MANIFEST_SCHEMA_VERSION == 2
    assert all("package_lifecycle_state" in entry for entry in registry["entries"])


def test_unsupported_feature_schema_version_is_rejected(reference):
    library, context = reference
    package, bundle, features = load_case_version(library, context["approved"].case_id, "1.1.0")
    assert features is not None
    tampered = features.model_copy(update={"feature_schema_version": 2})
    findings = validate_project_package(package, bundle, tampered)
    assert any(finding.check_id == "M7V-SCHEMA-FEATURE" for finding in findings)


def _forge_consistent_version(library, case_id, source_version, new_version, supersedes):
    """Write an internally consistent forged version, bypassing write gates."""
    from saudi_plot_design.library.fingerprints import finalize_package
    from saudi_plot_design.library.models import LibraryValidationReport
    from saudi_plot_design.library.storage import (
        bundle_version_dir,
        feature_version_dir,
        json_bytes,
        project_version_dir,
    )
    from saudi_plot_design.library.validation import feature_relative_path

    package, bundle, features = load_case_version(library, case_id, source_version)
    feature_ref = package.extracted_features.model_copy(
        update={"relative_path": feature_relative_path(case_id, new_version)}
    )
    forged = finalize_package(
        package.model_copy(
            update={
                "case_version": new_version,
                "supersedes_case_version": supersedes,
                "extracted_features": feature_ref,
                "package_fingerprint": "0" * 64,
            }
        )
    )
    forged_bundle = bundle.model_copy(update={"case_version": new_version})
    forged_features = features.model_copy(update={"case_version": new_version})
    findings = validate_project_package(forged, forged_bundle, forged_features)
    assert not [finding for finding in findings if finding.severity == "error"]
    validation = LibraryValidationReport(
        generated_at=forged.creation_metadata.created_at,
        passed=True,
        findings=findings,
        checked_case_versions=1,
        active_template_count=0,
    )
    project_dir = project_version_dir(library, case_id, new_version)
    bundle_dir = bundle_version_dir(library, case_id, new_version)
    feature_dir = feature_version_dir(library, case_id, new_version)
    for directory in (project_dir, bundle_dir, feature_dir):
        directory.mkdir(parents=True)
    (project_dir / "project_case_package.json").write_bytes(
        json_bytes(forged.model_dump(mode="json"))
    )
    (project_dir / "provenance.json").write_bytes(
        json_bytes(forged.provenance.model_dump(mode="json"))
    )
    (project_dir / "validation.json").write_bytes(json_bytes(validation.model_dump(mode="json")))
    (bundle_dir / "asset_manifest.json").write_bytes(
        json_bytes(forged_bundle.model_dump(mode="json"))
    )
    (feature_dir / "template_features.json").write_bytes(
        json_bytes(forged_features.model_dump(mode="json"))
    )


def test_disconnected_cycle_blocks_current_selection(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    case_id = context["approved"].case_id
    # Forge a cyclic component (2.0.0 <-> 2.1.0) disconnected from the
    # legitimate head 1.1.0.
    _forge_consistent_version(library, case_id, "1.1.0", "2.0.0", "2.1.0")
    _forge_consistent_version(library, case_id, "1.1.0", "2.1.0", "2.0.0")
    registry, index, validation = derive_library_state(
        library, generated_at="2026-07-16T09:00:00+03:00"
    )
    assert any(finding.check_id == "M7V-VERSION-CYCLE" for finding in validation.findings)
    assert not validation.passed
    assert index.entries == ()
    assert all(entry.is_current is False for entry in registry.entries if entry.case_id == case_id)
    result = main(["library", "show", "--library-root", str(library), "--case-id", case_id])
    captured = capsys.readouterr()
    assert result == 2 and "ambiguous version chain" in captured.err


def test_tampered_validation_report_is_reported(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    target = (
        library / "project_packages" / context["approved"].case_id / "1.1.0" / "validation.json"
    )
    payload = _read(target)
    payload["passed"] = False
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = main(["library", "validate", "--library-root", str(library), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert result == 3 and out["passed"] is False
    assert any(
        finding["check_id"] == "M7V-STORED-ARTIFACT-UNREADABLE" for finding in out["library_errors"]
    )


def test_bundle_creation_metadata_is_bound_to_package(reference):
    library, context = reference
    package, bundle, features = load_case_version(library, context["approved"].case_id, "1.1.0")
    tampered = bundle.model_copy(
        update={"creation_metadata": metadata("2027-01-01T00:00:00+00:00")}
    )
    findings = validate_project_package(package, tampered, features)
    assert any(finding.check_id == "M7V-BUNDLE-METADATA" for finding in findings)


def test_tampered_bundle_metadata_on_disk_fails_validation(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    target = (
        library
        / "source_bundle_manifests"
        / context["approved"].case_id
        / "1.1.0"
        / "asset_manifest.json"
    )
    payload = _read(target)
    payload["creation_metadata"]["created_by"] = "tampered"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = main(["library", "validate", "--library-root", str(library), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert result == 3 and out["passed"] is False


def test_renamed_version_directories_are_reported(tmp_path, capsys):
    import shutil

    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    case_id = context["approved"].case_id
    for directory in ("project_packages", "source_bundle_manifests", "feature_packages"):
        source = library / directory / case_id / "1.1.0"
        if source.exists():
            shutil.move(str(source), str(library / directory / case_id / "9.9.9"))
    result = main(["library", "validate", "--library-root", str(library), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 3 and payload["passed"] is False
    assert any(
        finding["check_id"] == "M7V-STORED-ARTIFACT-UNREADABLE"
        and finding["case_version"] == "9.9.9"
        for finding in payload["library_errors"]
    )


def test_json_error_output_is_machine_readable(tmp_path, capsys):
    from saudi_plot_design.cli import main

    result = main(
        [
            "library",
            "show",
            "--library-root",
            str(tmp_path / "missing-library"),
            "--case-id",
            "absent-case",
            "--json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 2
    assert payload["exit_code"] == 2
    assert "absent-case" in payload["error"]


def test_room_geometry_is_never_reported_fully_extracted(reference):
    rooms = _feature_map(reference)["room_geometry.rooms"]
    assert rooms.status.value == "requires_review"
    assert rooms.value, "room records must still carry the available area/contact data"
    assert all(room["area_m2"] is not None for room in rooms.value)
    assert all(room["clear_width_m"] is None for room in rooms.value)


def test_unsupported_m6a_case_schema_version_is_rejected(tmp_path):
    _, artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    canonical_path = artifacts / "architectural_case.json"
    payload = _read(canonical_path)
    payload["schema_version"] = 99
    canonical_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    canonical_path.write_bytes(canonical_bytes)
    manifest_path = artifacts / "case_manifest.json"
    manifest = _read(manifest_path)
    manifest["files_sha256"]["architectural_case.json"] = hashlib.sha256(
        canonical_bytes
    ).hexdigest()
    manifest["schema_version"] = 99
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(SpdInputError, match="unsupported M6A case schema version"):
        import_m6a_artifacts(
            library_root=tmp_path / "library",
            artifact_root=artifacts,
            case_version="1.0.0",
            case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
            creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
            template_use_permitted=True,
            shareable_outputs_permitted=True,
            rights_basis="synthetic fixture testing only",
            synthetic_test_fixture=True,
        )


def test_non_utf8_m6a_manifest_is_an_input_error(tmp_path):
    _, artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    (artifacts / "case_manifest.json").write_bytes(b"\xff\xfe broken")
    with pytest.raises(SpdInputError, match="failed schema validation"):
        import_m6a_artifacts(
            library_root=tmp_path / "library",
            artifact_root=artifacts,
            case_version="1.0.0",
            case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
            creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
            template_use_permitted=True,
            shareable_outputs_permitted=True,
            rights_basis="synthetic fixture testing only",
            synthetic_test_fixture=True,
        )


def test_argparse_usage_error_keeps_json_contract(capsys):
    from saudi_plot_design.cli import main

    result = main(["library", "ingest", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1])
    assert result == 2
    assert payload["exit_code"] == 2
    assert "invalid library command arguments" in payload["error"]


# Final closeout regressions: manifest metadata, list state, idempotency ----


def test_unchanged_manifest_passes_validation(reference, capsys):
    from saudi_plot_design.cli import main

    library, _ = reference
    result = main(["library", "validate", "--library-root", str(library), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 0 and payload["passed"] is True
    assert payload["stale_root_artifacts"] == []


def test_tampered_manifest_generated_at_fails_validation(tmp_path, capsys):
    from saudi_plot_design.cli import main
    from saudi_plot_design.library.fingerprints import calculate_manifest_root_fingerprint
    from saudi_plot_design.library.models import LibraryManifest

    library = tmp_path / "library"
    build_reference_library(library, tmp_path / "work")
    manifest_path = library / "library_manifest.json"
    payload = _read(manifest_path)
    payload["generated_at"] = "2030-01-01T00:00:00+00:00"
    # Even a "smart" attacker who recomputes the root fingerprint for the new
    # timestamp must be caught by the validate-time rederivation.
    tampered = LibraryManifest.model_validate({**payload, "root_fingerprint": "0" * 64})
    payload["root_fingerprint"] = calculate_manifest_root_fingerprint(tampered)
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = main(["library", "validate", "--library-root", str(library), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert result == 3 and out["passed"] is False
    assert "stale root artifact: library_manifest.json" in out["stale_root_artifacts"]


def test_tampered_generated_at_without_fingerprint_update_is_invalid(tmp_path):
    library = tmp_path / "library"
    build_reference_library(library, tmp_path / "work")
    manifest_path = library / "library_manifest.json"
    payload = _read(manifest_path)
    payload["generated_at"] = "2030-01-01T00:00:00+00:00"
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    errors = verify_library_manifest(library)
    assert errors and "root fingerprint" in errors[0]


def test_malformed_manifest_generated_at_fails_cleanly(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    build_reference_library(library, tmp_path / "work")
    manifest_path = library / "library_manifest.json"
    payload = _read(manifest_path)
    payload["generated_at"] = "not-a-timestamp"
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    errors = verify_library_manifest(library)
    assert errors and "invalid library_manifest.json" in errors[0]
    result = main(["library", "validate", "--library-root", str(library), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert result == 3 and out["passed"] is False


def test_manifest_rebuild_is_deterministic_under_controlled_metadata(reference, tmp_path):
    from saudi_plot_design.library.storage import derive_library_manifest

    library, _ = reference
    stored = _read(library / "library_manifest.json")
    rederived = derive_library_manifest(library, generated_at=stored["generated_at"])
    assert rederived.model_dump(mode="json") == stored


def test_list_distinguishes_current_superseded_and_active(reference, capsys):
    from saudi_plot_design.cli import main

    library, context = reference
    case_id = context["approved"].case_id
    result = main(["library", "list", "--library-root", str(library), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 0 and payload["validation_passed"] is True
    by_key = {(entry["case_id"], entry["case_version"]): entry for entry in payload["entries"]}

    superseded = by_key[(case_id, "1.0.0")]
    assert superseded["package_lifecycle_state"] == "requires_review"
    assert superseded["effective_lifecycle_state"] == "superseded"
    assert superseded["is_current"] is False
    assert superseded["superseded"] is True
    assert superseded["active_template"] is False

    current = by_key[(case_id, "1.1.0")]
    assert current["package_lifecycle_state"] == "approved"
    assert current["effective_lifecycle_state"] == "approved"
    assert current["is_current"] is True
    assert current["superseded"] is False
    assert current["active_template"] is True

    office = by_key[("TEST-OFFICE-001", "1.0.0")]
    assert office["case_role"] == "ingestion_stress_test"
    assert office["is_current"] is True
    assert office["active_template"] is False


def test_list_superseded_approved_version_is_not_active(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    case_id = context["approved"].case_id
    # Archive the approved 1.1.0: the formerly approved version becomes
    # superseded and must not read as the active approved template.
    archive_case(
        library_root=library,
        case_id=case_id,
        from_version="1.1.0",
        new_version="1.2.0",
        creation_metadata=metadata("2026-07-16T08:03:00+03:00"),
    )
    result = main(["library", "list", "--library-root", str(library), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    by_key = {(entry["case_id"], entry["case_version"]): entry for entry in payload["entries"]}

    formerly_approved = by_key[(case_id, "1.1.0")]
    assert formerly_approved["package_lifecycle_state"] == "approved"
    assert formerly_approved["effective_lifecycle_state"] == "superseded"
    assert formerly_approved["is_current"] is False
    assert formerly_approved["active_template"] is False

    archived = by_key[(case_id, "1.2.0")]
    assert archived["package_lifecycle_state"] == "archived"
    assert archived["is_current"] is True
    assert archived["active_template"] is False


def test_list_human_and_json_agree(reference, capsys):
    from saudi_plot_design.cli import main

    library, _ = reference
    main(["library", "list", "--library-root", str(library), "--json"])
    json_entries = json.loads(capsys.readouterr().out)["entries"]
    main(["library", "list", "--library-root", str(library)])
    human = capsys.readouterr().out
    for entry in json_entries:
        assert f"{entry['case_id']}/{entry['case_version']}" in human
        assert f"package={entry['package_lifecycle_state']}" in human
        assert f"effective={entry['effective_lifecycle_state']}" in human
        expected_status = "current" if entry["is_current"] else "superseded"
        expected_active = "active-template" if entry["active_template"] else "inactive"
        assert f"[{expected_status}, {expected_active}]" in human
    private_root = str(library).replace("\\", "/")
    assert private_root not in human.replace("\\", "/")


def test_apply_review_replay_is_idempotent(tmp_path):
    library = tmp_path / "library"
    _, villa_artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    candidate, _ = import_m6a_artifacts(
        library_root=library,
        artifact_root=villa_artifacts,
        case_version="1.0.0",
        case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
        creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
        template_use_permitted=True,
        shareable_outputs_permitted=True,
        rights_basis="synthetic fixture explicitly permitted for automated tests",
        synthetic_test_fixture=True,
    )
    kwargs = dict(
        library_root=library,
        case_id=candidate.case_id,
        from_version="1.0.0",
        new_version="1.1.0",
        decision_type=ReviewDecisionType.APPROVED,
        reviewer_id="synthetic-test-reviewer",
        review_date="2026-07-16",
        bound_fingerprint=candidate.review_binding_fingerprint,
        rationale="Approved only for deterministic automated library tests.",
        template_use_approved=True,
        creation_metadata=metadata("2026-07-16T08:01:00+03:00"),
    )
    first, created_first = apply_review(**kwargs)
    roots_before = {
        name: (library / name).read_bytes()
        for name in ("library_registry.json", "active_template_index.json", "library_manifest.json")
    }
    replay, created_replay = apply_review(**kwargs)
    assert created_first is True and created_replay is False
    assert first == replay
    # An idempotent replay must not rewrite root artifacts.
    for name, before in roots_before.items():
        assert (library / name).read_bytes() == before, name
    versions = [
        path.name
        for path in (library / "project_packages" / candidate.case_id).iterdir()
        if path.is_dir()
    ]
    assert sorted(versions) == ["1.0.0", "1.1.0"]
    with pytest.raises(LibraryConflictError, match="immutable"):
        apply_review(**{**kwargs, "rationale": "a conflicting different rationale"})


def test_replay_repairs_roots_after_interrupted_first_attempt(tmp_path, monkeypatch):
    import saudi_plot_design.library.commands as commands_module

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    kwargs = dict(
        library_root=library,
        case_id=context["approved"].case_id,
        from_version="1.1.0",
        new_version="1.2.0",
        creation_metadata=metadata("2026-07-16T08:03:00+03:00"),
    )

    def simulated_crash(*args, **kw):
        raise RuntimeError("simulated crash between write and rebuild")

    monkeypatch.setattr(commands_module, "rebuild_library", simulated_crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
        archive_case(**kwargs)
    monkeypatch.undo()
    # The immutable version was written but the roots are stale: the
    # archived template still reads as active.
    assert _read(library / "active_template_index.json")["entries"]

    archived, created = archive_case(**kwargs)
    assert created is False
    assert archived.case_role is CaseRole.ARCHIVED
    # The retry finished the interrupted rebuild.
    assert _read(library / "active_template_index.json")["entries"] == []
    _, _, validation, stale = commands_module._derive_state_and_stale_roots(library)
    assert validation.passed and stale == []


def test_old_replay_refuses_root_repair_and_preserves_state(tmp_path):
    library = tmp_path / "library"
    _, office_artifacts, _ = build_office_stress_artifacts(tmp_path / "office-work")
    context = build_reference_library(library, tmp_path / "work", office_artifacts=office_artifacts)
    assert context["approved"].case_version == "1.1.0"
    registry_before = (library / "library_registry.json").read_bytes()
    newest = json.loads(registry_before)["generated_at"]
    # Only the manifest goes stale; an OLD identical replay must not guess a
    # repair timestamp - it refuses and directs to an explicit rebuild.
    (library / "library_manifest.json").unlink()
    replay = dict(
        library_root=library,
        artifact_root=office_artifacts,
        case_version="1.0.0",
        case_role=CaseRole.INGESTION_STRESS_TEST,
        creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
        template_use_permitted=False,
        shareable_outputs_permitted=False,
        rights_basis="internal ingestion and validation testing only",
    )
    with pytest.raises(SpdInputError, match="rebuild-index"):
        import_m6a_artifacts(**replay)
    # No root artifact was rewritten by the refused replay.
    assert (library / "library_registry.json").read_bytes() == registry_before
    assert not (library / "library_manifest.json").exists()
    # The documented explicit repair restores a verified state.
    rebuild_library(library, generated_at=newest)
    assert verify_library_manifest(library) == ()
    assert _read(library / "library_manifest.json")["generated_at"] == newest


def test_old_replay_refuses_repair_when_registry_root_is_lost(tmp_path):
    library = tmp_path / "library"
    _, office_artifacts, _ = build_office_stress_artifacts(tmp_path / "office-work")
    build_reference_library(library, tmp_path / "work", office_artifacts=office_artifacts)
    index_before = (library / "active_template_index.json").read_bytes()
    newest = json.loads(index_before)["generated_at"]
    # The registry root itself is lost; an OLD replay must not rebuild with
    # its own older timestamp (nor epoch) - the surviving self-consistent
    # roots are newer, so it refuses.
    (library / "library_registry.json").unlink()
    with pytest.raises(SpdInputError, match="rebuild-index"):
        import_m6a_artifacts(
            library_root=library,
            artifact_root=office_artifacts,
            case_version="1.0.0",
            case_role=CaseRole.INGESTION_STRESS_TEST,
            creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
            template_use_permitted=False,
            shareable_outputs_permitted=False,
            rights_basis="internal ingestion and validation testing only",
        )
    assert (library / "active_template_index.json").read_bytes() == index_before
    assert not (library / "library_registry.json").exists()
    rebuild_library(library, generated_at=newest)
    assert _read(library / "library_registry.json")["generated_at"] == newest
    assert verify_library_manifest(library) == ()


def test_replay_never_launders_tampered_future_timestamp(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    _, office_artifacts, _ = build_office_stress_artifacts(tmp_path / "office-work")
    build_reference_library(library, tmp_path / "work", office_artifacts=office_artifacts)
    registry_before = (library / "library_registry.json").read_bytes()
    # Tamper only the manifest's timestamp to a future value; the replay must
    # not rebuild the library around it (which would launder the tampering
    # into a state that passes validation).
    manifest_path = library / "library_manifest.json"
    payload = _read(manifest_path)
    payload["generated_at"] = "2030-01-01T00:00:00+00:00"
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(SpdInputError, match="rebuild-index"):
        import_m6a_artifacts(
            library_root=library,
            artifact_root=office_artifacts,
            case_version="1.0.0",
            case_role=CaseRole.INGESTION_STRESS_TEST,
            creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
            template_use_permitted=False,
            shareable_outputs_permitted=False,
            rights_basis="internal ingestion and validation testing only",
        )
    # Nothing was rewritten and the tampering still fails validation.
    assert (library / "library_registry.json").read_bytes() == registry_before
    result = main(["library", "validate", "--library-root", str(library), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert result == 3 and out["passed"] is False


def test_latest_replay_also_refuses_tampered_future_claim(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    manifest_path = library / "library_manifest.json"
    payload = _read(manifest_path)
    payload["generated_at"] = "2030-01-01T00:00:00+00:00"
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Replaying even the NEWEST operation must not rebuild over a future
    # tampered claim - the parseable claim vetoes auto-repair.
    with pytest.raises(SpdInputError, match="rebuild-index"):
        apply_review(
            library_root=library,
            case_id=context["candidate"].case_id,
            from_version="1.0.0",
            new_version="1.1.0",
            decision_type=ReviewDecisionType.APPROVED,
            reviewer_id="synthetic-test-reviewer",
            review_date="2026-07-16",
            bound_fingerprint=context["candidate"].review_binding_fingerprint,
            rationale="Approved only for deterministic automated library tests.",
            template_use_approved=True,
            creation_metadata=metadata("2026-07-16T08:02:00+03:00"),
        )
    result = main(["library", "validate", "--library-root", str(library), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert result == 3 and out["passed"] is False


def test_surviving_summary_timestamp_vetoes_backdated_repair(tmp_path):
    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    # A later explicit rebuild stamps all roots at 09:00.
    rebuild_library(library, generated_at="2026-07-16T09:00:00+03:00")
    summary_before = (library / "library_summary.md").read_bytes()
    # All four JSON roots are lost; only the summary survives with the newer
    # controlled timestamp. Replaying the newest operation (08:02) must not
    # roll the surviving claim backward.
    for name in (
        "library_registry.json",
        "active_template_index.json",
        "validation_report.json",
        "library_manifest.json",
    ):
        (library / name).unlink()
    with pytest.raises(SpdInputError, match="rebuild-index"):
        apply_review(
            library_root=library,
            case_id=context["candidate"].case_id,
            from_version="1.0.0",
            new_version="1.1.0",
            decision_type=ReviewDecisionType.APPROVED,
            reviewer_id="synthetic-test-reviewer",
            review_date="2026-07-16",
            bound_fingerprint=context["candidate"].review_binding_fingerprint,
            rationale="Approved only for deterministic automated library tests.",
            template_use_approved=True,
            creation_metadata=metadata("2026-07-16T08:02:00+03:00"),
        )
    assert (library / "library_summary.md").read_bytes() == summary_before
    assert not (library / "library_registry.json").exists()


def test_archive_replay_is_idempotent_via_cli(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    argv = [
        "library",
        "archive",
        "--library-root",
        str(library),
        "--case-id",
        context["approved"].case_id,
        "--from-version",
        "1.1.0",
        "--new-version",
        "1.2.0",
        "--created-at",
        "2026-07-16T08:03:00+03:00",
        "--created-by",
        "test",
        "--json",
    ]
    assert main(argv) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(argv) == 0
    replay = json.loads(capsys.readouterr().out)
    assert first["disposition"] == "created"
    assert replay["disposition"] == "idempotent"
    main(argv[:-1])
    human = capsys.readouterr().out
    assert "idempotent" in human


def test_non_confidential_import_is_not_marked_anonymized(reference):
    _, context = reference
    candidate = context["candidate"]
    assert candidate.confidentiality.status == "internal"
    assert candidate.confidentiality.anonymized is False


def test_package_validation_is_machine_readable(reference):
    library, context = reference
    package, bundle, features = load_case_version(library, context["approved"].case_id, "1.1.0")
    findings = validate_project_package(package, bundle, features)
    assert all(
        hasattr(finding, "check_id") and hasattr(finding, "severity") for finding in findings
    )
    assert not [finding for finding in findings if finding.severity == "error"]


# Codex review-gate fixes ---------------------------------------------------


def test_identical_retry_completes_interrupted_version_write(tmp_path):
    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    case_id = context["approved"].case_id
    kwargs = dict(
        library_root=library,
        case_id=case_id,
        from_version="1.1.0",
        new_version="1.2.0",
        creation_metadata=metadata("2026-07-16T08:03:00+03:00"),
    )
    archived, created = archive_case(**kwargs)
    assert created is True
    written = {
        path: path.read_bytes()
        for name in ("project_packages", "source_bundle_manifests", "feature_packages")
        for path in (library / name / case_id / "1.2.0").rglob("*")
        if path.is_file()
    }
    roots_after_full_write = (library / "library_registry.json").read_bytes()
    # Simulate a hard kill after only some immutable artifacts reached disk.
    interrupted = [
        path
        for path in written
        if path.name in {"validation.json", "asset_manifest.json", "template_features.json"}
    ]
    assert interrupted
    for path in interrupted:
        path.unlink()
    retried, retried_created = archive_case(**kwargs)
    assert retried_created is True
    assert retried == archived
    for path, content in written.items():
        assert path.read_bytes() == content, path
    assert (library / "library_registry.json").read_bytes() == roots_after_full_write
    _, _, validation = derive_library_state(
        library, generated_at=archived.creation_metadata.created_at
    )
    assert validation.passed


def test_differing_retry_still_conflicts_after_interrupted_write(tmp_path):
    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    case_id = context["approved"].case_id
    kwargs = dict(
        library_root=library,
        case_id=case_id,
        from_version="1.1.0",
        new_version="1.2.0",
        creation_metadata=metadata("2026-07-16T08:03:00+03:00"),
    )
    archive_case(**kwargs)
    version_dir = library / "project_packages" / case_id / "1.2.0"
    (version_dir / "validation.json").unlink()
    # A retry with different content must not "complete" the interrupted
    # write, and foreign bytes in the version directory must still conflict.
    with pytest.raises(LibraryConflictError, match="immutable"):
        archive_case(**{**kwargs, "creation_metadata": metadata("2026-07-16T09:00:00+03:00")})
    (version_dir / "unexpected_extra.json").write_bytes(b"{}")
    with pytest.raises(LibraryConflictError, match="immutable"):
        archive_case(**kwargs)


def test_mutation_reports_failed_library_validation(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    villa_id = context["approved"].case_id
    # Strip a required immutable artifact from an unrelated stored version.
    (library / "project_packages" / villa_id / "1.0.0" / "provenance.json").unlink()
    result = main(
        [
            "library",
            "archive",
            "--library-root",
            str(library),
            "--case-id",
            "TEST-OFFICE-001",
            "--from-version",
            "1.0.0",
            "--new-version",
            "1.1.0",
            "--created-at",
            "2026-07-16T08:05:00+03:00",
            "--created-by",
            "test",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 3
    assert payload["disposition"] == "created"
    assert payload["library_validation_passed"] is False
    assert any(
        finding["check_id"] == "M7V-CASE-UNREADABLE-VERSION"
        for finding in payload["library_errors"]
    )


def test_healthy_mutation_reports_passing_validation(tmp_path, capsys):
    from saudi_plot_design.cli import main

    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    result = main(
        [
            "library",
            "archive",
            "--library-root",
            str(library),
            "--case-id",
            context["approved"].case_id,
            "--from-version",
            "1.1.0",
            "--new-version",
            "1.2.0",
            "--created-at",
            "2026-07-16T08:05:00+03:00",
            "--created-by",
            "test",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["library_validation_passed"] is True
    assert "library_errors" not in payload


def test_registry_and_active_index_mark_synthetic_fixtures(reference):
    from saudi_plot_design.library.models import SYNTHETIC_FIXTURE_DISCLAIMER

    library, _ = reference
    registry = _read(library / "library_registry.json")
    by_case = {(entry["case_id"], entry["case_version"]): entry for entry in registry["entries"]}
    assert by_case[("SYNTHETIC-VILLA-TEST-001", "1.1.0")]["synthetic_test_fixture"] is True
    assert by_case[("TEST-OFFICE-001", "1.0.0")]["synthetic_test_fixture"] is False
    index = _read(library / "active_template_index.json")
    assert index["entries"], "reference fixture activates the synthetic villa"
    for entry in index["entries"]:
        assert entry["synthetic_test_fixture"] is True
        assert entry["test_data_disclaimer"] == SYNTHETIC_FIXTURE_DISCLAIMER
    summary = (library / "library_summary.md").read_text(encoding="utf-8")
    assert SYNTHETIC_FIXTURE_DISCLAIMER in summary


def test_active_entry_disclaimer_is_enforced_by_schema(reference):
    from saudi_plot_design.library.models import SYNTHETIC_FIXTURE_DISCLAIMER

    library, _ = reference
    index = _read(library / "active_template_index.json")
    entry = dict(index["entries"][0])
    from saudi_plot_design.library.models import ActiveTemplateEntry

    entry_no_disclaimer = {**entry, "test_data_disclaimer": None}
    with pytest.raises(ValidationError, match="verbatim test-data disclaimer"):
        ActiveTemplateEntry.model_validate(entry_no_disclaimer)
    entry_fake_real = {**entry, "synthetic_test_fixture": False}
    with pytest.raises(ValidationError, match="only synthetic test fixtures"):
        ActiveTemplateEntry.model_validate(entry_fake_real)
    assert entry["test_data_disclaimer"] == SYNTHETIC_FIXTURE_DISCLAIMER


def test_known_synthetic_fixture_cannot_shed_its_marker(tmp_path):
    _, villa_artifacts, _ = build_synthetic_villa_artifacts(tmp_path / "fixture")
    with pytest.raises(SpdInputError, match="M7V-SYNTHETIC-PROVENANCE"):
        import_m6a_artifacts(
            library_root=tmp_path / "library",
            artifact_root=villa_artifacts,
            case_version="1.0.0",
            case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
            creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
            template_use_permitted=True,
            shareable_outputs_permitted=True,
            rights_basis="synthetic fixture explicitly permitted for automated tests",
            synthetic_test_fixture=False,
        )


def test_stale_retry_cannot_fork_after_new_current_version(tmp_path):
    library = tmp_path / "library"
    context = build_reference_library(library, tmp_path / "work")
    case_id = context["approved"].case_id
    # A stale operation targeting 1.2.0 created its directory, then died
    # before writing any artifact.
    (library / "project_packages" / case_id / "1.2.0").mkdir(parents=True)
    # Another operation legitimately moves the chain forward.
    archive_case(
        library_root=library,
        case_id=case_id,
        from_version="1.1.0",
        new_version="1.3.0",
        creation_metadata=metadata("2026-07-16T08:04:00+03:00"),
    )
    # The stale retry must refuse to write a second successor of 1.1.0.
    with pytest.raises(LibraryConflictError):
        archive_case(
            library_root=library,
            case_id=case_id,
            from_version="1.1.0",
            new_version="1.2.0",
            creation_metadata=metadata("2026-07-16T08:03:00+03:00"),
        )
    assert not (
        library / "project_packages" / case_id / "1.2.0" / "project_case_package.json"
    ).exists()
    _, _, validation = derive_library_state(library, generated_at="2026-07-16T08:04:00+03:00")
    assert not any(finding.check_id == "M7V-VERSION-FORK" for finding in validation.findings)


def test_confidential_case_without_shareable_outputs_cannot_be_approved(tmp_path):
    from saudi_plot_design.cases.pipeline import ingest_case

    source = build_case_dir(
        tmp_path / "source",
        case_id="CONFIDENTIAL-VILLA-TEST-001",
        project_type="residential_villa",
        case_role="residential_villa_template_candidate",
        country="SA",
        city="Riyadh",
        architectural_character="najdi",
        confidential=True,
        anonymization_required=True,
        notes="Synthetic confidential test fixture - not a real project.",
    )
    artifacts = tmp_path / "artifacts"
    ingest_case(source, artifacts)
    library = tmp_path / "library"
    candidate, _ = import_m6a_artifacts(
        library_root=library,
        artifact_root=artifacts,
        case_version="1.0.0",
        case_role=CaseRole.RESIDENTIAL_VILLA_CANDIDATE,
        creation_metadata=metadata("2026-07-16T08:00:00+03:00"),
        template_use_permitted=True,
        shareable_outputs_permitted=False,
        rights_basis="synthetic fixture explicitly permitted for automated tests",
        synthetic_test_fixture=True,
    )
    assert candidate.confidentiality.status == "confidential"
    with pytest.raises(SpdInputError, match="confidential_shareable_output_permission_missing"):
        apply_review(
            library_root=library,
            case_id=candidate.case_id,
            from_version="1.0.0",
            new_version="1.1.0",
            decision_type=ReviewDecisionType.APPROVED,
            reviewer_id="synthetic-test-reviewer",
            review_date="2026-07-16",
            bound_fingerprint=candidate.review_binding_fingerprint,
            rationale="Approval must be blocked by the confidentiality gate.",
            template_use_approved=True,
            creation_metadata=metadata("2026-07-16T08:01:00+03:00"),
        )
    # The failed approval must not have written the new version.
    assert not (library / "project_packages" / candidate.case_id / "1.1.0").exists()
