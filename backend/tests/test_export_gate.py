"""Tests for the M5 export binding/safety gate."""

import pytest

from saudi_plot_design.elevation.facade_selection import select_primary_facade
from saudi_plot_design.elevation.front import generate_front_facade
from saudi_plot_design.export.binding import export_gate
from saudi_plot_design.export.pipeline import export_project
from saudi_plot_design.model import SpdInputError
from saudi_plot_design.rules.setbacks import load_default_setback_rules
from tests.conftest import reference_pipeline


@pytest.fixture(scope="module")
def state():
    s = reference_pipeline()
    s["rules"] = load_default_setback_rules()
    from saudi_plot_design.rules.setbacks import compute_envelope

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


def gate(s, **overrides):
    args = {
        k: s[k]
        for k in (
            "plot",
            "envelope",
            "rules",
            "concept",
            "match",
            "style_selection",
            "pack_ref",
            "pack_data",
            "selection",
            "facade",
        )
    }
    args.update(overrides)
    return export_gate(
        args["plot"],
        args["envelope"],
        args["rules"],
        args["concept"],
        args["match"],
        args["style_selection"],
        args["pack_ref"],
        args["pack_data"],
        args["selection"],
        args["facade"],
    )


class TestExportGate:
    def test_reference_chain_passes(self, state):
        result = gate(state)
        assert result.passed, result.reasons

    def test_plot_fingerprint_mismatch_blocks(self, state):
        from saudi_plot_design.plot.geometry import build_plot_model
        from tests.conftest import REFERENCE_CORNERS, standard_edges

        other_plot, _ = build_plot_model(REFERENCE_CORNERS, standard_edges(), 20.0)
        result = gate(state, plot=other_plot)
        assert not result.passed
        assert any("fingerprint mismatch" in r for r in result.reasons)

    def test_concept_fingerprint_mismatch_blocks(self, state):
        from saudi_plot_design.planner.compact_3br import plan_compact_3br
        from saudi_plot_design.plot.geometry import build_plot_model
        from saudi_plot_design.rules.setbacks import compute_envelope
        from tests.conftest import standard_edges

        skewed = ((0.0, 0.0), (20.0, 0.02), (20.0, 30.02), (0.0, 30.0))
        other_plot, _ = build_plot_model(skewed, standard_edges(), 15.0)
        other_concept = plan_compact_3br(other_plot, compute_envelope(other_plot, state["rules"]))
        result = gate(state, concept=other_concept)
        assert not result.passed
        assert any(
            "concept fingerprint mismatch" in r or "fingerprint" in r for r in result.reasons
        )

    def test_stale_facade_concept_reference_blocks(self, state):
        stale = state["facade"].model_copy(update={"concept_fingerprint": "deadbeef00000000"})
        result = gate(state, facade=stale)
        assert not result.passed
        assert any("different concept with the same id" in r for r in result.reasons)

    def test_stale_facade_plot_reference_blocks(self, state):
        stale = state["facade"].model_copy(update={"plot_fingerprint": "deadbeef00000000"})
        result = gate(state, facade=stale)
        assert not result.passed
        assert any("different plot with the same id" in r for r in result.reasons)

    def test_unconfirmed_style_blocks(self, state):
        unconfirmed = state["style_selection"].model_copy(update={"user_confirmed": False})
        result = gate(state, style_selection=unconfirmed)
        assert not result.passed
        assert any("user_confirmed is false" in r for r in result.reasons)

    def test_invalid_facade_blocks(self, state):
        invalid = state["facade"].model_copy(
            update={"rejection_reasons": ("forced invalid for test",)}
        )
        result = gate(state, facade=invalid)
        assert not result.passed
        assert any("invalid or rejected" in r for r in result.reasons)

    def test_missing_disclaimer_blocks(self, state):
        naked = state["facade"].model_copy(update={"disclaimer": ""})
        result = gate(state, facade=naked)
        assert not result.passed
        assert any("missing the unconditional DEMO disclaimer" in r for r in result.reasons)

    def test_modified_facade_with_stale_report_blocks(self, state):
        # Regression (Codex M5 P1): a facade copy with modified geometry but a
        # retained passing validation report must fail re-validation.
        moved = tuple(
            o.model_copy(update={"x_start_m": o.x_start_m + 0.05}) if o.id == "F-w_kitchen" else o
            for o in state["facade"].facade_openings
        )
        tampered = state["facade"].model_copy(update={"facade_openings": moved})
        assert tampered.is_valid  # the stale report still claims validity
        result = gate(state, facade=tampered)
        assert not result.passed
        assert any("re-validation" in r for r in result.reasons)

    def test_facade_from_other_zone_blocks(self, state):
        # Regression (Codex M5 P1): facade bound to the supplied match.
        drifted = state["facade"].model_copy(
            update={"character_match_zone_id": "DEMO-ZONE-HEJAZI-01"}
        )
        result = gate(state, facade=drifted)
        assert not result.passed
        assert any("character zone" in r for r in result.reasons)

    def test_facade_from_other_pack_version_blocks(self, state):
        drifted = state["facade"].model_copy(update={"style_pack_version": "0.0.1"})
        result = gate(state, facade=drifted)
        assert not result.passed
        assert any("regenerate the facade" in r for r in result.reasons)

    def test_stale_envelope_blocks(self, state):
        # Regression (Codex M5 P2): the envelope must match plot + rules.
        from saudi_plot_design.model import BuildableEnvelope

        stale = BuildableEnvelope(
            corners=((3.0, 4.0), (17.0, 4.0), (17.0, 27.0), (3.0, 27.0)),
            area_m2=14.0 * 23.0,
            width_m=14.0,
            depth_m=23.0,
        )
        result = gate(state, envelope=stale)
        assert not result.passed
        assert any("does not match the envelope computed" in r for r in result.reasons)

    def test_no_partial_output_on_mid_pipeline_failure(self, state, tmp_path, monkeypatch):
        # Regression (Codex M5 P2): if the DXF step fails after the PDF
        # succeeded, nothing may remain in the destination directory.
        from saudi_plot_design.export import pipeline as pipeline_module

        def boom(*args, **kwargs):
            raise RuntimeError("forced DXF failure")

        monkeypatch.setattr(pipeline_module, "_write_dxf", boom)
        with pytest.raises(RuntimeError, match="forced DXF failure"):
            export_project(
                tmp_path / "run",
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
                run_id="t-partial",
                generation_timestamp="2026-07-13T00:00:00Z",
            )
        assert not list((tmp_path / "run").iterdir())  # staging cleaned, no partials

    def test_traversal_run_id_rejected(self, state, tmp_path):
        # Regression (Codex M5 verification P1): a run_id with path
        # separators must be rejected before any path is constructed.
        with pytest.raises(SpdInputError, match="run_id .* must match"):
            export_project(
                tmp_path / "run",
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
                run_id="x\\..\\..\\victim",
                generation_timestamp="2026-07-13T00:00:00Z",
            )

    def test_reordered_envelope_corners_block(self, state):
        # Regression (Codex M5 verification P2): same vertex SET in a
        # different order would draw a crossed polygon - must block.
        from saudi_plot_design.model import BuildableEnvelope

        c = list(state["envelope"].corners)
        reordered = BuildableEnvelope(
            corners=(c[0], c[2], c[1], c[3]),
            area_m2=state["envelope"].area_m2,
            width_m=state["envelope"].width_m,
            depth_m=state["envelope"].depth_m,
        )
        result = gate(state, envelope=reordered)
        assert not result.passed
        assert any("ordered corners" in r for r in result.reasons)

    def test_stale_envelope_area_blocks(self, state):
        from saudi_plot_design.model import BuildableEnvelope

        wrong_area = BuildableEnvelope(
            corners=state["envelope"].corners,
            area_m2=state["envelope"].area_m2 + 5.0,
            width_m=state["envelope"].width_m,
            depth_m=state["envelope"].depth_m,
        )
        result = gate(state, envelope=wrong_area)
        assert not result.passed

    def test_failed_publication_rolls_back_previous_run(self, state, tmp_path, monkeypatch):
        # Regression (Codex M5 verification P2): if publication fails midway,
        # a previous complete run must remain fully intact - never mixed.
        import os as os_module

        from saudi_plot_design.export import pipeline as pipeline_module
        from saudi_plot_design.export.runlog import sha256_file

        out = tmp_path / "run"
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
            generation_timestamp="2026-07-13T00:00:00Z",
        )
        export_project(out, run_id="first-run", **kwargs)
        before = {p.name: sha256_file(p) for p in out.iterdir()}

        real_replace = os_module.replace

        def flaky_replace(src, dst):
            # Fail only when publishing the DXF out of staging; rollback
            # moves come from the backup dir and stay unaffected.
            if ".staging-" in str(src) and str(dst).endswith(".dxf"):
                raise PermissionError("destination file is locked")
            return real_replace(src, dst)

        monkeypatch.setattr(pipeline_module.os, "replace", flaky_replace)
        with pytest.raises(PermissionError):
            export_project(out, run_id="second-run", **kwargs)
        after = {p.name: sha256_file(p) for p in out.iterdir()}
        assert after == before  # fully old set restored, nothing mixed

    def test_nan_envelope_area_blocks(self, state):
        # Regression (Codex M5 verification round 2, P2): NaN defeats plain
        # comparisons; a non-finite envelope must block explicitly.
        from saudi_plot_design.model import BuildableEnvelope

        poisoned = BuildableEnvelope(
            corners=state["envelope"].corners,
            area_m2=float("nan"),
            width_m=state["envelope"].width_m,
            depth_m=state["envelope"].depth_m,
        )
        result = gate(state, envelope=poisoned)
        assert not result.passed
        assert any("non-finite" in r for r in result.reasons)

    def test_failed_rollback_preserves_backup(self, state, tmp_path, monkeypatch):
        # Regression (Codex M5 verification round 2, P1): if the rollback
        # itself fails, the backup directory (holding the only copies of the
        # previous outputs) must be preserved and reported.
        import os as os_module

        from saudi_plot_design.export import pipeline as pipeline_module

        out = tmp_path / "run"
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
            generation_timestamp="2026-07-13T00:00:00Z",
        )
        export_project(out, run_id="first-run", **kwargs)

        real_replace = os_module.replace

        def hostile_replace(src, dst):
            if ".staging-" in str(src) and str(dst).endswith(".dxf"):
                raise PermissionError("publish failed")
            if ".backup-" in str(src):
                raise PermissionError("restore failed too")
            return real_replace(src, dst)

        monkeypatch.setattr(pipeline_module.os, "replace", hostile_replace)
        with pytest.raises(RuntimeError, match="preserved in") as excinfo:
            export_project(out, run_id="second-run", **kwargs)
        backup_dirs = [p for p in out.iterdir() if p.name.startswith(".backup-")]
        assert backup_dirs, "backup directory must survive a failed rollback"
        preserved = list(backup_dirs[0].iterdir())
        assert any(p.name.endswith(".dxf") for p in preserved)
        assert str(backup_dirs[0]) in str(excinfo.value)

    def test_pdf_limitations_from_consumed_pack_data(self, state, tmp_path):
        # Regression (Codex M5 verification round 2, P2): the PDF limitations
        # must come from the consumed pack data so they always agree with the
        # run.json provenance record.
        from pypdf import PdfReader

        from saudi_plot_design.export.pdf import _write_pdf

        tampered_ref = state["pack_ref"].model_copy(
            update={"limitations": ("TAMPERED REFERENCE LIMITATION",)}
        )
        path = _write_pdf(
            tmp_path / "t.pdf",
            state["plot"],
            state["envelope"],
            state["rules"],
            state["concept"],
            state["match"],
            state["style_selection"],
            tampered_ref,
            state["pack_data"],
            state["selection"],
            state["facade"],
        )
        sheet2 = PdfReader(path).pages[1].extract_text()
        assert "TAMPERED REFERENCE LIMITATION" not in sheet2
        assert "synthetic placeholder" in sheet2  # from pack_data limitations

    @pytest.mark.parametrize("bad", ["../victim", "a/b", "a\\b", "C:\\x", "nested/victim"])
    def test_malicious_basename_rejected(self, state, tmp_path, bad):
        # Regression (Codex M5 full-diff review, high): basename must be a
        # single safe filename component.
        with pytest.raises(SpdInputError, match="basename .* must match"):
            export_project(
                tmp_path / "run",
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
                basename=bad,
                run_id="t",
                generation_timestamp="2026-07-13T00:00:00Z",
            )

    def test_manifest_published_last(self, state, tmp_path, monkeypatch):
        # Regression (Codex M5 full-diff review, high): a reader must never
        # observe run.json/manifest referencing not-yet-published drawings.
        import os as os_module

        from saudi_plot_design.export import pipeline as pipeline_module

        published: list[str] = []
        real_replace = os_module.replace

        def recording_replace(src, dst):
            if ".staging-" in str(src):
                published.append(str(dst).rsplit("\\", 1)[-1].rsplit("/", 1)[-1])
            return real_replace(src, dst)

        monkeypatch.setattr(pipeline_module.os, "replace", recording_replace)
        export_project(
            tmp_path / "run",
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
            run_id="order-check",
            generation_timestamp="2026-07-13T00:00:00Z",
        )
        assert published[-1] == "export_manifest.json"
        assert published[-2] == "run.json"
        assert set(published[:-2]) == {
            "saudi_plot_design_reference.pdf",
            "saudi_plot_design_reference.dxf",
            "architectural_quality_report.json",
            "architectural_quality_summary.md",
            "architectural_quality_overlay.svg",
        }

    def test_reversed_arabic_pack_ref_drift_blocks(self, state):
        # Regression (Codex M5 full-diff review, high): a same-id/version
        # reference with a reversed name_ar must never reach the exporters.
        reversed_name = state["pack_ref"].name_ar[::-1]
        tampered = state["pack_ref"].model_copy(update={"name_ar": reversed_name})
        result = gate(state, pack_ref=tampered)
        assert not result.passed
        assert any("does not match the consumed pack data" in r for r in result.reasons)

    def test_pack_content_fingerprint_drift_blocks(self, state):
        drifted_facade = state["facade"].model_copy(
            update={"style_pack_fingerprint": "deadbeef00000000"}
        )
        result = gate(state, facade=drifted_facade)
        assert not result.passed
        assert any("pack content fingerprint mismatch" in r for r in result.reasons)

    def test_stale_match_point_blocks(self, state):
        # Regression (Codex M5 full-diff review, medium): a match computed
        # for another coordinate (even in the same zone) must block.
        from saudi_plot_design.character.models import LocationPoint

        drifted = state["match"].model_copy(
            update={"point": LocationPoint(latitude=24.9, longitude=46.9)}
        )
        result = gate(state, match=drifted)
        assert not result.passed
        assert any("not the plot location" in r for r in result.reasons)

    def test_public_export_api_is_gate_enforcing_only(self):
        # Regression (Codex M5 full-diff review, high): the package exposes
        # only the gate-enforcing entry point; raw writers are private.
        import saudi_plot_design.export as export_package

        assert export_package.__all__ == ["export_project"]
        assert not hasattr(export_package, "write_pdf")
        assert not hasattr(export_package, "write_dxf")

    def test_old_audit_files_hidden_before_drawing_replacement(self, state, tmp_path, monkeypatch):
        # Regression (Codex M5 full-diff verification, P1): when overwriting
        # an existing export, the old run.json/manifest must be gone before
        # any drawing is replaced - a reader must never see old audit files
        # describing new drawings.
        import os as os_module

        from saudi_plot_design.export import pipeline as pipeline_module

        out = tmp_path / "run"
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
            generation_timestamp="2026-07-13T00:00:00Z",
        )
        export_project(out, run_id="first-run", **kwargs)

        real_replace = os_module.replace
        audit_seen_during_drawing_publish: list[str] = []

        def observing_replace(src, dst):
            if ".staging-" in str(src) and (str(dst).endswith(".pdf") or str(dst).endswith(".dxf")):
                audit_seen_during_drawing_publish.extend(
                    p.name for p in out.iterdir() if p.name in ("run.json", "export_manifest.json")
                )
            return real_replace(src, dst)

        monkeypatch.setattr(pipeline_module.os, "replace", observing_replace)
        export_project(out, run_id="second-run", **kwargs)
        assert audit_seen_during_drawing_publish == []
        # And the final state is complete.
        names = {p.name for p in out.iterdir()}
        assert {"run.json", "export_manifest.json"} <= names

    def test_pipeline_raises_with_specific_reasons(self, state, tmp_path):
        naked = state["facade"].model_copy(update={"disclaimer": ""})
        with pytest.raises(SpdInputError, match="export blocked: .*disclaimer"):
            export_project(
                tmp_path,
                plot=state["plot"],
                envelope=state["envelope"],
                rules=state["rules"],
                concept=state["concept"],
                match=state["match"],
                style_selection=state["style_selection"],
                pack_ref=state["pack_ref"],
                pack_data=state["pack_data"],
                selection=state["selection"],
                facade=naked,
                run_id="t",
                generation_timestamp="2026-07-13T00:00:00Z",
            )
        assert not list(tmp_path.iterdir())  # nothing written when blocked
