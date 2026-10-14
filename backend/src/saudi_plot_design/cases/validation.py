"""Case ingestion validation (M6A): structured report, never fabricated data."""

from __future__ import annotations

from saudi_plot_design.cases.models import ArchitecturalDesignCase
from saudi_plot_design.model import ValidationCheck, ValidationReport

MIN_PLAUSIBLE_ROOM_M2 = 1.0
MAX_PLAUSIBLE_ROOM_M2 = 500.0


def validate_case(case: ArchitecturalDesignCase) -> ValidationReport:
    checks = (
        _check("K01", "IFC schema supported", _schema(case)),
        _check("K02", "metric units resolved", []),  # enforced at read time
        _check("K03", "spatial hierarchy present", _hierarchy(case)),
        _check("K04", "spaces have usable data", _spaces(case)),
        _check("K05", "walls have usable geometry", _walls(case)),
        _check("K06", "doors/windows have hosts or explicit warnings", _hosts(case)),
        _check("K07", "no duplicate GlobalIds", _duplicates(case)),
        _check("K08", "room areas plausible", _areas(case)),
        _check("K09", "no negative dimensions", _dimensions(case)),
        _check("K10", "relationships reference real objects", _references(case)),
        _check("K11", "source fingerprint recorded", _fingerprint(case)),
        _check("K12", "private data rules satisfied", _privacy(case)),
        _check("K13", "usage rights confirmed", _usage(case)),
    )
    return ValidationReport(checks=checks)


def _check(check_id, name, problems) -> ValidationCheck:
    return ValidationCheck(
        id=check_id,
        name=name,
        passed=not problems,
        details="; ".join(problems) if problems else "ok",
    )


def _schema(case) -> list[str]:
    if not case.provenance.ifc_schema.upper().startswith("IFC4"):
        return [f"schema '{case.provenance.ifc_schema}' unsupported"]
    return []


def _hierarchy(case) -> list[str]:
    return [] if case.levels else ["no building storeys extracted"]


def _spaces(case) -> list[str]:
    problems = []
    if not case.spaces:
        problems.append("no spaces extracted")
    level_ids = {level.ifc_global_id for level in case.levels}
    for space in case.spaces:
        if space.level_id not in level_ids:
            problems.append(f"space '{space.ifc_global_id}' references unknown level")
    return problems


def _walls(case) -> list[str]:
    problems = []
    if not case.walls:
        problems.append("no walls extracted")
    elif not any(w.start is not None and w.end is not None for w in case.walls):
        problems.append("no extracted wall has axis geometry")
    for wall in case.walls:
        if wall.start is not None and wall.end is not None and wall.start == wall.end:
            problems.append(f"wall '{wall.ifc_global_id}' has zero-length axis")
    return problems


def _hosts(case) -> list[str]:
    # Hostless openings are acceptable ONLY when an explicit warning records
    # them; the reader always emits one, so verify the pairing.
    problems = []
    for opening in list(case.doors) + list(case.windows):
        if opening.host_wall_id is None:
            recorded = any(opening.ifc_global_id in w or (opening.name in w) for w in case.warnings)
            if not recorded:
                problems.append(
                    f"{opening.kind} '{opening.ifc_global_id}' has no host and no warning"
                )
    return problems


def _duplicates(case) -> list[str]:
    ids = (
        [level.ifc_global_id for level in case.levels]
        + [s.ifc_global_id for s in case.spaces]
        + [w.ifc_global_id for w in case.walls]
        + [s.ifc_global_id for s in case.slabs]
        + [o.ifc_global_id for o in case.doors]
        + [o.ifc_global_id for o in case.windows]
    )
    duplicates = {i for i in ids if ids.count(i) > 1}
    return [f"duplicate GlobalId '{d}'" for d in sorted(duplicates)]


def _areas(case) -> list[str]:
    problems = []
    for space in case.spaces:
        if space.area_m2 is not None and not (
            MIN_PLAUSIBLE_ROOM_M2 <= space.area_m2 <= MAX_PLAUSIBLE_ROOM_M2
        ):
            problems.append(
                f"space '{space.name}' area {space.area_m2:g} m2 outside plausible range"
            )
    return problems


