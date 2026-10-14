"""M6A tests: IFC case ingestion, privacy gates, review states, determinism.

The IFC fixture is synthetic TEST DATA (see m6a_ifc_fixture.py) - it is not
a professional design and is never treated as an approved template.
"""

from __future__ import annotations

import hashlib
import json

import pytest

pytest.importorskip("ifcopenshell")

from m6a_ifc_fixture import build_case_dir, build_test_ifc, guid, write_metadata

from saudi_plot_design.cases.eligibility import (
    TemplateEligibilityError,
    evaluate_template_eligibility,
)
from saudi_plot_design.cases.metadata import ANONYMIZED
from saudi_plot_design.cases.models import (
    CaseState,
    TemplateUseBlocked,
    assert_template_usable,
)
from saudi_plot_design.cases.pipeline import ingest_case
from saudi_plot_design.model import SpdInputError

EXPECTED_FILES = {
    "case_manifest.json",
    "architectural_case.json",
    "spaces.json",
    "elements.json",
    "adjacency_graph.json",
    "circulation_graph.json",
    "facade_openings.json",
    "metrics.json",
    "validation_report.json",
    "review_corrections_template.json",
    "plan_preview.svg",
}


@pytest.fixture(scope="module")
def standard(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("m6a_standard")
    source = build_case_dir(tmp)
    out = tmp / "out"
    case = ingest_case(source, out)
    return source, out, case


# --- valid ingestion -------------------------------------------------------


def test_valid_case_stops_at_requires_review(standard):
    _, _, case = standard
    assert case.state is CaseState.REQUIRES_REVIEW
    assert case.validation is not None and case.validation.passed
    assert case.template_eligible is True
    assert case.template_ineligibility_reasons == ()


def test_all_output_files_written_with_matching_hashes(standard):
    _, out, _ = standard
    assert {p.name for p in out.iterdir()} == EXPECTED_FILES
    manifest = json.loads((out / "case_manifest.json").read_text(encoding="utf-8"))
    assert manifest["state"] == "requires_review"
    assert manifest["template_eligible"] is True
    assert manifest["template_ineligibility_reasons"] == []
    for name, expected in manifest["files_sha256"].items():
        digest = hashlib.sha256((out / name).read_bytes()).hexdigest()
        assert digest == expected, f"hash mismatch for {name}"


def test_ifc_global_ids_retained(standard):
    _, _, case = standard
    assert {s.ifc_global_id for s in case.spaces} >= {guid("sp_majlis"), guid("sp_kitchen")}
    assert {w.ifc_global_id for w in case.walls} >= {guid("w_front"), guid("w_kit_bath")}
    assert {d.ifc_global_id for d in case.doors} >= {guid("d_main"), guid("d_majlis")}
    assert {w.ifc_global_id for w in case.windows} == {guid("win_front"), guid("win_majlis")}
    assert case.levels[0].ifc_global_id == guid("storey")


def test_classifications_from_names_are_reviewable(standard):
    _, _, case = standard
    by_name = {s.name: s for s in case.spaces}
    majlis = by_name["Majlis"]
    assert majlis.space_type.value == "mens_majlis"
    assert majlis.zone.value == "guest_public"
    assert majlis.space_type.method == "name_keyword"
    assert 0 < majlis.space_type.confidence < 1
    assert majlis.space_type.reviewer_status == "requires_review"
    kitchen = by_name["Kitchen"]  # Arabic long name matched too
    assert kitchen.space_type.value == "kitchen"


def test_specific_room_names_beat_generic_keywords():
    from saudi_plot_design.cases.semantics import classify_space

    assert classify_space("Master Bathroom", None)[0].value == "bathroom"
    assert classify_space("Maid Bedroom", None)[0].value == "maid_room"
    assert classify_space("Master Bedroom", None)[0].value == "master_bedroom"


def test_net_quantity_preferred_across_all_quantity_sets(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"gross_first_qto": True})
    case = ingest_case(source, tmp_path / "out")
    mystery = next(s for s in case.spaces if s.ifc_global_id == guid("sp_mystery"))
    assert mystery.area_m2 == pytest.approx(9.0)  # Net wins over earlier Gross


def test_indexed_polycurve_axis_extracted(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"indexed_axis": True})
    case = ingest_case(source, tmp_path / "out")
    front = next(w for w in case.walls if w.ifc_global_id == guid("w_front"))
    assert front.start == (0.0, 0.0) and front.end == (14.0, 0.0)
    assert not any("no axis representation" in w for w in case.warnings)


def test_unclassifiable_space_stays_unknown(standard):
    _, _, case = standard
    mystery = next(s for s in case.spaces if s.name == "Rm-07")
    assert mystery.space_type.value == "unknown"
    assert mystery.zone.value == "unknown"
    assert mystery.space_type.confidence == 0.0
    assert mystery.space_type.method == "unclassified"


