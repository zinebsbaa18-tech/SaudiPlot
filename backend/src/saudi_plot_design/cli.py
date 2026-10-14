"""The ``spd`` command-line interface.

Completing the locked MVP surface (LOCKED_MVP_SCOPE.md "Interface" row).
Every implemented flag works end to end - no placeholders. Lookup-only usage
is ``generate`` without ``--confirm-character`` (prints the recommendation
plus the unconditional DEMO disclaimer and exits 2, writing nothing).

Explicit gates surfaced as flags (the code-level gates from M3-M5 are never
bypassed): ``--confirm-character <slug>`` confirms the character
(``--override-reason`` is mandatory when the slug differs from the
recommendation), and ``--confirm-facade`` confirms the primary street
facade. Character slugs map to installed packs by the documented convention
``<slug>_demo_v<N>`` (najdi -> najdi_demo_v1).

M7.1 adds the separate local ``library`` command group.  Library commands do
not invoke generation and contain no template retrieval, ranking, or
adaptation. Exit codes: 0 success; 2 input/confirmation errors; 3 library
validation failure; 1 unexpected internal errors (traceback).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from saudi_plot_design.character.engine import load_zone_dataset, recommend_character
from saudi_plot_design.character.models import LocationPoint
from saudi_plot_design.character.selection import (
    confirm_selection,
    override_selection,
    recommend_style,
)
from saudi_plot_design.elevation.facade_selection import select_primary_facade
from saudi_plot_design.elevation.front import generate_front_facade
from saudi_plot_design.export.pipeline import export_project
from saudi_plot_design.model import SpdInputError
from saudi_plot_design.output import DISCLAIMER
from saudi_plot_design.plot.edges import parse_edge_classes
from saudi_plot_design.plot.geometry import (
    build_plot_model,
    corners_from_dimensions,
    load_corners_csv,
)
from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
from saudi_plot_design.styles.loader import load_pilot_style_pack


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spd",
        description=(
            "Saudi Plot Design Studio (DEMO) - one rectangular plot to a "
            "Saudi-character concept (PDF + DXF). All geographic and style "
            "data is DEMO, not official."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser(
        "generate",
        help="generate the concept and exports (the only command)",
        description="Without --confirm-character: prints the character "
        "recommendation and exits 2 (lookup-only mode, nothing written).",
    )
    g.add_argument("--csv", type=Path, help="plot corners CSV (id,x_m,y_m) - the only file format")
    g.add_argument("--width", type=float, help="plot width in m (alternative to --csv)")
    g.add_argument("--depth", type=float, help="plot depth in m (alternative to --csv)")
    g.add_argument("--lat", type=float, required=True, help="plot latitude (WGS84)")
    g.add_argument("--lon", type=float, required=True, help="plot longitude (WGS84)")
    g.add_argument(
        "--edges",
        required=True,
        help="comma-separated edge classes, e.g. street,neighbor,neighbor,neighbor",
    )
    g.add_argument("--street-width", type=float, required=True, help="street width in m (3-60)")
    g.add_argument(
        "--confirm-character",
        metavar="SLUG",
        help="explicitly confirm the character slug (e.g. najdi)",
    )
    g.add_argument(
        "--override-reason",
        help="mandatory reason when --confirm-character differs from the recommendation",
    )
    g.add_argument(
        "--confirm-facade",
        action="store_true",
        help="explicitly confirm the primary street facade",
    )
    g.add_argument(
        "--layout-mode",
        choices=("baseline", "optimized"),
        default="baseline",
        help=(
            "baseline preserves the approved authored layout (default); optimized runs "
            "the bounded deterministic M6.2 layout search"
        ),
    )
    g.add_argument(
        "--sheet-set",
        choices=("none", "concept", "review", "all"),
        default="concept",
        help=("professional M6.3 sheets: none, clean concept (default), design review, or both"),
    )
    g.add_argument(
        "--paper-size",
        choices=("A3",),
        default="A3",
        help="professional sheet paper size (M6.3 supports A3 only)",
    )
    g.add_argument(
        "--sheet-language",
        choices=("en",),
        default="en",
        help="professional sheet language (M6.3 supports English only)",
    )
    g.add_argument("--out", type=Path, required=True, help="output directory")
    from saudi_plot_design.library.commands import add_library_subparser

    add_library_subparser(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to legacy codepages; the disclaimer contains
    # an em dash and provenance contains Arabic - emit real UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    # The DEMO disclaimer remains unconditional on every legacy generation
    # path. M7.1 library JSON must remain machine-readable and does not consume
    # governed DEMO datasets, so it emits its own scope notice instead.
    if not effective_argv or effective_argv[0] != "library":
        print(DISCLAIMER)
    try:
        args = build_parser().parse_args(effective_argv)
    except SystemExit as exc:  # argparse printed its usage/error already
        code = int(exc.code or 0)
        if code != 0 and effective_argv[:1] == ["library"] and "--json" in effective_argv:
            # The library JSON contract holds even for argparse usage errors.
            import json

            print(
                json.dumps(
                    {"error": "invalid library command arguments", "exit_code": code},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        return code
    try:
        if args.command == "library":
            from pydantic import ValidationError

            from saudi_plot_design.library.commands import run_library_command

            try:
                return run_library_command(args)
            except ValidationError as exc:
                # Library CLI values (ids, versions, dates, rights) construct
                # models directly; their rejection is a user input error (2),
                # not an internal failure (1).
                first = exc.errors()[0]
                location = ".".join(str(part) for part in first["loc"])
                detail = f"{location}: {first['msg']}" if location else first["msg"]
                return _library_error(args, f"invalid library input: {detail}")
            except SpdInputError as exc:
                return _library_error(args, str(exc))
        return _generate(args)
    except SpdInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _library_error(args: argparse.Namespace, message: str) -> int:
    """Library failures honor --json: one machine-readable object, exit 2."""
    if getattr(args, "json_output", False):
        import json

        print(
            json.dumps(
                {"error": message, "exit_code": 2},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    else:
        print(f"error: {message}", file=sys.stderr)
    return 2


def _pack_slug(pack_id: str) -> str:
    """Documented convention: character slug = pack id before '_demo'."""
    return pack_id.split("_demo")[0]


def _generate(args: argparse.Namespace) -> int:
    if bool(args.csv) == (args.width is not None or args.depth is not None):
        raise SpdInputError("provide either --csv OR --width and --depth (not both, not neither)")
    if args.csv:
        corners = load_corners_csv(args.csv)
    else:
        if args.width is None or args.depth is None:
            raise SpdInputError("--width and --depth must be provided together")
        corners = corners_from_dimensions(args.width, args.depth)

    edges = parse_edge_classes(args.edges, len(corners))
    plot, _metrics = build_plot_model(
        corners, edges, args.street_width, location=(args.lat, args.lon)
    )
    rules = load_default_setback_rules()
    envelope = compute_envelope(plot, rules)

    dataset = load_zone_dataset()
    pack_ref, pack_data = load_pilot_style_pack(
        known_zone_ids=tuple(z.zone_id for z in dataset.zones)
    )
    installed_slug = _pack_slug(pack_ref.style_pack_id)
    match = recommend_character(dataset, LocationPoint(latitude=args.lat, longitude=args.lon))

    recommended_pack_id = (
        dataset.zone_by_id(match.selected_zone_id).style_pack_id if match.selected_zone_id else None
    )
    recommended_slug = _pack_slug(recommended_pack_id) if recommended_pack_id else None

    print(_recommendation_text(match, recommended_slug, installed_slug, pack_ref))

    if not args.confirm_character:
        print(
            f"\nno character confirmed - re-run with --confirm-character "
            f"{recommended_slug or installed_slug} (nothing was written)",
            file=sys.stderr,
        )
        return 2
    if args.confirm_character != installed_slug:
        raise SpdInputError(
            f"character '{args.confirm_character}' has no installed style pack; "
            f"installed characters: {installed_slug} (style pack: {pack_ref.style_pack_id})"
        )

    base_selection = recommend_style(match, recommended_pack_id)
    if recommended_pack_id == pack_ref.style_pack_id:
        style_selection = confirm_selection(base_selection, pack_ref)
    else:
        if not args.override_reason:
            raise SpdInputError(
                f"'{args.confirm_character}' is not the recommendation "
                f"({recommended_slug or 'no zone match'}); a manual override needs "
                f"--override-reason"
            )
        style_selection = override_selection(base_selection, pack_ref, args.override_reason)

    # D3: the planner runs ONLY after the character is explicitly confirmed
    # (or overridden with a reason) - never in lookup-only mode.
    from saudi_plot_design.planner.compact_3br import plan_compact_3br

    concept = plan_compact_3br(plot, envelope)
    if not concept.is_valid:
        for reason in concept.rejection_reasons:
            print(f"plan rejected: {reason}", file=sys.stderr)
        return 2

    optimization_result = None
    if args.layout_mode == "optimized":
        from saudi_plot_design.layout.engine import optimize_layout

        optimization_result = optimize_layout(concept, envelope)
        concept = optimization_result.selected_concept

    facade_selection = select_primary_facade(
        plot, concept, plot.street_edge_index, user_confirmed=args.confirm_facade
    )
    if not args.confirm_facade:
        print(
            f"\nprimary facade: boundary {facade_selection.selected_plot_boundary_id}, "
            f"walls {', '.join(facade_selection.selected_building_wall_ids) or '(none)'}\n"
            f"not confirmed - re-run with --confirm-facade (nothing was written)",
            file=sys.stderr,
        )
        return 2

    facade = generate_front_facade(
        plot, concept, facade_selection, match, style_selection, pack_ref, pack_data
    )
    if not facade.is_valid:
        for reason in facade.rejection_reasons:
            print(f"facade rejected: {reason}", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    manifest = export_project(
        args.out,
        plot=plot,
        envelope=envelope,
        rules=rules,
        concept=concept,
        match=match,
        style_selection=style_selection,
        pack_ref=pack_ref,
        pack_data=pack_data,
        selection=facade_selection,
        facade=facade,
        run_id=now.strftime("run-%Y%m%dT%H%M%SZ"),
        generation_timestamp=now.isoformat(timespec="seconds"),
        # Every CLI input is echoed for full traceability (run.json audit).
        source_inputs=[
            f"csv={args.csv}" if args.csv else f"width={args.width} depth={args.depth}",
            f"lat={args.lat}",
            f"lon={args.lon}",
            f"edges={args.edges}",
            f"street_width={args.street_width}",
            f"confirm_character={args.confirm_character}",
            f"override_reason={args.override_reason}",
            f"confirm_facade={args.confirm_facade}",
            f"layout_mode={args.layout_mode}",
            f"sheet_set={args.sheet_set}",
            f"paper_size={args.paper_size}",
            f"sheet_language={args.sheet_language}",
            f"out={args.out}",
        ],
        optimization_result=optimization_result,
        sheet_set=args.sheet_set,
        paper_size=args.paper_size,
        sheet_language=args.sheet_language,
    )
    print(f"\nexported to {args.out}:")
    for name, digest in manifest.file_sha256.items():
        print(f"  {name}  sha256 {digest[:16]}...")
    print("  export_manifest.json")
    overall_score = (
        "not rated"
        if manifest.quality_overall_score is None
        else f"{manifest.quality_overall_score:.2f}/100"
    )
    raw_score = (
        "not rated"
        if manifest.quality_raw_weighted_score is None
        else f"{manifest.quality_raw_weighted_score:.2f}/100"
    )
    adjusted_score = (
        "not rated"
        if manifest.quality_coverage_adjusted_score is None
        else f"{manifest.quality_coverage_adjusted_score:.2f}/100"
    )
    print(
        f"\narchitectural quality: {overall_score} "
        f"({manifest.quality_score_status})\n"
        f"  raw weighted score: {raw_score}\n"
        f"  coverage-adjusted score: {adjusted_score}\n"
        f"  evidence coverage: {manifest.quality_evidence_coverage:.2%}\n"
        f"  blocking findings: {manifest.quality_blocking_findings}\n"
        f"  major findings: {manifest.quality_major_findings}\n"
        f"  reports: {manifest.quality_report_path}, {manifest.quality_summary_path}, "
        f"{manifest.quality_overlay_path}"
    )
    if manifest.quality_status_constraints:
        print("  status constrained by:")
        for constraint_id in manifest.quality_status_constraints:
            print(f"    - {constraint_id}")
    if optimization_result is not None:
        baseline_quality = optimization_result.baseline_candidate.quality_assessment
        selected_quality = optimization_result.selected_candidate.quality_assessment
        baseline_major_ids = {
            finding.rule_id
            for finding in baseline_quality.findings
            if finding.severity.value == "major"
        }
        improved = [
            item.rule_id
            for item in optimization_result.finding_comparison
            if item.change == "improved" and item.rule_id in baseline_major_ids
        ]
        print(
            "\nlayout optimization:"
            f"\n  candidates generated: {optimization_result.generated_candidate_count}"
            f"\n  valid candidates: {optimization_result.valid_candidate_count}"
            f"\n  rejected candidates: {optimization_result.rejected_candidate_count}"
            f"\n  baseline effective score: {baseline_quality.overall_score:.2f}/100"
            f"\n  selected effective score: {selected_quality.overall_score:.2f}/100"
            f"\n  selected candidate: {optimization_result.selected_candidate_id}"
            f"\n  major findings resolved/improved: {', '.join(improved) or '(none)'}"
            "\n  reports: "
            f"{manifest.layout_optimization_report_path}, "
            f"{manifest.layout_candidate_comparison_path}, "
            f"{manifest.layout_optimization_overlay_path}"
        )
    if manifest.sheet_set_mode is not None:
        print(
            "\nprofessional architectural sheets:"
            f"\n  mode: {manifest.sheet_set_mode}"
            f"\n  profile: {manifest.sheet_graphic_profile_id}"
            f"\n  sheets: {', '.join(manifest.architectural_sheet_numbers)}"
            f"\n  concept PDF: {manifest.sheet_concept_pdf_path or '(not generated)'}"
            f"\n  review PDF: {manifest.sheet_review_pdf_path or '(not generated)'}"
            f"\n  index: {manifest.architectural_sheet_index_path}"
            f"\n  manifest: {manifest.architectural_sheet_manifest_path}"
            f"\n  unresolved annotation collisions: "
            f"{manifest.architectural_sheet_unresolved_collisions}"
        )
    return 0


def _recommendation_text(match, recommended_slug, installed_slug, pack_ref) -> str:
    if match.selected_zone_id:
        head = (
            f"recommended character: {recommended_slug or '(zone has no installed pack)'} "
            f"(zone {match.selected_zone_id}, confidence {match.confidence_level} "
            f"{match.confidence_value})"
        )
    else:
        head = "no demo zone contains this location - manual character selection required"
    warnings = "".join(f"\n  warning: {w}" for w in match.warnings)
    return (
        f"{head}{warnings}\n"
        f"installed characters: {installed_slug} "
        f"(style pack: {pack_ref.style_pack_id} v{pack_ref.version})"
    )


if __name__ == "__main__":
    raise SystemExit(main())
