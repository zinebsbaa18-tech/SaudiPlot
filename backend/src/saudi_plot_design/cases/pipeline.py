"""M6A ingestion orchestrator: private IFC source -> reviewable case outputs.

Reads from the private source directory (never copies source files into
tracked paths), assembles the canonical ArchitecturalDesignCase, validates,
and writes the review artifact set into a gitignored output directory. The
resulting state stops at ``requires_review`` (or ``corrected`` when a manual
corrections file exists); only an explicit human review decision file can
move a case further.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from saudi_plot_design.cases.eligibility import (
    TemplateEligibilityError,
    evaluate_template_eligibility,
    record_template_eligibility,
)
from saudi_plot_design.cases.ifc_reader import IfcExtraction, read_ifc_case
from saudi_plot_design.cases.metadata import (
    ANONYMIZED,
    anonymize_metadata,
    anonymize_text,
    enforce_usage_rights,
    load_case_metadata,
    safe_source_display,
)
from saudi_plot_design.cases.models import (
    ArchitecturalDesignCase,
    CaseOpening,
    CaseSlab,
    CaseState,
    CaseWall,
    Entrance,
    Level,
    Space,
)
from saudi_plot_design.cases.relationships import build_graphs, compute_metrics
from saudi_plot_design.cases.semantics import (
    apply_entrance_correction,
    apply_space_correction,
    classify_entrance,
    classify_space,
    load_corrections,
)
from saudi_plot_design.cases.svg_case_preview import render_case_preview
from saudi_plot_design.cases.validation import validate_case
from saudi_plot_design.model import SpdInputError, content_fingerprint

ASSUMPTIONS: tuple[str, ...] = (
    "Semantic IFC extraction only: no geometry tessellation; missing source "
    "data yields warnings, never fabricated values.",
    "Adjacency requires IfcRelSpaceBoundary; circulation requires door host "
    "walls bounding exactly two spaces.",
    "All classifications require human review; nothing is silently guessed.",
    "This case is NOT an approved template until a human architect supplies "
    "an explicit review decision.",
    "Template eligibility is evaluated independently from review state; "
    "non-residential and stress-test cases can be reviewed but never approved as templates.",
)


def ingest_case(source_dir: str | Path, out_dir: str | Path) -> ArchitecturalDesignCase:
    source_dir = Path(source_dir)
    metadata = anonymize_metadata(load_case_metadata(source_dir))
    enforce_usage_rights(metadata)

    model_path = source_dir / "model.ifc"
    extraction = read_ifc_case(model_path)
    if metadata.anonymization_required:
        # IFC text fields (room/wall/site names, materials) commonly carry
        # client or address details; scrub them before anything downstream
        # (classifications, warnings, outputs) can echo them.
        _anonymize_extraction(extraction)
    corrections = load_corrections(source_dir)
    if metadata.anonymization_required:
        # Correction reviewer names are embedded in Classification.source;
        # anonymized artifacts must carry only the redaction marker.
        for section in ("spaces", "entrances"):
            for entry in (corrections.get(section) or {}).values():
                if isinstance(entry, dict) and entry.get("reviewer"):
                    entry["reviewer"] = ANONYMIZED
    warnings = list(extraction.warnings)

    space_to_walls: dict[str, list[str]] = {}
    for wall_id, bounded in extraction.wall_to_spaces.items():
        for space_id in bounded:
            space_to_walls.setdefault(space_id, []).append(wall_id)

    spaces = []
    for raw in extraction.spaces:
        space_type, zone = classify_space(raw.name, raw.long_name)
        space_type, zone = apply_space_correction(corrections, raw.global_id, space_type, zone)
        spaces.append(
            Space(
                ifc_global_id=raw.global_id,
                name=raw.name,
                long_name=raw.long_name,
                level_id=raw.level_id,
                area_m2=raw.area_m2,
                height_m=raw.height_m,
                space_type=space_type,
                zone=zone,
                boundary_wall_ids=tuple(sorted(space_to_walls.get(raw.global_id, []))),
                is_external=extraction.space_external_flags.get(raw.global_id, False),
            )
        )
    spaces = tuple(spaces)
    space_ids = {s.ifc_global_id for s in spaces}
    unknown_targets = set((corrections.get("spaces") or {})) - space_ids
    if unknown_targets:
        raise SpdInputError(
            f"review_corrections.json references unknown space GlobalId(s): "
            f"{sorted(unknown_targets)}"
        )

    walls = tuple(
        CaseWall(
            ifc_global_id=raw.global_id,
            name=raw.name,
            level_id=raw.level_id,
            start=raw.start,
            end=raw.end,
            length_m=raw.length_m,
            thickness_m=raw.thickness_m,
            height_m=raw.height_m,
            is_external=raw.is_external,
            material=raw.material,
            bounded_space_ids=tuple(
                sorted(sid for sid in extraction.wall_to_spaces.get(raw.global_id, []))
            ),
        )
        for raw in extraction.walls
    )
    wall_by_id = {w.ifc_global_id: w for w in walls}

    doors: list[CaseOpening] = []
    windows: list[CaseOpening] = []
    for raw in extraction.openings:
        host_wall_id = raw.host_wall_id
        if host_wall_id is not None and host_wall_id not in wall_by_id:
            # The IFC host exists but its wall was not extracted (e.g. no
            # storey containment) - a dangling reference must not pass as a
            # valid host.
            warnings.append(
                f"{raw.kind} '{raw.global_id}' references host wall "
                f"'{host_wall_id}' that was not extracted; host cleared"
            )
            host_wall_id = None
        host = wall_by_id.get(host_wall_id) if host_wall_id else None
        bounded = tuple(sid for sid in (host.bounded_space_ids if host else ()) if sid in space_ids)
        is_external = bool(host.is_external) if host else False
        opening = CaseOpening(
            ifc_global_id=raw.global_id,
            name=raw.name,
            kind=raw.kind,
            level_id=raw.level_id,
            host_wall_id=host_wall_id,
            width_m=raw.width_m,
            height_m=raw.height_m,
            sill_height_m=raw.sill_height_m,
            connects_space_ids=bounded,
            is_external=is_external,
        )
        (doors if raw.kind == "door" else windows).append(opening)
    doors_t, windows_t = tuple(doors), tuple(windows)
    door_ids = {d.ifc_global_id for d in doors_t}
    unknown_doors = set((corrections.get("entrances") or {})) - door_ids
    if unknown_doors:
        raise SpdInputError(
            f"review_corrections.json references unknown door GlobalId(s): {sorted(unknown_doors)}"
        )

    space_type_by_id = {s.ifc_global_id: s.space_type.value for s in spaces}
    entrances = []
    for door in doors_t:
        if not door.is_external:
            continue
        into = door.connects_space_ids[0] if len(door.connects_space_ids) == 1 else None
        if into is None and door.connects_space_ids:
            warnings.append(
                f"external door '{door.ifc_global_id}' bounds several spaces; "
                f"entrance target unresolved"
            )
        classification = classify_entrance(space_type_by_id.get(into or ""))
        classification = apply_entrance_correction(corrections, door.ifc_global_id, classification)
        entrances.append(
            Entrance(door_id=door.ifc_global_id, entrance_type=classification, into_space_id=into)
        )
    entrances_t = tuple(entrances)

    graphs = build_graphs(spaces, doors_t, entrances_t, extraction.wall_to_spaces, warnings)
    external_wall_counts = {
        s.ifc_global_id: sum(
            1 for wid in s.boundary_wall_ids if wid in wall_by_id and wall_by_id[wid].is_external
        )
        for s in spaces
    }
    metrics = compute_metrics(spaces, external_wall_counts, entrances_t)
    facade_openings = tuple(
        sorted(o.ifc_global_id for o in list(doors_t) + list(windows_t) if o.is_external)
    )

    from saudi_plot_design.cases.models import SourceProvenance

    source_fingerprint = hashlib.sha256(model_path.read_bytes()).hexdigest()
    metadata_fingerprint = content_fingerprint(metadata.model_dump_json())
    provenance = SourceProvenance(
        source_directory_recorded=safe_source_display(source_dir, metadata),
        source_format=metadata.source_format,
        ifc_schema=extraction.schema,
        source_fingerprint=source_fingerprint,
        metadata_fingerprint=metadata_fingerprint,
        review_binding_fingerprint="",  # filled from the derived content below
        ownership_status="rights_holder_confirmed_usage"
        if metadata.usage_rights_confirmed
        else "unconfirmed",
        permitted_usage="internal case-library review and, only after template "
        "eligibility plus explicit architect approval, template derivation",
        confidentiality_status="confidential" if metadata.confidential else "internal",
        anonymization_status="anonymized" if metadata.anonymization_required else "not_required",
        project_code=metadata.case_id,
        reviewer=None,
        approval_status=metadata.approval_status,
    )

    # "corrected" is earned only by corrections that actually changed a
    # classification - a corrections file with no effect must not suggest a
    # review happened.
    applied_corrections = sum(
        1
        for s in spaces
        if s.space_type.method == "manual_correction" or s.zone.method == "manual_correction"
    ) + sum(1 for e in entrances_t if e.entrance_type.method == "manual_correction")
    state = CaseState.CORRECTED if applied_corrections else CaseState.REQUIRES_REVIEW
    case = ArchitecturalDesignCase(
        case_id=metadata.case_id,
        state=state,
        metadata=metadata,
        provenance=provenance,
        building_type=extraction.building_type,
        site_note=extraction.site_note,
        levels=tuple(
            Level(ifc_global_id=level.global_id, name=level.name, elevation_m=level.elevation_m)
            for level in extraction.levels
        ),
        spaces=spaces,
        walls=walls,
        slabs=tuple(
            CaseSlab(
                ifc_global_id=raw.global_id,
                name=raw.name,
                level_id=raw.level_id,
                thickness_m=raw.thickness_m,
                area_m2=raw.area_m2,
            )
            for raw in extraction.slabs
        ),
        doors=doors_t,
        windows=windows_t,
        entrances=entrances_t,
        graphs=graphs,
        facade_openings=facade_openings,
        metrics=metrics,
        assumptions=ASSUMPTIONS,
        warnings=tuple(warnings),
    )
    # Validation runs first so the binding can cover the complete review
    # result. None of the checks read review_binding_fingerprint, so this
    # ordering stays consistent.
    case = case.model_copy(update={"validation": validate_case(case)})
    case = record_template_eligibility(case)
    # A review decision only counts for the exact content the reviewer saw:
    # the model bytes, the metadata, AND the derived review artifacts
    # (including the validation report) - so a change in extractor,
    # classifier, or validation behavior also invalidates the binding.
    derived = case.model_dump(mode="json")
    derived.pop("provenance")
    review_binding = content_fingerprint(
        source_fingerprint
        + ":"
        + metadata_fingerprint
        + ":"
        + json.dumps(derived, sort_keys=True, ensure_ascii=False)
    )
    case = case.model_copy(
        update={
            "provenance": provenance.model_copy(
                update={"review_binding_fingerprint": review_binding}
            )
        }
    )
    case = apply_review_decision(case, source_dir)
    _write_outputs(case, Path(out_dir))
    return case


def apply_review_decision(
    case: ArchitecturalDesignCase, source_dir: Path
) -> ArchitecturalDesignCase:
    """Only an explicit human review file can move a case past review states."""
    path = Path(source_dir) / "review_decision.json"
    if not path.is_file():
        return case
    try:
        decision = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpdInputError(f"review_decision.json is not valid JSON: {exc}") from None
    state_value = decision.get("state")
    allowed = {
        CaseState.ARCHITECT_REVIEWED.value,
        CaseState.APPROVED_TEMPLATE.value,
        CaseState.REJECTED.value,
    }
    if state_value not in allowed:
        raise SpdInputError(
            f"review_decision.json state must be one of {sorted(allowed)}, got '{state_value}'"
        )
    reviewer = decision.get("reviewed_by")
    review_date = decision.get("review_date")
    if not reviewer or not review_date:
        raise SpdInputError(
            "review_decision.json requires reviewed_by and review_date - a case "
            "cannot advance without an accountable human reviewer"
        )
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise SpdInputError(
            "review_decision.json reviewed_by must be a non-empty string naming "
            "the accountable human reviewer"
        )
    reviewer = reviewer.strip()
    if not isinstance(review_date, str):
        raise SpdInputError(
            f"review_decision.json review_date must be an ISO date string "
            f"(YYYY-MM-DD), got {type(review_date).__name__}"
        )
    try:
        date.fromisoformat(review_date)
    except ValueError:
        raise SpdInputError(
            f"review_decision.json review_date '{review_date}' is not a valid ISO date (YYYY-MM-DD)"
        ) from None
    bound_to = decision.get("case_fingerprint")
    if bound_to != case.provenance.review_binding_fingerprint:
        raise SpdInputError(
            "review_decision.json case_fingerprint "
            f"'{bound_to}' does not match this case's review binding "
            f"'{case.provenance.review_binding_fingerprint}' - the source model, "
            "metadata, or corrections changed after the review; the case must "
            "be re-reviewed (copy the fingerprint from case_manifest.json)"
        )
    if state_value == CaseState.APPROVED_TEMPLATE.value:
        eligibility = evaluate_template_eligibility(case)
        if not eligibility.template_eligible:
            raise TemplateEligibilityError(eligibility.template_ineligibility_reasons)
    if case.metadata.anonymization_required:
        # The accountable name stays in the private review_decision.json;
        # published artifacts carry only the redaction marker.
        reviewer = ANONYMIZED
    reviewed_case = case.model_copy(
        update={
            "state": CaseState(state_value),
            "provenance": case.provenance.model_copy(
                update={"reviewer": reviewer, "review_date": review_date}
            ),
        }
    )
    return record_template_eligibility(reviewed_case)


def _anonymize_extraction(extraction: IfcExtraction) -> None:
    """Scrub every free-text field that leaves the private source directory."""
    for level in extraction.levels:
        level.name = anonymize_text(level.name)
    for space in extraction.spaces:
        space.name = anonymize_text(space.name)
        space.long_name = anonymize_text(space.long_name) if space.long_name else None
    for wall in extraction.walls:
        wall.name = anonymize_text(wall.name)
        wall.material = anonymize_text(wall.material) if wall.material else None
    for slab in extraction.slabs:
        slab.name = anonymize_text(slab.name)
    for opening in extraction.openings:
        opening.name = anonymize_text(opening.name)
    extraction.site_note = anonymize_text(extraction.site_note) if extraction.site_note else None
    extraction.building_type = anonymize_text(extraction.building_type)
    extraction.warnings = [anonymize_text(w) for w in extraction.warnings]


def _write_outputs(case: ArchitecturalDesignCase, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    def write(name: str, payload) -> tuple[str, str]:
        path = out_dir / name
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        path.write_text(text, encoding="utf-8", newline="\n")
        return name, hashlib.sha256(text.encode("utf-8")).hexdigest()

    dump = case.model_dump(mode="json")
    hashes = dict(
        [
            write("architectural_case.json", dump),
            write("spaces.json", dump["spaces"]),
            write(
                "elements.json",
                {
                    "walls": dump["walls"],
                    "slabs": dump["slabs"],
                    "doors": dump["doors"],
                    "windows": dump["windows"],
                },
            ),
            write("adjacency_graph.json", dump["graphs"]["room_adjacency"]),
            write("circulation_graph.json", dump["graphs"]["circulation"]),
            write(
                "facade_openings.json",
                {"external_opening_ids": dump["facade_openings"], "entrances": dump["entrances"]},
            ),
            write("metrics.json", dump["metrics"]),
            write("validation_report.json", dump["validation"]),
            write("review_corrections_template.json", _corrections_template(case)),
        ]
    )
    svg = render_case_preview(case)
    (out_dir / "plan_preview.svg").write_text(svg, encoding="utf-8", newline="\n")
    hashes["plan_preview.svg"] = hashlib.sha256(svg.encode("utf-8")).hexdigest()
    write(
        "case_manifest.json",
        {
            "schema_version": case.schema_version,
            "case_id": case.case_id,
            "state": case.state.value,
            "template_eligible": case.template_eligible,
            "template_ineligibility_reasons": list(case.template_ineligibility_reasons),
            "source_fingerprint": case.provenance.source_fingerprint,
            "metadata_fingerprint": case.provenance.metadata_fingerprint,
            "review_binding_fingerprint": case.provenance.review_binding_fingerprint,
            "reviewer": case.provenance.reviewer,
            "review_date": case.provenance.review_date,
            "confidentiality_status": case.provenance.confidentiality_status,
            "anonymization_status": case.provenance.anonymization_status,
            "files_sha256": dict(sorted(hashes.items())),
            "note": "review artifacts only - the source model was read in place "
            "and never copied into tracked paths",
        },
    )


def _corrections_template(case: ArchitecturalDesignCase) -> dict:
    return {
        "_instructions": (
            "Reviewer: fill corrected values (blank means unchanged) and save "
            "this file as review_corrections.json inside the private case "
            "source directory, then re-run ingestion. To advance the case "
            "state, add review_decision.json with {state, reviewed_by, "
            "review_date, case_fingerprint} where case_fingerprint is the "
            "review_binding_fingerprint from case_manifest.json of the run "
            "you reviewed. approved_template is accepted only when the "
            "reviewed manifest also records template_eligible=true."
        ),
        "spaces": {
            s.ifc_global_id: {
                "name": s.name,
                "current_space_type": s.space_type.value,
                "current_confidence": s.space_type.confidence,
                "space_type": "",
                "zone": "",
                "reviewer": "",
            }
            for s in case.spaces
        },
        "entrances": {
            e.door_id: {
                "current_entrance_type": e.entrance_type.value,
                "entrance_type": "",
                "reviewer": "",
            }
            for e in case.entrances
        },
    }
