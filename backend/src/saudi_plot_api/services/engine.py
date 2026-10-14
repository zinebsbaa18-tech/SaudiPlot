"""Adapter over the deterministic core engine (saudi_plot_design).

Calls the existing engine through plain Python functions -- the exact same
orchestration the ``spd generate`` CLI performs -- and never through a shell.
The core remains untouched: no HTTP, database, Gemini, or storage code enters
``saudi_plot_design`` (ADR-WEB-001).

Honesty contract (docs/WEB_BACKEND_SCOPE.md, HONEST DEMO POLICY):

* The core generation gate accepts ONLY the validated 20 m x 30 m reference
  rectangle. A plot record with different dimensions does not fail silently
  and is not faked: the run proceeds on the reference plot and records an
  explicit assumption, finishing as ``completed_with_assumptions``.
* The planner produces the authored Compact 3BR skeleton. Questionnaire and
  room-catalogue answers are persisted and reported, and every answer the
  planner does not yet apply geometrically is listed in
  ``unapplied_answers`` -- never claimed as applied.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from saudi_plot_api.services import storage

REFERENCE_WIDTH_M = 20.0
REFERENCE_DEPTH_M = 30.0
DEFAULT_STREET_WIDTH_M = 15.0

# Output files safe for sanitized share links: verified coordinate-free
# design artifacts only. The reference PDF and sheet PDFs print the exact
# WGS84 location (export/pdf.py, sheets/engine.py) and therefore stay private
# to the owning session, as do run.json (input echoes) and quality reports.
_SHAREABLE_KINDS = {"dxf", "svg_plan", "svg_elevation"}

_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".dxf": "image/vnd.dxf",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".md": "text/markdown",
    ".png": "image/png",
}


@dataclass
class EngineInputs:
    width_m: float
    height_m: float
    latitude: float | None
    longitude: float | None
    street_width_m: float | None
    boundaries: dict | None
    answers: dict | None
    room_counts: dict | None


@dataclass
class EngineResult:
    support_status: str
    assumptions: list[str]
    unapplied_answers: list[dict]
    unsupported: list[str]
    design_fingerprint: str | None = None
    character: dict | None = None
    summary: dict | None = None
    files: list[dict] = field(default_factory=list)
    plan_svg_relative_path: str | None = None


class EngineRejection(Exception):
    """The core engine rejected the inputs (honest structured refusal)."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _street_width_from_boundaries(boundaries: dict | None) -> float | None:
    """Parse a street width from deed boundary descriptions like
    'على شارع عرض 20 م'. Returns None when no street is mentioned."""
    streets = _street_boundaries(boundaries)
    return streets[0][2] if streets else None


# Boundary direction -> edge index on the reference rectangle
# (corners (0,0),(W,0),(W,H),(0,H); edge i runs corner i -> i+1).
_BOUNDARY_EDGE_INDEX = {"south": 0, "east": 1, "north": 2, "west": 3}


def _street_boundaries(boundaries: dict | None) -> list[tuple[str, int, float | None]]:
    """Every boundary that mentions a street: (direction, edge_index, width|None),
    widest first so the primary frontage choice is deterministic."""
    if not boundaries:
        return []
    found = []
    for direction, text in boundaries.items():
        if direction not in _BOUNDARY_EDGE_INDEX or not text or "شارع" not in str(text):
            continue
        match = re.search(r"عرض\s*(\d+(?:\.\d+)?)", str(text))
        width = float(match.group(1)) if match else None
        if width is not None and not (3.0 <= width <= 60.0):
            width = None
        found.append((direction, _BOUNDARY_EDGE_INDEX[direction], width))
    found.sort(key=lambda item: -(item[2] or 0.0))
    return found


def _frontage(inputs: EngineInputs) -> tuple[int, float, list[str]]:
    """Street edge index + width from the confirmed boundaries, with explicit
    assumptions for everything that had to be defaulted."""
    notes: list[str] = []
    streets = _street_boundaries(inputs.boundaries)
    if streets:
        direction, edge_index, width = streets[0]
        if len(streets) > 1:
            notes.append(
                "Multiple street boundaries are recorded on the deed; the widest "
                f"({direction}) was used as the primary frontage."
            )
        if width is None:
            width = inputs.street_width_m or DEFAULT_STREET_WIDTH_M
        return edge_index, width, notes
    notes.append(
        "No boundary description identifies a street; the frontage was assumed on "
        "the south boundary (reference edge 0)."
    )
    return 0, inputs.street_width_m or DEFAULT_STREET_WIDTH_M, notes


