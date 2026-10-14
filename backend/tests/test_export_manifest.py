"""Tests for run.json, the export manifest, and hashing (M5)."""

import json

import pytest

from saudi_plot_design.elevation.facade_selection import select_primary_facade
from saudi_plot_design.elevation.front import generate_front_facade
from saudi_plot_design.export.pipeline import export_project
from saudi_plot_design.export.runlog import sha256_file
from saudi_plot_design.output import DISCLAIMER
from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
from tests.conftest import reference_pipeline

FIXED_RUN = {"run_id": "test-run-0001", "generation_timestamp": "2026-07-13T00:00:00Z"}


@pytest.fixture(scope="module")
def state():
    s = reference_pipeline()
    s["rules"] = load_default_setback_rules()
    s["envelope"] = compute_envelope(s["plot"], s["rules"])
    s["selection"] = select_primary_facade(s["plot"], s["concept"], 0, user_confirmed=True)
    s["facade"] = generate_front_facade(
        s["plot"],
        s["concept"],
        s["selection"],
        s["match"],
        s["style_selection"],
        s["pack_ref"],
        s["pack_data"],
    )
    return s


def run_export(state, out_dir, **overrides):
    kwargs = dict(
        plot=state["plot"],
        envelope=state["envelope"],
        rules=state["rules"],
        concept=state["concept"],
        match=state["match"],
        style_selection=state["style_selection"],
        pack_ref=state["pack_ref"],
        pack_data=state["pack_data"],
        selection=state["selection"],
        facade=state["facade"],
        source_inputs=["samples/plot_20x30.csv"],
        **FIXED_RUN,
    )
    kwargs.update(overrides)
    return export_project(out_dir, **kwargs)


@pytest.fixture(scope="module")
def exported(state, tmp_path_factory):
    out = tmp_path_factory.mktemp("export")
    return out, run_export(state, out)


class TestRunJson:
    def test_contains_fingerprints_and_ids(self, state, exported):
        out, _ = exported
        payload = json.loads((out / "run.json").read_text(encoding="utf-8"))
        assert payload["plot_fingerprint"] == state["plot"].fingerprint
        assert payload["concept_fingerprint"] == state["concept"].fingerprint
        assert payload["project_id"] == state["plot"].plot_id
        assert payload["facade_concept_id"] == state["facade"].facade_concept_id
        assert payload["style_pack_id"] == "najdi_demo_v1"
        assert payload["dataset_id"] == "DEMO-CHAR-ZONES"
        assert payload["run_id"] == FIXED_RUN["run_id"]

    def test_contains_output_hashes(self, exported):
        out, _ = exported
        payload = json.loads((out / "run.json").read_text(encoding="utf-8"))
        for name, digest in payload["output_sha256"].items():
            assert digest == sha256_file(out / name)

    def test_confirmations_and_validation_summaries(self, exported):
        out, _ = exported
        payload = json.loads((out / "run.json").read_text(encoding="utf-8"))
        assert payload["confirmations"]["style_user_confirmed"] is True
        assert payload["confirmations"]["facade_user_confirmed"] is True
        assert payload["validation_summaries"]["concept"]["passed"] is True
        assert payload["validation_summaries"]["facade"]["checks"] == 24

    def test_governed_data_provenance_recorded(self, exported):
        # Regression (Codex M5 P2): run.json must carry complete per-dataset
        # provenance for every governed source consumed.
        out, _ = exported
        payload = json.loads((out / "run.json").read_text(encoding="utf-8"))
        prov = payload["governed_data_provenance"]
        assert prov["character_dataset"]["source_status"].startswith("DEMO SYNTHETIC")
        assert prov["character_dataset"]["demo_statement"].startswith(
            "Demo geographic classification"
        )
        assert prov["style_pack"]["status"] == "demo_requires_architect_review"
        assert prov["style_pack"]["source_metadata"]["provenance_level"] == "demo"
        assert prov["style_pack"]["limitations"]
        assert prov["setback_rules"]["provenance"] == "demo"
        assert "NOT official" in prov["setback_rules"]["statement"]

    def test_style_provenance_from_consumed_pack_data(self, state, exported):
        # run.json provenance is serialized from the consumed pack_data.
        out, _ = exported
        payload = json.loads((out / "run.json").read_text(encoding="utf-8"))
        recorded = payload["governed_data_provenance"]["style_pack"]
        assert recorded["source_metadata"] == state["pack_data"].source_metadata.model_dump(
            mode="json"
        )
        assert recorded["name_ar"] == state["pack_data"].core.name_ar

    def test_tampered_pack_ref_blocks_export(self, state, tmp_path):
        # Strengthened (Codex M5 full-diff review, high): a drifted reference
        # is now rejected at the gate instead of being tolerated in run.json.
        from saudi_plot_design.model import SpdInputError

        tampered_ref = state["pack_ref"].model_copy(
            update={
                "source_metadata": {
                    **state["pack_ref"].source_metadata,
                    "statement": "TAMPERED REFERENCE METADATA",
                }
            }
        )
        with pytest.raises(SpdInputError, match="does not match the consumed pack data"):
            run_export(state, tmp_path, pack_ref=tampered_ref)
        assert not list(tmp_path.iterdir())

    def test_disclaimer_present(self, exported):
        out, _ = exported
        payload = json.loads((out / "run.json").read_text(encoding="utf-8"))
        assert payload["disclaimer"] == DISCLAIMER

    def test_deterministic_under_fixed_run_metadata(self, state, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        run_export(state, a)
        run_export(state, b)
        assert (a / "run.json").read_bytes() == (b / "run.json").read_bytes()
        assert (a / "export_manifest.json").read_bytes() == (
            b / "export_manifest.json"
        ).read_bytes()
        assert sha256_file(a / "saudi_plot_design_reference.pdf") == sha256_file(
            b / "saudi_plot_design_reference.pdf"
        )
        assert sha256_file(a / "saudi_plot_design_reference.dxf") == sha256_file(
            b / "saudi_plot_design_reference.dxf"
        )
        for name in (
            "architectural_quality_report.json",
            "architectural_quality_summary.md",
            "architectural_quality_overlay.svg",
        ):
            assert (a / name).read_bytes() == (b / name).read_bytes()


class TestManifest:
    def test_hashes_match_actual_files(self, exported):
        out, manifest = exported
        for name, digest in manifest.file_sha256.items():
            assert digest == sha256_file(out / name)
            assert manifest.file_sizes_bytes[name] == (out / name).stat().st_size

    def test_binds_exact_sources(self, state, exported):
        _, manifest = exported
        assert manifest.plot_fingerprint == state["plot"].fingerprint
        assert manifest.concept_fingerprint == state["concept"].fingerprint
        assert manifest.facade_concept_id == state["facade"].facade_concept_id
        assert manifest.validation_status == "all_gates_passed"
        assert manifest.disclaimer == DISCLAIMER

    def test_mutating_output_changes_hash(self, exported):
        out, manifest = exported
        target = out / "saudi_plot_design_reference.dxf"
        original = manifest.file_sha256[target.name]
        target.write_bytes(target.read_bytes() + b"\n999\n")
        assert sha256_file(target) != original

    def test_all_outputs_reference_disclaimer(self, exported):
        out, _ = exported
        run_payload = json.loads((out / "run.json").read_text(encoding="utf-8"))
        manifest_payload = json.loads((out / "export_manifest.json").read_text(encoding="utf-8"))
        assert run_payload["disclaimer"] == DISCLAIMER
        assert manifest_payload["disclaimer"] == DISCLAIMER
        # PDF and DXF disclaimers are asserted in their own reopen tests.