def _dimensions(case) -> list[str]:
    problems = []
    for wall in case.walls:
        for label, value in (
            ("length", wall.length_m),
            ("thickness", wall.thickness_m),
            ("height", wall.height_m),
        ):
            if value is not None and value <= 0:
                problems.append(f"wall '{wall.ifc_global_id}' has non-positive {label}")
    for opening in list(case.doors) + list(case.windows):
        for label, value in (("width", opening.width_m), ("height", opening.height_m)):
            if value is not None and value <= 0:
                problems.append(
                    f"{opening.kind} '{opening.ifc_global_id}' has non-positive {label}"
                )
    return problems


def _references(case) -> list[str]:
    known = {s.ifc_global_id for s in case.spaces}
    known |= {w.ifc_global_id for w in case.walls}
    known |= {o.ifc_global_id for o in case.doors} | {o.ifc_global_id for o in case.windows}
    problems = []
    wall_ids = {w.ifc_global_id for w in case.walls}
    for opening in list(case.doors) + list(case.windows):
        if opening.host_wall_id is not None and opening.host_wall_id not in wall_ids:
            problems.append(
                f"{opening.kind} '{opening.ifc_global_id}' references unknown "
                f"host wall '{opening.host_wall_id}'"
            )
    for edge in case.graphs.room_adjacency + case.graphs.circulation:
        for node in (edge.a, edge.b):
            if node not in known:
                problems.append(f"graph edge references unknown object '{node}'")
        if edge.via is not None and edge.via not in known:
            problems.append(f"graph edge via unknown object '{edge.via}'")
    for entrance in case.entrances:
        if entrance.door_id not in known:
            problems.append(f"entrance references unknown door '{entrance.door_id}'")
    return problems


def _fingerprint(case) -> list[str]:
    if len(case.provenance.source_fingerprint) != 64:
        return ["source fingerprint is not a sha256 hex digest"]
    return []


def _privacy(case) -> list[str]:
    problems = []
    display = case.provenance.source_directory_recorded
    if not display.startswith("private_cases/"):
        problems.append("recorded source path leaks outside private_cases/")
    if case.metadata.confidential and case.metadata.case_id in display:
        problems.append("recorded source path leaks the confidential case id")
    if case.metadata.anonymization_required:
        from saudi_plot_design.cases.metadata import ANONYMIZED, anonymize_text

        if anonymize_text(case.metadata.notes) != case.metadata.notes:
            problems.append("metadata notes still contain sensitive markers")
        if case.metadata.district is not None:
            problems.append("district must be dropped when anonymization is required")
        if case.metadata.approved_by not in (None, ANONYMIZED):
            problems.append("approved_by must be anonymized when required")
        # Re-verify every IFC-sourced string: scrubbing must be idempotent.
        texts: list[tuple[str, str | None]] = [("building_type", case.building_type)]
        texts.append(("site_note", case.site_note))
        texts += [(f"level '{level.ifc_global_id}'", level.name) for level in case.levels]
        texts += [
            (f"space '{s.ifc_global_id}' classification", c.source)
            for s in case.spaces
            for c in (s.space_type, s.zone)
        ]
        texts += [
            (f"entrance '{e.door_id}' classification", e.entrance_type.source)
            for e in case.entrances
        ]
        texts += [(f"space '{s.ifc_global_id}'", s.name) for s in case.spaces]
        texts += [(f"space '{s.ifc_global_id}' long name", s.long_name) for s in case.spaces]
        texts += [(f"wall '{w.ifc_global_id}'", w.name) for w in case.walls]
        texts += [(f"wall '{w.ifc_global_id}' material", w.material) for w in case.walls]
        texts += [(f"slab '{s.ifc_global_id}'", s.name) for s in case.slabs]
        texts += [
            (f"{o.kind} '{o.ifc_global_id}'", o.name) for o in list(case.doors) + list(case.windows)
        ]
        texts += [(f"warning {i}", w) for i, w in enumerate(case.warnings)]
        for label, text in texts:
            if text and anonymize_text(text) != text:
                problems.append(f"{label} still contains sensitive markers")
    return problems


def _usage(case) -> list[str]:
    return [] if case.metadata.usage_rights_confirmed else ["usage rights not confirmed"]