def plan_support(inputs: EngineInputs) -> tuple[str, list[str], list[dict], list[str]]:
    """Decide supported / supported_with_assumptions / unsupported_requirements
    for the current engine, with every deviation stated explicitly."""
    assumptions: list[str] = []
    unapplied: list[dict] = []
    unsupported: list[str] = []

    if inputs.width_m <= 0 or inputs.height_m <= 0:
        unsupported.append("plot dimensions must be positive numbers")
    is_reference = (
        abs(inputs.width_m - REFERENCE_WIDTH_M) < 0.01
        and abs(inputs.height_m - REFERENCE_DEPTH_M) < 0.01
    )
    if not is_reference and not unsupported:
        assumptions.append(
            f"The current engine generates only its validated {REFERENCE_WIDTH_M:g} m x "
            f"{REFERENCE_DEPTH_M:g} m reference plot. Your recorded plot "
            f"({inputs.width_m:g} m x {inputs.height_m:g} m) is stored but NOT applied "
            "geometrically; the generated design uses the reference plot."
        )

    street = inputs.street_width_m or _street_width_from_boundaries(inputs.boundaries)
    if street is None:
        assumptions.append(
            f"No street width was provided or parseable from the deed boundaries; the "
            f"reference street width of {DEFAULT_STREET_WIDTH_M:g} m was assumed."
        )

    # Every persisted answer the Compact 3BR planner does not consume is
    # reported -- the planner takes no user program inputs today.
    if inputs.answers:
        for key in sorted(inputs.answers):
            unapplied.append(
                {
                    "answer": key,
                    "value": inputs.answers[key],
                    "note": "persisted; not yet applied geometrically by the Compact 3BR planner",
                }
            )
    if inputs.room_counts:
        unapplied.append(
            {
                "answer": "room_catalog",
                "value": inputs.room_counts,
                "note": (
                    "persisted; the generated plan is the authored Compact 3BR skeleton, "
                    "not a layout derived from these room counts"
                ),
            }
        )
    if unapplied:
        assumptions.append(
            "The generated plan is the authored Compact 3BR skeleton; the persisted "
            "questionnaire and room-catalogue answers listed under unapplied_answers "
            "are not yet applied geometrically."
        )

    if unsupported:
        return "unsupported_requirements", assumptions, unapplied, unsupported
    if assumptions:
        return "supported_with_assumptions", assumptions, unapplied, unsupported
    return "supported", assumptions, unapplied, unsupported


def resolve_engine_character(latitude: float | None, longitude: float | None) -> dict:
    """The core character engine's own deterministic recommendation (demo
    zone dataset), independent of the advisory geo knowledge."""
    from saudi_plot_design.character.engine import load_zone_dataset, recommend_character
    from saudi_plot_design.character.models import LocationPoint

    dataset = load_zone_dataset()
    if latitude is None or longitude is None:
        return {
            "selected_zone_id": None,
            "confidence_level": None,
            "warnings": ["no coordinates provided"],
        }
    match = recommend_character(dataset, LocationPoint(latitude=latitude, longitude=longitude))
    return {
        "selected_zone_id": match.selected_zone_id,
        "confidence_level": match.confidence_level,
        "confidence_value": match.confidence_value,
        "warnings": list(match.warnings),
    }


