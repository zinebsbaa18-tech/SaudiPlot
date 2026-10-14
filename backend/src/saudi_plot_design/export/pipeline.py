"""Export orchestrator: gate -> drawings/quality -> run.json -> manifest."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from saudi_plot_design.export.binding import export_gate
from saudi_plot_design.export.dxf import _write_dxf
from saudi_plot_design.export.pdf import _write_pdf
from saudi_plot_design.export.runlog import (
    ExportManifest,
    build_run_json,
    sha256_file,
    write_json,
)
from saudi_plot_design.layout.overlay import write_optimization_overlay_svg
from saudi_plot_design.layout.geometry import geometry_fingerprint
from saudi_plot_design.layout.reporting import (
    write_candidate_comparison_csv,
    write_optimization_report,
)
from saudi_plot_design.model import SpdInputError
from saudi_plot_design.quality.evaluator import evaluate_architectural_quality
from saudi_plot_design.quality.overlay import write_quality_overlay_svg
from saudi_plot_design.quality.reporting import (
    write_quality_report,
    write_quality_summary_markdown,
)
from saudi_plot_design.sheets.export import export_architectural_sheets

BASENAME = "saudi_plot_design_reference"
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_QUALITY_FILES = (
    "architectural_quality_report.json",
    "architectural_quality_summary.md",
    "architectural_quality_overlay.svg",
)
_OPTIMIZATION_FILES = (
    "layout_optimization_report.json",
    "layout_candidate_comparison.csv",
    "layout_optimization_overlay.svg",
)
_AUDIT_FILES = (*_QUALITY_FILES, *_OPTIMIZATION_FILES, "run.json", "export_manifest.json")
_SHEET_OUTPUTS = (
    "architectural_concept_sheet_set.pdf",
    "architectural_review_sheet_set.pdf",
    "architectural_sheet_index.json",
    "architectural_sheet_manifest.json",
    "annotation_collision_report.json",
    "sheets",
)
_AUDIT_FILES = (*_AUDIT_FILES, *_SHEET_OUTPUTS)


def export_project(
    out_dir: str | Path,
    *,
    plot,
    envelope,
    rules,
    concept,
    match,
    style_selection,
    pack_ref,
    pack_data,
    selection,
    facade,
    run_id: str,
    generation_timestamp: str,
    source_inputs: list[str] | None = None,
    basename: str = BASENAME,
    optimization_result=None,
    sheet_set: str = "none",
    paper_size: str = "A3",
    sheet_language: str = "en",
) -> ExportManifest:
    """Run the export pipeline; raises SpdInputError with specific reasons
    when the binding/safety gate blocks."""
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise SpdInputError(f"run_id '{run_id}' must match [A-Za-z0-9._-]+ (no path separators)")
    if not _RUN_ID_PATTERN.fullmatch(basename):
        raise SpdInputError(
            f"basename '{basename}' must match [A-Za-z0-9._-]+ (single filename "
            f"component, no path separators)"
        )
    if optimization_result is not None and (
        optimization_result.selected_concept.fingerprint != concept.fingerprint
    ):
        raise SpdInputError(
            "export blocked: optimization result does not select the supplied concept"
        )
    if optimization_result is not None:
        _verify_optimization_result(optimization_result, concept, envelope)
    if sheet_set not in {"none", "concept", "review", "all"}:
        raise SpdInputError(f"unsupported sheet set '{sheet_set}'")
    if paper_size != "A3":
        raise SpdInputError("M6.3 supports only --paper-size A3")
    if sheet_language != "en":
        raise SpdInputError("M6.3 supports only --sheet-language en")
    gate = export_gate(
        plot,
        envelope,
        rules,
        concept,
        match,
        style_selection,
        pack_ref,
        pack_data,
        selection,
        facade,
    )
    if not gate.passed:
        raise SpdInputError("export blocked: " + "; ".join(gate.reasons))

    # No partial output: everything is generated in a staging directory
    # (random name via mkdtemp, guaranteed inside out_dir and independent of
    # caller-provided metadata) and published with rollback.
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=out_dir))
    try:
        manifest = _export_into(
            staging,
            basename=basename,
            plot=plot,
            envelope=envelope,
            rules=rules,
            concept=concept,
            match=match,
            style_selection=style_selection,
            pack_ref=pack_ref,
            pack_data=pack_data,
            selection=selection,
            facade=facade,
            run_id=run_id,
            generation_timestamp=generation_timestamp,
            source_inputs=source_inputs,
            optimization_result=optimization_result,
            sheet_set=sheet_set,
        )
        _publish_with_rollback(staging, out_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return manifest


def _verify_optimization_result(optimization_result, concept, envelope) -> None:
    """Recompute the canonical M6.2 search before trusting audit metadata."""
    from saudi_plot_design.layout.engine import optimize_layout
    from saudi_plot_design.layout.geometry import geometry_fingerprint

    selected = optimization_result.selected_candidate
    baseline = optimization_result.baseline_candidate
    if not selected.is_valid or not selected.eligible_for_selection or selected.rejection:
        raise SpdInputError(
            "export blocked: optimization result selected an invalid or ineligible candidate"
        )
    if (
        selected.concept is None
        or selected.validation != selected.concept.validation
        or selected.geometry_fingerprint != geometry_fingerprint(selected.concept)
    ):
        raise SpdInputError(
            "export blocked: selected optimization geometry or validation audit is inconsistent"
        )
    if baseline.concept is None or not baseline.concept.is_valid:
        raise SpdInputError("export blocked: optimization result has no valid baseline concept")
    recomputed = optimize_layout(
        baseline.concept,
        envelope,
        config=optimization_result.config,
    )
    if recomputed.model_dump(mode="json") != optimization_result.model_dump(mode="json"):
        raise SpdInputError(
            "export blocked: optimization assessments, ranking, audit, or comparison are stale"
        )
    if recomputed.selected_concept.fingerprint != concept.fingerprint:
        raise SpdInputError(
            "export blocked: recomputed optimization result does not select the supplied concept"
        )


def _publication_order(staging: Path) -> list[Path]:
    """Deliverables first, run.json next, manifest LAST - a reader can never
    observe a manifest/audit file referencing not-yet-published outputs."""

    def rank(p: Path) -> tuple[int, str]:
        if p.name == "export_manifest.json":
            return (3, p.name)
        if p.name == "run.json":
            return (2, p.name)
        return (1, p.name)

    return sorted(staging.iterdir(), key=rank)


def _publish_with_rollback(staging: Path, out_dir: Path) -> None:
    """Replace the destination set as one transaction (best effort).

    A true atomic multi-file swap is not available cross-platform, so this
    backs up existing destinations first and rolls everything back if any
    replacement fails - the destination ends up either fully old or fully
    new, never mixed. Documented limitation: the MVP is a single-user,
    single-process tool (NOT_NOW.md excludes collaboration/queues), so
    concurrent exporters into one directory are out of scope.
    """
    backup = Path(tempfile.mkdtemp(prefix=".backup-", dir=out_dir))
    placed: list[Path] = []

    def remove(path: Path) -> None:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)

    try:
        # Phase 1: displace any EXISTING audit files first - a reader must
        # never see old run.json/manifest describing drawings that are being
        # replaced underneath them (no audit file at all beats a lying one).
        for name in _AUDIT_FILES:
            existing = out_dir / name
            if existing.exists():
                os.replace(existing, backup / name)
        # Phase 2: deliverables, then the new audit files last.
        for staged in _publication_order(staging):
            dest = out_dir / staged.name
            if dest.exists():
                os.replace(dest, backup / staged.name)
            os.replace(staged, dest)
            placed.append(dest)
    except BaseException:
        # Remove everything newly placed, then restore EVERY backed-up file -
        # including one displaced by the very replacement that failed. If the
        # rollback itself fails, the backup directory is PRESERVED (it may
        # hold the only copies of previous outputs) and its path is reported.
        try:
            for dest in placed:
                remove(dest)
            for previous in backup.iterdir():
                os.replace(previous, out_dir / previous.name)
        except BaseException as rollback_error:
            raise RuntimeError(
                f"export publication failed and rollback also failed; previous "
                f"outputs are preserved in '{backup}' - restore them manually"
            ) from rollback_error
        shutil.rmtree(backup, ignore_errors=True)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def _export_into(
    staging: Path,
    *,
    basename: str,
    plot,
    envelope,
    rules,
    concept,
    match,
    style_selection,
    pack_ref,
    pack_data,
    selection,
    facade,
    run_id: str,
    generation_timestamp: str,
    source_inputs,
    optimization_result,
    sheet_set,
) -> ExportManifest:
    pdf_path = _write_pdf(
        staging / f"{basename}.pdf",
        plot,
        envelope,
        rules,
        concept,
        match,
        style_selection,
        pack_ref,
        pack_data,
        selection,
        facade,
    )
    dxf_path = _write_dxf(
        staging / f"{basename}.dxf",
        plot,
        envelope,
        rules,
        concept,
        match,
        pack_ref,
        selection,
        facade,
    )
    quality_assessment = evaluate_architectural_quality(concept, envelope)
    quality_report_path = write_quality_report(
        staging / "architectural_quality_report.json", quality_assessment
    )
    quality_summary_path = write_quality_summary_markdown(
        staging / "architectural_quality_summary.md", quality_assessment
    )
    quality_overlay_path = write_quality_overlay_svg(
        staging / "architectural_quality_overlay.svg", concept, quality_assessment
    )
    optimization_paths = ()
    if optimization_result is not None:
        optimization_paths = (
            write_optimization_report(
                staging / "layout_optimization_report.json", optimization_result
            ),
            write_candidate_comparison_csv(
                staging / "layout_candidate_comparison.csv", optimization_result
            ),
            write_optimization_overlay_svg(
                staging / "layout_optimization_overlay.svg", optimization_result
            ),
        )
    sheet_export = None
    sheet_paths = ()
    if sheet_set != "none":
        sheet_export = export_architectural_sheets(
            staging,
            plot=plot,
            envelope=envelope,
            rules=rules,
            concept=concept,
            facade=facade,
            pack_ref=pack_ref,
            pack_data=pack_data,
            quality_assessment=quality_assessment,
            candidate_id=(
                optimization_result.selected_candidate_id
                if optimization_result is not None
                else "baseline"
            ),
            generation_timestamp=generation_timestamp,
            mode=sheet_set,
        )
        sheet_paths = tuple(staging / relative for relative in sheet_export.output_paths)
    deliverables = (
        pdf_path,
        dxf_path,
        quality_report_path,
        quality_summary_path,
        quality_overlay_path,
        *optimization_paths,
        *sheet_paths,
    )

    def relative(path: Path) -> str:
        return path.relative_to(staging).as_posix()

    output_hashes = {relative(path): sha256_file(path) for path in deliverables}
    output_files = {relative(path): relative(path) for path in deliverables}
    run_payload = build_run_json(
        run_id=run_id,
        generation_timestamp=generation_timestamp,
        plot=plot,
        envelope=envelope,
        rules=rules,
        concept=concept,
        match=match,
        style_selection=style_selection,
        pack_ref=pack_ref,
        pack_data=pack_data,
        selection=selection,
        facade=facade,
        source_inputs=source_inputs or [],
        # Paths are recorded relative to the export directory so the audit
        # artifact stays deterministic and portable.
        output_files=output_files,
        output_hashes=output_hashes,
        quality_assessment=quality_assessment,
        optimization_result=optimization_result,
        sheet_export=sheet_export,
    )
    run_path = write_json(staging / "run.json", run_payload)

    manifest = ExportManifest(
        schema_version=3
        if sheet_export is not None
        else (2 if optimization_result is not None else 1),
        pdf_path=pdf_path.name,
        dxf_path=dxf_path.name,
        quality_report_path=quality_report_path.name,
        quality_summary_path=quality_summary_path.name,
        quality_overlay_path=quality_overlay_path.name,
        run_json_path=run_path.name,
        file_sizes_bytes={
            relative(path): path.stat().st_size for path in (*deliverables, run_path)
        },
        file_sha256={**output_hashes, relative(run_path): sha256_file(run_path)},
        plot_fingerprint=plot.fingerprint,
        concept_fingerprint=concept.fingerprint,
        facade_concept_id=facade.facade_concept_id,
        validation_status="all_gates_passed",
        quality_assessment_version=quality_assessment.assessment_version,
        quality_criteria_profile_id=quality_assessment.criteria_profile.profile_id,
        quality_criteria_profile_version=quality_assessment.criteria_profile.profile_version,
        quality_raw_weighted_score=quality_assessment.raw_weighted_score,
        quality_evidence_coverage=quality_assessment.evidence_coverage,
        quality_coverage_adjusted_score=quality_assessment.coverage_adjusted_score,
        quality_overall_score=quality_assessment.overall_score,
        quality_score_status=quality_assessment.score_status.value,
        quality_status_constraints=tuple(
            constraint.constraint_id for constraint in quality_assessment.status_constraints
        ),
        quality_blocking_findings=sum(
            finding.severity.value == "blocking" and finding.status.value in {"warning", "fail"}
            for finding in quality_assessment.findings
        ),
        quality_major_findings=sum(
            finding.severity.value == "major" and finding.status.value in {"warning", "fail"}
            for finding in quality_assessment.findings
        ),
        layout_mode="optimized" if optimization_result is not None else None,
        layout_engine_version=(
            optimization_result.engine_version if optimization_result is not None else None
        ),
        layout_selected_candidate_id=(
            optimization_result.selected_candidate_id if optimization_result is not None else None
        ),
        layout_candidates_generated=(
            optimization_result.generated_candidate_count
            if optimization_result is not None
            else None
        ),
        layout_candidates_valid=(
            optimization_result.valid_candidate_count if optimization_result is not None else None
        ),
        layout_candidates_rejected=(
            optimization_result.rejected_candidate_count
            if optimization_result is not None
            else None
        ),
        layout_optimization_report_path=(
            optimization_paths[0].name if optimization_paths else None
        ),
        layout_candidate_comparison_path=(
            optimization_paths[1].name if optimization_paths else None
        ),
        layout_optimization_overlay_path=(
            optimization_paths[2].name if optimization_paths else None
        ),
        sheet_set_mode=sheet_export.mode if sheet_export is not None else None,
        sheet_graphic_profile_id=(sheet_export.profile_id if sheet_export is not None else None),
        sheet_source_candidate_id=(
            optimization_result.selected_candidate_id
            if sheet_export is not None and optimization_result is not None
            else ("baseline" if sheet_export is not None else None)
        ),
        sheet_source_geometry_fingerprint=(
            geometry_fingerprint(concept) if sheet_export is not None else None
        ),
        sheet_concept_pdf_path=(
            sheet_export.concept_pdf_path if sheet_export is not None else None
        ),
        sheet_review_pdf_path=(sheet_export.review_pdf_path if sheet_export is not None else None),
        architectural_sheet_index_path=(
            sheet_export.sheet_index_path if sheet_export is not None else None
        ),
        architectural_sheet_manifest_path=(
            sheet_export.sheet_manifest_path if sheet_export is not None else None
        ),
        annotation_collision_report_path=(
            sheet_export.collision_report_path if sheet_export is not None else None
        ),
        architectural_sheet_svg_paths=(sheet_export.svg_paths if sheet_export is not None else ()),
        architectural_sheet_numbers=(
            sheet_export.sheet_numbers if sheet_export is not None else ()
        ),
        architectural_sheet_validation_status=(
            sheet_export.validation_status if sheet_export is not None else None
        ),
        architectural_sheet_unresolved_collisions=(
            sheet_export.unresolved_collision_count if sheet_export is not None else None
        ),
        disclaimer_status="unconditional_demo_disclaimer_embedded",
    )
    write_json(
        staging / "export_manifest.json",
        manifest.model_dump(mode="json", exclude_none=True),
    )
    return manifest