def test_metric_and_millimetre_models_agree(standard, tmp_path):
    _, _, case = standard
    mm_case = ingest_case(build_case_dir(tmp_path, ifc_kwargs={"milli": True}), tmp_path / "out")
    assert {s.name: s.area_m2 for s in mm_case.spaces} == {s.name: s.area_m2 for s in case.spaces}
    assert {w.ifc_global_id: w.thickness_m for w in mm_case.walls} == {
        w.ifc_global_id: w.thickness_m for w in case.walls
    }


# --- relationships ---------------------------------------------------------


def test_room_adjacency_from_space_boundaries(standard):
    _, _, case = standard
    pairs = {(e.a, e.b) for e in case.graphs.room_adjacency}
    kitchen_wc = tuple(sorted((guid("sp_kitchen"), guid("sp_bathroom"))))
    assert kitchen_wc in pairs
    corridor_living = tuple(sorted((guid("sp_corridor"), guid("sp_living"))))
    assert corridor_living in pairs


def test_circulation_graph_uses_doors(standard):
    _, _, case = standard
    vias = {e.via for e in case.graphs.circulation}
    assert guid("d_cor_bed") in vias
    connected = {(e.a, e.b) for e in case.graphs.circulation}
    assert tuple(sorted((guid("sp_corridor"), guid("sp_bedroom")))) in connected


def test_wet_rooms_cluster_together(standard):
    _, _, case = standard
    assert case.graphs.wet_groups == (tuple(sorted((guid("sp_bathroom"), guid("sp_kitchen")))),)


def test_entrances_and_privacy_paths(standard):
    _, _, case = standard
    kinds = {e.entrance_type.value for e in case.entrances}
    assert kinds == {"main_family_entrance", "mens_majlis_entrance"}
    # The guest entrance reaches only the majlis (no internal guest door in
    # the fixture) while the family entrance reaches the family side.
    assert case.graphs.guest_path == (guid("sp_majlis"),)
    assert guid("sp_bedroom") in case.graphs.family_path
    assert guid("sp_majlis") not in case.graphs.family_path


def test_facade_openings_inventory(standard):
    _, _, case = standard
    assert set(case.facade_openings) == {
        guid("d_main"),
        guid("d_majlis"),
        guid("win_front"),
        guid("win_majlis"),
    }


def test_metrics_are_descriptive_only(standard):
    _, _, case = standard
    metrics = case.metrics
    assert metrics.bedroom_count == 1
    assert metrics.bathroom_count == 1
    assert metrics.circulation_area_m2 == pytest.approx(12.0)
    assert "no automatic architectural quality claim" in metrics.note
    assert metrics.entrance_counts == {
        "main_family_entrance": 1,
        "mens_majlis_entrance": 1,
    }
    assert metrics.area_metrics_complete is True
    assert metrics.spaces_without_area == ()


# --- template eligibility -------------------------------------------------


def _build_office_stress_case(tmp_path):
    return build_case_dir(
        tmp_path,
        project_type="mixed_use_office_building",
        case_role=None,
        country="Finland",
        city="undisclosed",
        architectural_character="not_applicable_for_saudi_villa_training",
        notes=(
            "Non-residential mixed-use office IFC ingestion stress-test. "
            "Do not use as a Saudi residential-villa template."
        ),
    )


def test_mixed_use_office_stress_case_is_deterministically_ineligible(tmp_path):
    source = _build_office_stress_case(tmp_path)
    case = ingest_case(source, tmp_path / "out")
    expected = (
        "project_type_not_residential_villa:mixed_use_office_building",
        "country_not_saudi_arabia:finland",
        "declared_case_role_ineligible:ingestion_stress_test",
        "architectural_character_not_applicable:not_applicable_for_saudi_villa_training",
    )
    assert case.state is CaseState.REQUIRES_REVIEW
    assert case.template_eligible is False
    assert case.template_ineligibility_reasons == expected
    assert evaluate_template_eligibility(case).template_ineligibility_reasons == expected
    assert evaluate_template_eligibility(case).template_ineligibility_reasons == expected


def test_candidate_role_cannot_override_incompatible_office_project_type(tmp_path):
    source = build_case_dir(
        tmp_path,
        project_type="commercial_office",
        case_role="residential_villa_template_candidate",
    )
    case = ingest_case(source, tmp_path / "out")
    assert case.template_eligible is False
    assert case.template_ineligibility_reasons == (
        "project_type_not_residential_villa:commercial_office",
    )