def run_engine(
    inputs: EngineInputs, out_dir: Path, storage_root: Path, run_id: str
) -> EngineResult:
    """Execute the deterministic pipeline into ``out_dir`` (inside the storage
    root) and describe every produced file."""
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
    from saudi_plot_design.layout.engine import optimize_layout
    from saudi_plot_design.planner.compact_3br import plan_compact_3br
    from saudi_plot_design.plot.geometry import build_plot_model, corners_from_dimensions
    from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
    from saudi_plot_design.styles.loader import load_pilot_style_pack

    support_status, assumptions, unapplied, unsupported = plan_support(inputs)
    if unsupported:
        raise EngineRejection(unsupported)

    # Coordinates are used as a pair or not at all -- a half-supplied pair is
    # never mixed with defaults into a fabricated location.
    if inputs.latitude is not None and inputs.longitude is not None:
        latitude, longitude = inputs.latitude, inputs.longitude
    else:
        latitude, longitude = 24.65, 46.71
        assumptions.append(
            "No complete coordinate pair was provided; the engine's demo reference "
            "location was assumed for the character lookup."
        )

    corners = corners_from_dimensions(REFERENCE_WIDTH_M, REFERENCE_DEPTH_M)
    # The street edge comes from the confirmed boundary data (which side the
    # deed says faces a street), never a hard-coded frontage.
    street_edge_index, street_width, frontage_notes = _frontage(inputs)
    assumptions.extend(frontage_notes)
    edges = tuple(
        "street" if index == street_edge_index else "neighbor" for index in range(len(corners))
    )
    from saudi_plot_design.plot.edges import parse_edge_classes

    plot, _metrics = build_plot_model(
        corners,
        parse_edge_classes(",".join(edges), len(corners)),
        street_width,
        location=(latitude, longitude),
    )
    rules = load_default_setback_rules()
    envelope = compute_envelope(plot, rules)

    dataset = load_zone_dataset()
    pack_ref, pack_data = load_pilot_style_pack(
        known_zone_ids=tuple(z.zone_id for z in dataset.zones)
    )
    match = recommend_character(dataset, LocationPoint(latitude=latitude, longitude=longitude))
    recommended_pack_id = (
        dataset.zone_by_id(match.selected_zone_id).style_pack_id if match.selected_zone_id else None
    )
    base_selection = recommend_style(match, recommended_pack_id)
    if recommended_pack_id == pack_ref.style_pack_id:
        style_selection = confirm_selection(base_selection, pack_ref)
        character_note = "core demo zone recommendation matches the installed pack"
    else:
        override_reason = (
            "demo journey: only the najdi_demo_v1 pilot style pack is installed; applied "
            "outside its demo zone with this recorded reason"
        )
        style_selection = override_selection(base_selection, pack_ref, override_reason)
        character_note = override_reason
        assumptions.append(
            "The location is outside the installed pack's demo zone; the najdi_demo_v1 "
            "pilot style pack was applied with a recorded override reason."
        )

    concept = plan_compact_3br(plot, envelope)
    if not concept.is_valid:
        raise EngineRejection(list(concept.rejection_reasons))

    optimization_result = optimize_layout(concept, envelope)
    concept = optimization_result.selected_concept

    facade_selection = select_primary_facade(
        plot, concept, plot.street_edge_index, user_confirmed=True
    )
    facade = generate_front_facade(
        plot, concept, facade_selection, match, style_selection, pack_ref, pack_data
    )
    if not facade.is_valid:
        raise EngineRejection(list(facade.rejection_reasons))

    # Every assumption appended after plan_support (default location, frontage
    # defaults, out-of-zone pack override) must be reflected in the support
    # status -- a run with assumptions is never reported as plainly supported.
    if assumptions and support_status == "supported":
        support_status = "supported_with_assumptions"

    now = datetime.now(timezone.utc)
    manifest = export_project(
        str(out_dir),
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
        run_id=run_id,
        generation_timestamp=now.isoformat(timespec="seconds"),
        source_inputs=[
            f"width={inputs.width_m}",
            f"height={inputs.height_m}",
            f"street_width={street_width}",
            "engine_plot=reference_20x30",
            f"support_status={support_status}",
        ],
        optimization_result=optimization_result,
        sheet_set="concept",
        paper_size="A3",
        sheet_language="en",
    )

    files = _register_files(out_dir, storage_root)
    fingerprint = _design_fingerprint(run_id, support_status, files)

    plan_svg = next(
        (f["relative_path"] for f in files if f["kind"] == "svg_plan"),
        None,
    )
    quality = {
        "quality_overall_score": manifest.quality_overall_score,
        "quality_score_status": manifest.quality_score_status,
        "quality_blocking_findings": manifest.quality_blocking_findings,
        "quality_major_findings": manifest.quality_major_findings,
        "sheet_numbers": list(manifest.architectural_sheet_numbers or ()),
        "style_pack": f"{pack_ref.style_pack_id} v{pack_ref.version}",
        "engine_plan": "compact_3br_reference_20x30",
        "street_edge_index": street_edge_index,
        "street_width_m": street_width,
    }
    character = {
        "engine_zone_id": match.selected_zone_id,
        "engine_confidence_level": match.confidence_level,
        "applied_style_pack": pack_ref.style_pack_id,
        "note": character_note,
    }
    return EngineResult(
        support_status=support_status,
        assumptions=assumptions,
        unapplied_answers=unapplied,
        unsupported=[],
        design_fingerprint=fingerprint,
        character=character,
        summary=quality,
        files=files,
        plan_svg_relative_path=plan_svg,
    )


def _classify(relative_name: str) -> str:
    name = relative_name.replace("\\", "/")
    if name.endswith(".dxf"):
        return "dxf"
    if name == "saudi_plot_design_reference.pdf":
        return "pdf"
    if name.endswith(".pdf"):
        return "sheet_pdf"
    if "ground-floor-plan" in name and name.endswith(".svg"):
        return "svg_plan"
    if "elevation" in name and name.endswith(".svg"):
        return "svg_elevation"
    if name.endswith(".svg"):
        return "svg"
    if name == "run.json":
        return "run_json"
    if name.endswith(".json"):
        return "report_json"
    return "report"


def _register_files(out_dir: Path, storage_root: Path) -> list[dict]:
    root = storage.storage_root(storage_root)
    files = []
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        digest, size = storage.file_digest(path)
        relative_to_root = path.resolve().relative_to(root).as_posix()
        relative_name = path.relative_to(out_dir).as_posix()
        kind = _classify(relative_name)
        suffix = path.suffix.lower()
        files.append(
            {
                "kind": kind,
                "filename": path.name,
                "relative_path": relative_to_root,
                "content_type": _CONTENT_TYPES.get(suffix, "application/octet-stream"),
                "sha256": digest,
                "size_bytes": size,
                "shareable": kind in _SHAREABLE_KINDS,
            }
        )
    return files


def _design_fingerprint(run_id: str, support_status: str, files: list[dict]) -> str:
    payload = json.dumps(
        {
            "run_id": run_id,
            "support_status": support_status,
            "files": {f["relative_path"]: f["sha256"] for f in files},
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
