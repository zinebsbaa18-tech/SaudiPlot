"""Tests for the spd CLI (the locked single generate command)."""

import pytest

from saudi_plot_design.cli import main
from saudi_plot_design.output import DISCLAIMER

REFERENCE_ARGS = [
    "generate",
    "--csv",
    "samples/plot_20x30.csv",
    "--lat",
    "24.65",
    "--lon",
    "46.71",
    "--edges",
    "street,neighbor,neighbor,neighbor",
    "--street-width",
    "15",
]


def run(tmp_path, *extra, csv=True):
    args = (
        list(REFERENCE_ARGS)
        if csv
        else [
            "generate",
            "--width",
            "20",
            "--depth",
            "30",
            "--lat",
            "24.65",
            "--lon",
            "46.71",
            "--edges",
            "street,neighbor,neighbor,neighbor",
            "--street-width",
            "15",
        ]
    )
    args += ["--out", str(tmp_path / "run")] + list(extra)
    return main(args)


class TestCli:
    def test_full_generation_succeeds(self, tmp_path, capsys):
        code = run(tmp_path, "--confirm-character", "najdi", "--confirm-facade")
        out = capsys.readouterr().out
        assert code == 0
        names = {p.name for p in (tmp_path / "run").iterdir()}
        assert names == {
            "saudi_plot_design_reference.pdf",
            "saudi_plot_design_reference.dxf",
            "architectural_quality_report.json",
            "architectural_quality_summary.md",
            "architectural_quality_overlay.svg",
            "architectural_concept_sheet_set.pdf",
            "architectural_sheet_index.json",
            "architectural_sheet_manifest.json",
            "annotation_collision_report.json",
            "sheets",
            "run.json",
            "export_manifest.json",
        }
        assert DISCLAIMER in out
        assert "recommended character: najdi" in out
        assert "architectural quality:" in out
        assert "raw weighted score:" in out
        assert "coverage-adjusted score:" in out
        assert "evidence coverage:" in out
        assert "status constrained by:" in out
        assert "blocking findings:" in out
        assert "architectural_quality_report.json" in out
        assert "professional architectural sheets:" in out
        assert "architectural_concept_sheet_set.pdf" in out

    def test_width_depth_input_path(self, tmp_path):
        code = run(tmp_path, "--confirm-character", "najdi", "--confirm-facade", csv=False)
        assert code == 0
        assert (tmp_path / "run" / "run.json").is_file()

    def test_lookup_only_exits_2_and_writes_nothing(self, tmp_path, capsys):
        code = run(tmp_path)
        captured = capsys.readouterr()
        assert code == 2
        assert "recommended character: najdi" in captured.out
        assert DISCLAIMER in captured.out
        assert "--confirm-character najdi" in captured.err
        assert not (tmp_path / "run").exists()

    def test_unconfirmed_facade_exits_2_and_writes_nothing(self, tmp_path, capsys):
        code = run(tmp_path, "--confirm-character", "najdi")
        captured = capsys.readouterr()
        assert code == 2
        assert "primary facade: boundary plot-edge-1" in captured.err
        assert "--confirm-facade" in captured.err
        assert not (tmp_path / "run").exists()

    def test_unknown_character_exits_2(self, tmp_path, capsys):
        code = run(tmp_path, "--confirm-character", "hejazi", "--confirm-facade")
        captured = capsys.readouterr()
        assert code == 2
        assert "no installed style pack" in captured.err
        assert "najdi" in captured.err

    def test_override_without_reason_exits_2(self, tmp_path, capsys):
        # Location outside every demo zone -> confirming najdi is an override.
        args = [
            "generate",
            "--csv",
            "samples/plot_20x30.csv",
            "--lat",
            "20.0",
            "--lon",
            "50.0",
            "--edges",
            "street,neighbor,neighbor,neighbor",
            "--street-width",
            "15",
            "--confirm-character",
            "najdi",
            "--confirm-facade",
            "--out",
            str(tmp_path / "run"),
        ]
        code = main(args)
        captured = capsys.readouterr()
        assert code == 2
        assert "--override-reason" in captured.err
        assert not (tmp_path / "run").exists()

    def test_override_with_reason_succeeds(self, tmp_path):
        args = [
            "generate",
            "--csv",
            "samples/plot_20x30.csv",
            "--lat",
            "20.0",
            "--lon",
            "50.0",
            "--edges",
            "street,neighbor,neighbor,neighbor",
            "--street-width",
            "15",
            "--confirm-character",
            "najdi",
            "--confirm-facade",
            "--override-reason",
            "no demo zone covers the plot; client chose Najdi",
            "--out",
            str(tmp_path / "run"),
        ]
        assert main(args) == 0
        assert (tmp_path / "run" / "run.json").is_file()

    def test_bad_edges_exit_2(self, tmp_path, capsys):
        args = [
            "generate",
            "--csv",
            "samples/plot_20x30.csv",
            "--lat",
            "24.65",
            "--lon",
            "46.71",
            "--edges",
            "street,street,neighbor,neighbor",
            "--street-width",
            "15",
            "--out",
            str(tmp_path / "run"),
        ]
        code = main(args)
        assert code == 2
        assert "exactly one edge" in capsys.readouterr().err

    def test_both_csv_and_dimensions_rejected(self, tmp_path, capsys):
        code = run(tmp_path, "--width", "20", "--depth", "30")
        assert code == 2
        assert "either --csv OR --width" in capsys.readouterr().err

    def test_console_script_registered(self):
        from importlib.metadata import entry_points

        scripts = entry_points(group="console_scripts")
        spd = [ep for ep in scripts if ep.name == "spd"]
        assert spd and spd[0].value == "saudi_plot_design.cli:main"

    def test_no_placeholder_commands(self):
        # The locked MVP retains exactly one generation command. Owner-approved
        # post-MVP M7.1 adds one separate, fully implemented library group.
        from saudi_plot_design.cli import build_parser

        parser = build_parser()
        sub = next(
            a for a in parser._actions if isinstance(a, __import__("argparse")._SubParsersAction)
        )
        assert list(sub.choices) == ["generate", "library"]
        library = sub.choices["library"]
        library_sub = next(
            action
            for action in library._actions
            if isinstance(action, __import__("argparse")._SubParsersAction)
        )
        assert list(library_sub.choices) == [
            "ingest",
            "import-case",
            "list",
            "show",
            "apply-review",
            "archive",
            "rebuild-index",
            "validate",
            "prepare-review",
            "validate-review-package",
            "apply-corrections",
            "apply-architect-decision",
            "show-review-status",
        ]

    @pytest.mark.parametrize("flag", ["--lat", "--lon", "--edges", "--street-width", "--out"])
    def test_required_flags(self, tmp_path, flag, capsys):
        if flag == "--out":
            args = list(REFERENCE_ARGS)  # simply never append --out
        else:
            idx = REFERENCE_ARGS.index(flag)
            args = REFERENCE_ARGS[:idx] + REFERENCE_ARGS[idx + 2 :]
            args += ["--out", str(tmp_path / "run")]
        assert main(args) == 2
        # Regression (stop-gate): even argparse usage errors carry the
        # unconditional disclaimer.
        assert DISCLAIMER in capsys.readouterr().out

    def test_input_errors_carry_disclaimer(self, tmp_path, capsys):
        # Regression (stop-gate + review P2): SpdInputError paths include the
        # unconditional disclaimer too.
        code = run(tmp_path, "--width", "20", "--depth", "30")  # csv AND dims
        captured = capsys.readouterr()
        assert code == 2
        assert DISCLAIMER in captured.out
        assert "error:" in captured.err

    def test_planner_not_invoked_before_character_confirmation(self, tmp_path, monkeypatch):
        # Regression (stop-gate + review P1, ARCHITECTURE D3): lookup-only
        # mode must never reach the planner.
        import saudi_plot_design.planner.compact_3br as planner_module

        def forbidden(*args, **kwargs):
            raise AssertionError("planner invoked before character confirmation")

        monkeypatch.setattr(planner_module, "plan_compact_3br", forbidden)
        assert run(tmp_path) == 2  # lookup-only: recommendation + exit 2

    def test_real_invocations_are_byte_deterministic(self, tmp_path):
        # Regression: separate REAL invocations under DIFFERENT interpreter
        # hash seeds must yield byte-identical PDF/DXF - the DXF writer pins
        # the CLASSES-section order itself (ezdxf collects it from a set), so
        # no environment pinning or relaunch is needed for any caller.
        import os
        import subprocess
        import sys

        from saudi_plot_design.export.runlog import sha256_file

        for name, seed in (("a", "1"), ("b", "9973")):
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "saudi_plot_design.cli",
                    *REFERENCE_ARGS,
                    "--confirm-character",
                    "najdi",
                    "--confirm-facade",
                    "--out",
                    str(tmp_path / name),
                ],
                capture_output=True,
                cwd=".",
                env={**os.environ, "PYTHONHASHSEED": seed},  # force different seeds
            )
            assert result.returncode == 0, result.stderr.decode(errors="replace")
        for filename in (
            "saudi_plot_design_reference.pdf",
            "saudi_plot_design_reference.dxf",
            "architectural_quality_report.json",
            "architectural_quality_summary.md",
            "architectural_quality_overlay.svg",
        ):
            assert sha256_file(tmp_path / "a" / filename) == sha256_file(
                tmp_path / "b" / filename
            ), filename

    def test_run_json_echoes_all_cli_inputs(self, tmp_path):
        # Regression (review P2): run.json records every CLI input.
        import json

        run(tmp_path, "--confirm-character", "najdi", "--confirm-facade")
        payload = json.loads((tmp_path / "run" / "run.json").read_text(encoding="utf-8"))
        joined = " ".join(payload["source_inputs"])
        for needle in (
            "csv=samples",
            "lat=24.65",
            "lon=46.71",
            "edges=street,neighbor",
            "street_width=15",
            "confirm_character=najdi",
            "confirm_facade=True",
        ):
            assert needle in joined, needle