def test_residential_label_without_bedroom_is_not_villa_suitable(standard):
    _, _, case = standard
    without_bedrooms = case.model_copy(
        update={
            "spaces": tuple(
                space
                for space in case.spaces
                if space.space_type.value not in {"bedroom", "master_bedroom"}
            )
        }
    )
    eligibility = evaluate_template_eligibility(without_bedrooms)
    assert eligibility.template_eligible is False
    assert "residential_program_missing_bedroom" in (eligibility.template_ineligibility_reasons)


def test_office_cannot_accept_approved_template_with_valid_review_binding(tmp_path):
    source = _build_office_stress_case(tmp_path)
    reviewed = ingest_case(source, tmp_path / "out-review")
    _approve(source, reviewed.provenance.review_binding_fingerprint)
    with pytest.raises(TemplateEligibilityError) as exc_info:
        ingest_case(source, tmp_path / "out")
    assert exc_info.value.template_ineligibility_reasons == (
        "project_type_not_residential_villa:mixed_use_office_building",
        "country_not_saudi_arabia:finland",
        "declared_case_role_ineligible:ingestion_stress_test",
        "architectural_character_not_applicable:not_applicable_for_saudi_villa_training",
    )


def test_ineligible_case_may_be_architect_reviewed_without_template_approval(tmp_path):
    source = _build_office_stress_case(tmp_path)
    reviewed = ingest_case(source, tmp_path / "out-review")
    _approve(
        source,
        reviewed.provenance.review_binding_fingerprint,
        state="architect_reviewed",
    )
    case = ingest_case(source, tmp_path / "out")
    assert case.state is CaseState.ARCHITECT_REVIEWED
    assert case.template_eligible is False


def test_template_use_rechecks_manually_approved_ineligible_case(tmp_path):
    source = _build_office_stress_case(tmp_path)
    case = ingest_case(source, tmp_path / "out")
    forged = case.model_copy(
        update={
            "state": CaseState.APPROVED_TEMPLATE,
            "provenance": case.provenance.model_copy(
                update={"reviewer": "Test Architect", "review_date": "2026-07-14"}
            ),
        }
    )
    with pytest.raises(TemplateUseBlocked) as exc_info:
        assert_template_usable(forged)
    assert (
        "project_type_not_residential_villa:mixed_use_office_building"
        in exc_info.value.template_ineligibility_reasons
    )


def test_template_use_requires_architect_review_record_even_for_eligible_case(standard):
    _, _, case = standard
    forged = case.model_copy(update={"state": CaseState.APPROVED_TEMPLATE})
    with pytest.raises(TemplateUseBlocked) as exc_info:
        assert_template_usable(forged)
    assert "architect_review_record_missing_reviewer" in (
        exc_info.value.template_ineligibility_reasons
    )
    assert "architect_review_record_invalid_date" in (exc_info.value.template_ineligibility_reasons)


def test_blocking_validation_failure_prevents_eligibility_and_approval(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"bad_area": True})
    reviewed = ingest_case(source, tmp_path / "out-review")
    assert reviewed.template_eligible is False
    assert "blocking_validation_failure:K08" in reviewed.template_ineligibility_reasons
    _approve(source, reviewed.provenance.review_binding_fingerprint)
    with pytest.raises(TemplateEligibilityError) as exc_info:
        ingest_case(source, tmp_path / "out")
    assert "blocking_validation_failure:K08" in (exc_info.value.template_ineligibility_reasons)


def test_non_blocking_warnings_do_not_prevent_eligibility(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"hostless_door": True})
    case = ingest_case(source, tmp_path / "out")
    assert case.warnings
    assert case.validation is not None and case.validation.passed
    assert case.template_eligible is True
    assert case.template_ineligibility_reasons == ()


# --- determinism and traceability ------------------------------------------


def test_reingestion_is_deterministic(standard, tmp_path):
    source, out, _ = standard
    ingest_case(source, tmp_path / "out2")
    for name in sorted(EXPECTED_FILES):
        assert (tmp_path / "out2" / name).read_bytes() == (out / name).read_bytes(), name


def test_source_fingerprint_is_sha256_of_model_bytes(standard):
    source, _, case = standard
    expected = hashlib.sha256((source / "model.ifc").read_bytes()).hexdigest()
    assert case.provenance.source_fingerprint == expected


# --- unsupported or broken source models ------------------------------------


def test_unsupported_schema_rejected(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"schema": "IFC2X3"})
    with pytest.raises(SpdInputError, match="IFC4"):
        ingest_case(source, tmp_path / "out")


def test_missing_storey_rejected(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"omit_storey": True})
    with pytest.raises(SpdInputError, match="IfcBuildingStorey"):
        ingest_case(source, tmp_path / "out")


def test_duplicate_global_id_rejected(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"duplicate_id": True})
    with pytest.raises(SpdInputError, match="duplicate IFC GlobalId"):
        ingest_case(source, tmp_path / "out")


def test_missing_model_file_rejected(tmp_path):
    source = tmp_path / "case_001"
    source.mkdir()
    write_metadata(source)
    with pytest.raises(SpdInputError, match="IFC model not found"):
        ingest_case(source, tmp_path / "out")


def test_implausible_area_reported_not_fabricated(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"bad_area": True})
    case = ingest_case(source, tmp_path / "out")
    assert not case.validation.passed
    failed = {c.id for c in case.validation.failures()}
    assert "K08" in failed
    bedroom = next(s for s in case.spaces if s.name == "Master Bedroom")
    assert bedroom.area_m2 == -3.0  # reported as-is, never corrected silently


def test_hostless_door_produces_warning_not_guess(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"hostless_door": True})
    case = ingest_case(source, tmp_path / "out")
    loose = next(d for d in case.doors if d.name == "Loose Door")
    assert loose.host_wall_id is None
    assert loose.connects_space_ids == ()
    assert any("no host wall" in w for w in case.warnings)
    k06 = next(c for c in case.validation.checks if c.id == "K06")
    assert k06.passed  # warning recorded, so the check is satisfied


def test_external_boundary_marks_wall_external_without_pset(tmp_path):
    # Exporter omitted Pset_WallCommon.IsExternal; the EXTERNAL space
    # boundary must still mark the wall so facade openings and entrances on
    # it are not lost.
    source = build_case_dir(tmp_path, ifc_kwargs={"no_external_pset": True})
    case = ingest_case(source, tmp_path / "out")
    front = next(w for w in case.walls if w.ifc_global_id == guid("w_front"))
    assert front.is_external
    assert {e.entrance_type.value for e in case.entrances} == {
        "main_family_entrance",
        "mens_majlis_entrance",
    }
    assert guid("win_front") in case.facade_openings


def test_missing_area_flagged_not_counted_as_zero(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"omit_area": True})
    case = ingest_case(source, tmp_path / "out")
    mystery = next(s for s in case.spaces if s.ifc_global_id == guid("sp_mystery"))
    assert mystery.area_m2 is None
    assert case.metrics.area_metrics_complete is False
    assert case.metrics.spaces_without_area == (guid("sp_mystery"),)
    assert any("no floor-area quantity" in w for w in case.warnings)


def test_zero_opening_dimension_reported_by_validation(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"zero_width_door": True})
    case = ingest_case(source, tmp_path / "out")
    loose = next(d for d in case.doors if d.name == "Loose Door")
    assert loose.width_m == 0.0  # preserved, not hidden as None
    k09 = next(c for c in case.validation.checks if c.id == "K09")
    assert not k09.passed
    assert loose.ifc_global_id in k09.details


def test_positive_occurrence_qto_recovers_zero_door_attributes(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"zero_door_attributes_with_qto": True})
    case = ingest_case(source, tmp_path / "out")
    loose = next(d for d in case.doors if d.name == "Loose Door")
    assert loose.width_m == pytest.approx(1.1225)
    assert loose.height_m == pytest.approx(2.38)
    assert any(
        "unusable OverallWidth" in warning and "occurrence quantity" in warning
        for warning in case.warnings
    )
    assert any(
        "unusable OverallHeight" in warning and "occurrence quantity" in warning
        for warning in case.warnings
    )
    k09 = next(c for c in case.validation.checks if c.id == "K09")
    assert k09.passed, k09.details


def test_storey_elevation_derived_from_placement(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"placement_elevation": True})
    case = ingest_case(source, tmp_path / "out")
    assert case.levels[0].elevation_m == pytest.approx(3.2)
    assert any("derived from its placement" in w for w in case.warnings)


def test_storey_without_elevation_or_placement_stays_unknown(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"omit_elevation": True})
    case = ingest_case(source, tmp_path / "out")
    assert case.levels[0].elevation_m is None  # not fabricated as 0.0
    assert any("elevation unavailable" in w for w in case.warnings)


def test_external_earth_boundary_marks_wall_external(tmp_path):
    source = build_case_dir(
        tmp_path,
        ifc_kwargs={"no_external_pset": True, "external_variant": "EXTERNAL_EARTH"},
    )
    case = ingest_case(source, tmp_path / "out")
    front = next(w for w in case.walls if w.ifc_global_id == guid("w_front"))
    assert front.is_external
    assert guid("d_main") in case.facade_openings


def test_multi_space_wall_does_not_fabricate_adjacency_clique(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"multi_space_wall": True})
    case = ingest_case(source, tmp_path / "out")
    via_multi = [e for e in case.graphs.room_adjacency if e.via == guid("w_multi")]
    assert via_multi == []  # no pairwise edges invented for a 3-space wall
    assert any("ambiguous" in w and guid("w_multi") in w for w in case.warnings)
    # Real two-space walls still produce adjacency.
    assert any(e.via == guid("w_kit_bath") for e in case.graphs.room_adjacency)


def test_boundary_to_unextracted_wall_is_dropped(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"uncontained_host_wall": True})
    case = ingest_case(source, tmp_path / "out")
    corridor = next(s for s in case.spaces if s.ifc_global_id == guid("sp_corridor"))
    assert guid("w_uncontained") not in corridor.boundary_wall_ids
    assert not any(guid("w_uncontained") == w.ifc_global_id for w in case.walls)
    assert any("boundary dropped" in w for w in case.warnings)


def test_missing_slab_quantities_are_warned(standard):
    _, _, case = standard  # the fixture slab ships without base quantities
    slab = case.slabs[0]
    assert slab.thickness_m is None and slab.area_m2 is None
    assert any("slab" in w.lower() and "quantity" in w for w in case.warnings)


def test_dangling_host_wall_reference_cleared_with_warning(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"uncontained_host_wall": True})
    case = ingest_case(source, tmp_path / "out")
    orphan = next(d for d in case.doors if d.ifc_global_id == guid("d_orphanhost"))
    assert orphan.host_wall_id is None  # dangling reference must not survive
    assert any(guid("d_orphanhost") in w and "host cleared" in w for w in case.warnings)
    for check_id in ("K06", "K10"):
        check = next(c for c in case.validation.checks if c.id == check_id)
        assert check.passed, check.details


def test_same_type_entrance_paths_are_merged():
    from saudi_plot_design.cases.models import Classification, Entrance
    from saudi_plot_design.cases.relationships import _typed_path

    def entrance(door_id, into):
        return Entrance(
            door_id=door_id,
            entrance_type=Classification(
                value="main_family_entrance", method="test", confidence=1.0, source="test"
            ),
            into_space_id=into,
        )

    graph = {"A": {"B"}, "B": {"A"}, "C": set()}
    merged = _typed_path(
        (entrance("d1", "A"), entrance("d2", "C")), graph, {}, "main_family_entrance"
    )
    assert merged == ("A", "B", "C")  # both entrances contribute, not just d1


def test_missing_space_boundaries_warns_and_graphs_empty(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"omit_boundaries": True})
    case = ingest_case(source, tmp_path / "out")
    assert case.graphs.room_adjacency == ()
    assert case.graphs.circulation == ()
    assert any("IfcRelSpaceBoundary" in w for w in case.warnings)


# --- metadata, usage rights, privacy ----------------------------------------


def test_usage_rights_gate_blocks_ingestion(tmp_path):
    source = build_case_dir(tmp_path, usage_rights_confirmed=False)
    out = tmp_path / "out"
    with pytest.raises(SpdInputError, match="usage_rights_confirmed"):
        ingest_case(source, out)
    assert not out.exists()  # nothing was written


def test_usage_rights_gate_rejects_coerced_booleans(tmp_path):
    # "yes"/"true"/1 must not pass the legal gate - only the JSON boolean.
    for sneaky in ("yes", "true", 1):
        source = build_case_dir(tmp_path, usage_rights_confirmed=sneaky)
        with pytest.raises(SpdInputError, match="usage_rights_confirmed"):
            ingest_case(source, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_malformed_metadata_rejected(tmp_path):
    source = build_case_dir(tmp_path)
    metadata = json.loads((source / "case_metadata.json").read_text(encoding="utf-8"))
    del metadata["case_id"]
    (source / "case_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(SpdInputError, match="case_id"):
        ingest_case(source, tmp_path / "out")


def test_unknown_metadata_field_rejected(tmp_path):
    source = build_case_dir(tmp_path, client_name="should not exist")
    with pytest.raises(SpdInputError, match="client_name"):
        ingest_case(source, tmp_path / "out")


def test_metadata_invalid_json_rejected(tmp_path):
    source = build_case_dir(tmp_path)
    (source / "case_metadata.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(SpdInputError, match="not valid JSON"):
        ingest_case(source, tmp_path / "out")


def test_missing_metadata_rejected(tmp_path):
    source = tmp_path / "case_001"
    source.mkdir()
    build_test_ifc(source / "model.ifc")
    with pytest.raises(SpdInputError, match="case metadata not found"):
        ingest_case(source, tmp_path / "out")


def test_anonymization_scrubs_sensitive_values(tmp_path):
    source = build_case_dir(
        tmp_path,
        anonymization_required=True,
        confidential=True,
        district="Real District Name",
        approved_by="Eng. Real Name",
        notes="Client Mr. X, phone +966 55 123 4567, mail a@b.com, price 2,500,000 SAR",
    )
    case = ingest_case(source, tmp_path / "out")
    assert case.metadata.district is None
    assert case.metadata.approved_by == ANONYMIZED
    for leaked in ("Mr. X", "123 4567", "a@b.com", "SAR"):
        assert leaked not in case.metadata.notes
    dumped = (tmp_path / "out" / "architectural_case.json").read_text(encoding="utf-8")
    for leaked in ("Real District Name", "Eng. Real Name", "a@b.com", "4567"):
        assert leaked not in dumped
    assert "case_001" not in case.provenance.source_directory_recorded  # confidential


def test_anonymization_scrubs_ifc_source_names(tmp_path):
    source = build_case_dir(
        tmp_path, ifc_kwargs={"sensitive_names": True}, anonymization_required=True
    )
    case = ingest_case(source, tmp_path / "out")
    k12 = next(c for c in case.validation.checks if c.id == "K12")
    assert k12.passed, k12.details
    for artifact in (tmp_path / "out").iterdir():
        content = artifact.read_text(encoding="utf-8")
        for leaked in ("Fulan", "0551234567", "fulan@example.com"):
            assert leaked not in content, f"{leaked} leaked into {artifact.name}"


def test_anonymization_redacts_reviewer_in_artifacts(tmp_path):
    source = build_case_dir(tmp_path, anonymization_required=True)
    reviewed = ingest_case(source, tmp_path / "out-review")
    _approve(source, reviewed.provenance.review_binding_fingerprint, reviewer="Eng. Private")
    case = ingest_case(source, tmp_path / "out")
    assert case.provenance.reviewer == ANONYMIZED
    assert "Eng. Private" not in (tmp_path / "out" / "case_manifest.json").read_text("utf-8")


def test_anonymization_redacts_correction_reviewer_names(tmp_path):
    source = build_case_dir(tmp_path, anonymization_required=True)
    (source / "review_corrections.json").write_text(
        json.dumps(
            {
                "spaces": {
                    guid("sp_mystery"): {"space_type": "storage", "reviewer": "Eng. Secret Name"}
                }
            }
        ),
        encoding="utf-8",
    )
    case = ingest_case(source, tmp_path / "out")
    mystery = next(s for s in case.spaces if s.ifc_global_id == guid("sp_mystery"))
    assert "Eng. Secret Name" not in mystery.space_type.source
    for artifact in (tmp_path / "out").iterdir():
        assert "Eng. Secret Name" not in artifact.read_text(encoding="utf-8"), artifact.name


def test_confidential_case_hides_folder_name(tmp_path):
    source = build_case_dir(tmp_path, confidential=True)  # anonymization NOT required
    case = ingest_case(source, tmp_path / "out")
    assert case.provenance.source_directory_recorded == "private_cases/<confidential>"
    assert "case_001" not in case.provenance.source_directory_recorded


def test_no_source_file_copied_into_outputs(standard):
    source, out, case = standard
    source_bytes = (source / "model.ifc").read_bytes()
    for artifact in out.iterdir():
        assert artifact.suffix in {".json", ".svg"}
        assert artifact.read_bytes() != source_bytes
    assert case.provenance.source_directory_recorded.startswith("private_cases/")


# --- review states and the approval gate ------------------------------------


def test_unapproved_case_cannot_be_used_as_template(standard):
    _, _, case = standard
    with pytest.raises(TemplateUseBlocked, match="requires_review"):
        assert_template_usable(case)


def test_corrections_move_case_to_corrected(tmp_path):
    source = build_case_dir(tmp_path)
    corrections = {
        "spaces": {guid("sp_mystery"): {"space_type": "storage", "reviewer": "Test Architect"}}
    }
    (source / "review_corrections.json").write_text(json.dumps(corrections), encoding="utf-8")
    case = ingest_case(source, tmp_path / "out")
    assert case.state is CaseState.CORRECTED
    mystery = next(s for s in case.spaces if s.ifc_global_id == guid("sp_mystery"))
    assert mystery.space_type.value == "storage"
    assert mystery.space_type.method == "manual_correction"
    assert mystery.space_type.confidence == 1.0
    assert mystery.space_type.reviewer_status == "reviewer_confirmed"
    assert mystery.zone.value == "service"  # derived from the corrected type
    with pytest.raises(TemplateUseBlocked):
        assert_template_usable(case)  # corrected is still not approved


def test_correction_template_roundtrip_applies_nothing(standard, tmp_path):
    # Saving the generated template unchanged (all blanks) must be a no-op,
    # not an error, and must not claim the case was corrected.
    _, out, _ = standard
    template = (out / "review_corrections_template.json").read_text(encoding="utf-8")
    source = build_case_dir(tmp_path)
    (source / "review_corrections.json").write_text(template, encoding="utf-8")
    case = ingest_case(source, tmp_path / "out")
    assert case.state is CaseState.REQUIRES_REVIEW


def test_k05_fails_without_usable_wall_geometry(standard):
    from saudi_plot_design.cases.validation import validate_case

    _, _, case = standard
    no_walls = validate_case(case.model_copy(update={"walls": ()}))
    k05 = next(c for c in no_walls.checks if c.id == "K05")
    assert not k05.passed and "no walls extracted" in k05.details
    axis_less = case.model_copy(
        update={
            "walls": tuple(w.model_copy(update={"start": None, "end": None}) for w in case.walls)
        }
    )
    k05 = next(c for c in validate_case(axis_less).checks if c.id == "K05")
    assert not k05.passed and "axis geometry" in k05.details


def test_malformed_corrections_structure_rejected(tmp_path):
    source = build_case_dir(tmp_path)
    for payload, match in (
        ({"spaces": ["not-an-object"]}, "must be an object mapping"),
        ({"spaces": {guid("sp_mystery"): "storage"}}, "must be an object"),
    ):
        (source / "review_corrections.json").write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(SpdInputError, match=match):
            ingest_case(source, tmp_path / "out")


def test_correction_for_unknown_global_id_rejected(tmp_path):
    source = build_case_dir(tmp_path)
    (source / "review_corrections.json").write_text(
        json.dumps({"spaces": {"NotARealGlobalId0000": {"space_type": "storage"}}}),
        encoding="utf-8",
    )
    with pytest.raises(SpdInputError, match="unknown space GlobalId"):
        ingest_case(source, tmp_path / "out")


def test_ineffective_corrections_do_not_claim_corrected(tmp_path):
    source = build_case_dir(tmp_path)
    (source / "review_corrections.json").write_text(
        json.dumps({"_instructions": "nothing here", "spaces": {}}), encoding="utf-8"
    )
    case = ingest_case(source, tmp_path / "out")
    assert case.state is CaseState.REQUIRES_REVIEW


def test_invalid_correction_value_rejected(tmp_path):
    source = build_case_dir(tmp_path)
    (source / "review_corrections.json").write_text(
        json.dumps({"spaces": {guid("sp_mystery"): {"space_type": "throne_room"}}}),
        encoding="utf-8",
    )
    with pytest.raises(SpdInputError, match="unknown space_type"):
        ingest_case(source, tmp_path / "out")


def test_review_decision_requires_accountable_reviewer(tmp_path):
    source = build_case_dir(tmp_path)
    (source / "review_decision.json").write_text(
        json.dumps({"state": "approved_template"}), encoding="utf-8"
    )
    with pytest.raises(SpdInputError, match="reviewed_by"):
        ingest_case(source, tmp_path / "out")


def test_review_decision_rejects_unknown_state(tmp_path):
    source = build_case_dir(tmp_path)
    (source / "review_decision.json").write_text(
        json.dumps({"state": "ingested", "reviewed_by": "X", "review_date": "2026-07-14"}),
        encoding="utf-8",
    )
    with pytest.raises(SpdInputError, match="state must be one of"):
        ingest_case(source, tmp_path / "out")


def _approve(source, binding, state="approved_template", reviewer="Test Architect"):
    (source / "review_decision.json").write_text(
        json.dumps(
            {
                "state": state,
                "reviewed_by": reviewer,
                "review_date": "2026-07-14",
                "case_fingerprint": binding,
            }
        ),
        encoding="utf-8",
    )


def test_explicit_approval_unlocks_template_use(tmp_path):
    source = build_case_dir(tmp_path)
    # First run: the reviewer inspects the artifacts and copies the binding
    # fingerprint from the manifest into the decision file.
    reviewed = ingest_case(source, tmp_path / "out-review")
    manifest = json.loads((tmp_path / "out-review" / "case_manifest.json").read_text("utf-8"))
    assert manifest["review_binding_fingerprint"] == (
        reviewed.provenance.review_binding_fingerprint
    )
    _approve(source, reviewed.provenance.review_binding_fingerprint)
    case = ingest_case(source, tmp_path / "out")
    assert case.state is CaseState.APPROVED_TEMPLATE
    assert case.provenance.reviewer == "Test Architect"
    assert case.provenance.review_date == "2026-07-14"
    assert_template_usable(case)  # does not raise


def test_review_decision_without_fingerprint_rejected(tmp_path):
    source = build_case_dir(tmp_path)
    (source / "review_decision.json").write_text(
        json.dumps(
            {
                "state": "approved_template",
                "reviewed_by": "Test Architect",
                "review_date": "2026-07-14",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SpdInputError, match="case_fingerprint"):
        ingest_case(source, tmp_path / "out")


def test_stale_review_decision_rejected_when_source_changes(tmp_path):
    source = build_case_dir(tmp_path)
    reviewed = ingest_case(source, tmp_path / "out-review")
    _approve(source, reviewed.provenance.review_binding_fingerprint)
    # The model changes after the review - the old approval must not carry.
    build_test_ifc(source / "model.ifc", bad_area=True)
    with pytest.raises(SpdInputError, match="does not match"):
        ingest_case(source, tmp_path / "out")


def test_stale_review_decision_rejected_when_classifier_changes(tmp_path, monkeypatch):
    # The binding covers derived review content, so a change in classifier
    # (or extractor) behavior invalidates an old approval even though the
    # source inputs are byte-identical.
    from saudi_plot_design.cases.models import Classification

    source = build_case_dir(tmp_path)
    reviewed = ingest_case(source, tmp_path / "out-review")
    _approve(source, reviewed.provenance.review_binding_fingerprint)

    def stub_classify(name, long_name):
        c = Classification(value="storage", method="name_keyword", confidence=0.5, source="stub")
        z = Classification(
            value="service", method="derived_from_space_type", confidence=0.5, source="stub"
        )
        return c, z

    monkeypatch.setattr("saudi_plot_design.cases.pipeline.classify_space", stub_classify)
    with pytest.raises(SpdInputError, match="does not match"):
        ingest_case(source, tmp_path / "out")


def test_stale_review_decision_rejected_when_validation_changes(tmp_path, monkeypatch):
    # The binding includes the validation report, so changed validation
    # behavior alone invalidates an old approval.
    from saudi_plot_design.model import ValidationCheck, ValidationReport

    source = build_case_dir(tmp_path)
    reviewed = ingest_case(source, tmp_path / "out-review")
    _approve(source, reviewed.provenance.review_binding_fingerprint)

    def stub_validate(case):
        return ValidationReport(
            checks=(ValidationCheck(id="K99", name="stub", passed=True, details="stub"),)
        )

    monkeypatch.setattr("saudi_plot_design.cases.pipeline.validate_case", stub_validate)
    with pytest.raises(SpdInputError, match="does not match"):
        ingest_case(source, tmp_path / "out")


def test_non_string_or_blank_reviewer_rejected(tmp_path):
    source = build_case_dir(tmp_path)
    reviewed = ingest_case(source, tmp_path / "out-review")
    for bad_reviewer in (42, ["Team"], "   "):
        (source / "review_decision.json").write_text(
            json.dumps(
                {
                    "state": "approved_template",
                    "reviewed_by": bad_reviewer,
                    "review_date": "2026-07-14",
                    "case_fingerprint": reviewed.provenance.review_binding_fingerprint,
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(SpdInputError, match="reviewed_by"):
            ingest_case(source, tmp_path / "out")


def test_invalid_review_date_rejected(tmp_path):
    source = build_case_dir(tmp_path)
    reviewed = ingest_case(source, tmp_path / "out-review")
    (source / "review_decision.json").write_text(
        json.dumps(
            {
                "state": "approved_template",
                "reviewed_by": "Test Architect",
                "review_date": "tomorrow",
                "case_fingerprint": reviewed.provenance.review_binding_fingerprint,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SpdInputError, match="ISO date"):
        ingest_case(source, tmp_path / "out")


def test_stale_review_decision_rejected_when_corrections_change(tmp_path):
    source = build_case_dir(tmp_path)
    reviewed = ingest_case(source, tmp_path / "out-review")
    _approve(source, reviewed.provenance.review_binding_fingerprint)
    (source / "review_corrections.json").write_text(
        json.dumps({"spaces": {guid("sp_mystery"): {"space_type": "storage"}}}),
        encoding="utf-8",
    )
    with pytest.raises(SpdInputError, match="does not match"):
        ingest_case(source, tmp_path / "out")


# --- preview ----------------------------------------------------------------


def test_preview_is_inspection_svg_with_state_banner(standard):
    _, out, _ = standard
    svg = (out / "plan_preview.svg").read_text(encoding="utf-8")
    assert svg.startswith("<svg")
    assert "NOT AN APPROVED TEMPLATE" in svg
    assert "technical inspection preview" in svg
    assert "<line" in svg  # wall axes drawn
    assert "approximate" in svg  # opening markers honestly labeled


def test_preview_partitions_storeys_into_separate_panels(tmp_path):
    source = build_case_dir(tmp_path, ifc_kwargs={"second_storey": True})
    ingest_case(source, tmp_path / "out")
    svg = (tmp_path / "out" / "plan_preview.svg").read_text(encoding="utf-8")
    assert "Level: Ground Floor" in svg
    assert "Level: First Floor" in svg


def test_corrections_template_lists_every_space_and_entrance(standard):
    _, out, case = standard
    template = json.loads((out / "review_corrections_template.json").read_text(encoding="utf-8"))
    assert set(template["spaces"]) == {s.ifc_global_id for s in case.spaces}
    assert set(template["entrances"]) == {e.door_id for e in case.entrances}
