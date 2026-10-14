"""Front-facade generator (M4): gate, projection, bounded Najdi template.

One deterministic vector elevation derived from real plan openings on the
confirmed street-facing walls, dimensioned exclusively by the loaded style
pack (single source of truth). No opening is ever invented, moved, resized,
duplicated, or removed; unsupported states return structured rejections.

Authored template constants (demo values of this template, documented):
- MIN_EDGE_CLEARANCE_M / MIN_OPENING_SPACING_M: facade composition minimums.
- Plinth height: midpoint of the pack's plinth range.
- Shading-canopy thickness reuses the pack's surround band width (the pack
  defines no separate canopy dimension; inventing one is not allowed).
- Fence/gate: NOT generated - the pack carries only a family id with no
  dimensional data, and this template does not invent constants.
"""

from __future__ import annotations

from saudi_plot_design.character.models import (
    CharacterMatch,
    GateResult,
    StylePackReference,
    StyleSelection,
)
from saudi_plot_design.character.selection import confirmation_gate
from saudi_plot_design.elevation.facade_selection import outward_normal
from saudi_plot_design.elevation.models import (
    GENERATION_VERSION,
    FacadeConcept,
    FacadeElement,
    FacadeOpening,
    FacadeWall,
    PrimaryFacadeSelection,
)
from saudi_plot_design.model import Concept, Corner, PlotModel
from saudi_plot_design.output import DISCLAIMER
from saudi_plot_design.styles.schema import StylePackData

MIN_EDGE_CLEARANCE_M = 0.3
MIN_OPENING_SPACING_M = 0.3
_TOL = 1e-6

ASSUMPTIONS: tuple[str, ...] = (
    "Facade X increases left-to-right as seen from the street (outward normal "
    "rotated 90 deg CCW); origin at the minimal-X facade end at finished ground.",
    "The facade spans all collinear street-facing external wall segments.",
    "Opening sill/head elevations come from the style pack, not plan nominals "
    "(the pack is the single source of facade dimensions).",
    "Plinth height is the midpoint of the pack's plinth range.",
    "Shading-canopy thickness reuses the pack's surround band width.",
    "Fence/gate omitted: the pack declares only a family id without dimensions.",
    "Single front elevation only; side/rear elevations are out of scope.",
    "DEMO design data - not an officially compliant Saudi elevation.",
)


def facade_generation_gate(
    plot: PlotModel | None,
    concept: Concept | None,
    selection: PrimaryFacadeSelection | None,
    match: CharacterMatch | None,
    style_selection: StyleSelection | None,
    pack_ref: StylePackReference | None,
    pack_data: StylePackData | None = None,
) -> GateResult:
    """Orchestration-level gate with specific blocking reasons."""
    reasons: list[str] = []
    if plot is None:
        reasons.append("plot geometry is missing")
    if concept is None or not concept.is_valid:
        reasons.append("floor-plan concept is missing or invalid")
    if selection is None:
        reasons.append("primary facade has not been selected")
    else:
        if not selection.user_confirmed:
            reasons.append("primary facade is not user-confirmed")
        if not selection.selected_building_wall_ids:
            reasons.append("no building wall faces the selected street boundary")
        # The confirmation binds the EXACT plot and plan concept via content
        # fingerprints - descriptive ids are not unique (two 20x30 plots with
        # the same street index share a plot_id), so ids alone must never
        # satisfy the binding.
        if plot is not None:
            if selection.project_id != plot.plot_id:
                reasons.append(
                    f"facade selection was confirmed for project '{selection.project_id}', "
                    f"not '{plot.plot_id}' - re-selection required"
                )
            elif selection.plot_fingerprint != plot.fingerprint:
                reasons.append(
                    "facade selection was confirmed for a different plot with the same "
                    "id (content fingerprint mismatch) - re-selection required"
                )
        if concept is not None:
            if selection.concept_id != concept.concept_id:
                reasons.append(
                    f"facade selection was confirmed for concept '{selection.concept_id}', "
                    f"not '{concept.concept_id}' - re-selection required"
                )
            elif selection.concept_fingerprint != concept.fingerprint:
                reasons.append(
                    "facade selection was confirmed for a different concept with the "
                    "same id (content fingerprint mismatch) - re-selection required"
                )
    if match is None:
        reasons.append("character lookup (CharacterMatch) is missing")
    style_gate = confirmation_gate(match, style_selection, pack_ref)
    if not style_gate.passed:
        reasons.extend(f"style gate: {r}" for r in style_gate.reasons)
    # The confirmation binds a specific pack VERSION: a selection confirmed
    # against one version must not silently consume data from another, and
    # the loaded data must be the pack the reference describes.
    if style_selection is not None and pack_ref is not None:
        if style_selection.style_pack_version is None:
            # A confirmed selection must record the exact version it was
            # confirmed against; a missing version (e.g. legacy persisted
            # data) cannot be bound to the loaded pack.
            reasons.append(
                "confirmed style selection records no pack version - re-confirmation required"
            )
        elif style_selection.style_pack_version != pack_ref.version:
            reasons.append(
                f"style was confirmed against pack version "
                f"{style_selection.style_pack_version}, but version "
                f"{pack_ref.version} is loaded - re-confirmation required"
            )
    if pack_ref is not None and pack_data is not None:
        if (
            pack_data.core.style_pack_id != pack_ref.style_pack_id
            or pack_data.core.version != pack_ref.version
        ):
            reasons.append("loaded style pack data does not match the confirmed pack reference")
    return GateResult(passed=not reasons, reasons=tuple(reasons))


def generate_front_facade(
    plot: PlotModel,
    concept: Concept,
    selection: PrimaryFacadeSelection,
    match: CharacterMatch,
    style_selection: StyleSelection,
    pack_ref: StylePackReference,
    pack_data: StylePackData,
) -> FacadeConcept:
    """Generate the single front facade, or return a structured rejection."""
    from saudi_plot_design.elevation.validation import validate_facade

    facade_id = f"facade-{concept.concept_id}-{selection.selected_plot_boundary_id}"

    gate = facade_generation_gate(
        plot, concept, selection, match, style_selection, pack_ref, pack_data
    )
    if not gate.passed:
        return _rejection(
            facade_id, plot, concept, selection, match, style_selection, pack_ref, gate.reasons
        )
    prerequisite_problems = _template_prerequisites(pack_data)
    if prerequisite_problems:
        return _rejection(
            facade_id,
            plot,
            concept,
            selection,
            match,
            style_selection,
            pack_ref,
            prerequisite_problems,
        )

    built = _build(plot, concept, selection, match, style_selection, pack_ref, pack_data, facade_id)
    if built.rejection_reasons:
        return built
    # Determinism proof: an independent rebuild must serialize identically.
    rebuilt = _build(
        plot, concept, selection, match, style_selection, pack_ref, pack_data, facade_id
    )
    deterministic = built.model_dump_json() == rebuilt.model_dump_json()
    report = validate_facade(
        built, plot, concept, selection, pack_data, deterministic=deterministic
    )
    if not report.passed:
        return built.model_copy(
            update={
                "validation": report,
                "rejection_reasons": tuple(
                    f"facade validation {c.id} failed: {c.details}" for c in report.failures()
                ),
            }
        )
    return built.model_copy(update={"validation": report})


_REQUIRED_TEMPLATE_MATERIALS = (
    "demo_earthen_render",
    "demo_painted_wood_trim",
    "demo_stone_plinth",
)
_REQUIRED_TEMPLATE_COLORS = 4


def _template_prerequisites(pack_data: StylePackData) -> list[str]:
    """The Najdi template's data requirements, checked up-front so a same-id
    pack lacking them yields a structured rejection, never an IndexError."""
    problems: list[str] = []
    material_ids = {m.id for m in pack_data.materials.material_palette}
    for required in _REQUIRED_TEMPLATE_MATERIALS:
        if required not in material_ids:
            problems.append(f"style pack lacks template material '{required}'")
    if len(pack_data.materials.color_palette_hex) < _REQUIRED_TEMPLATE_COLORS:
        problems.append(
            f"style pack provides {len(pack_data.materials.color_palette_hex)} colors; "
            f"the Najdi template needs {_REQUIRED_TEMPLATE_COLORS}"
        )
    rules = pack_data.facade_rules
    for name, values in (
        ("wall_treatment_ids", rules.wall_treatment_ids),
        ("window_group_ids", rules.window_group_ids),
        ("shading_element_ids", rules.shading_element_ids),
    ):
        if not values:
            problems.append(f"style pack declares no {name}; the Najdi template needs one")
    return problems


def _rejection(facade_id, plot, concept, selection, match, style_selection, pack_ref, reasons):
    return FacadeConcept(
        facade_concept_id=facade_id,
        project_id=plot.plot_id if plot else "unknown",
        plan_concept_id=concept.concept_id if concept else "unknown",
        plot_fingerprint=plot.fingerprint if plot else "",
        concept_fingerprint=concept.fingerprint if concept else "",
        primary_facade_selection=selection,
        character_match_zone_id=match.selected_zone_id if match else None,
        style_selection_method=style_selection.selection_method.value if style_selection else None,
        style_pack_id=pack_ref.style_pack_id if pack_ref else None,
        style_pack_version=pack_ref.version if pack_ref else None,
        assumptions=ASSUMPTIONS,
        rejection_reasons=tuple(reasons),
        generation_version=GENERATION_VERSION,
        disclaimer=DISCLAIMER,
    )


def _build(plot, concept, selection, match, style_selection, pack_ref, pack_data, facade_id):
    dims = pack_data.facade_rules.facade_dimensions
    walls = {w.id: w for w in concept.walls}
    facade_walls = [walls[wid] for wid in selection.selected_building_wall_ids]

    # Facade axes from the first segment (all segments are collinear).
    normal = outward_normal(plot, concept, facade_walls[0])
    x_dir: Corner = (-normal[1], normal[0])  # rotate +90 deg CCW

    endpoints: list[Corner] = []
    for wall in facade_walls:
        endpoints.extend((wall.start, wall.end))
    projections = [_dot(p, x_dir) for p in endpoints]
    origin = endpoints[projections.index(min(projections))]
    length = max(projections) - min(projections)

    def facade_x(point: Corner) -> float:
        return round(_dot((point[0] - origin[0], point[1] - origin[1]), x_dir), 6)

    plinth_range = pack_data.facade_rules.plinth_height_range_m
    plinth_h = round((plinth_range.min + plinth_range.max) / 2.0, 3)
    facade_wall = FacadeWall(
        source_plan_wall_ids=tuple(sorted(w.id for w in facade_walls)),
        length_m=round(length, 6),
        base_elevation_m=0.0,
        wall_height_m=dims.wall_height_m,
        parapet_height_m=dims.parapet_height_m,
        total_height_m=round(dims.wall_height_m + dims.parapet_height_m, 6),
        plinth_height_m=plinth_h,
        local_origin_world_xy=origin,
        x_axis_world_dir=(round(x_dir[0], 6), round(x_dir[1], 6)),
        outward_normal_world_dir=(round(normal[0], 6), round(normal[1], 6)),
    )

    openings, opening_problems = _project_openings(concept, facade_walls, facade_x, dims, pack_data)
    if opening_problems:
        return _rejection(
            facade_id, plot, concept, selection, match, style_selection, pack_ref, opening_problems
        )
    elements = _najdi_template_elements(facade_wall, openings, pack_data)

    return FacadeConcept(
        facade_concept_id=facade_id,
        project_id=plot.plot_id,
        plan_concept_id=concept.concept_id,
        plot_fingerprint=plot.fingerprint,
        concept_fingerprint=concept.fingerprint,
        style_pack_fingerprint=pack_data.fingerprint,
        primary_facade_selection=selection,
        character_match_zone_id=match.selected_zone_id,
        style_selection_method=style_selection.selection_method.value,
        style_pack_id=pack_ref.style_pack_id,
        style_pack_version=pack_ref.version,
        facade_wall=facade_wall,
        facade_openings=openings,
        facade_elements=elements,
        dimensions={
            "length_m": facade_wall.length_m,
            "wall_height_m": facade_wall.wall_height_m,
            "parapet_height_m": facade_wall.parapet_height_m,
            "total_height_m": facade_wall.total_height_m,
            "plinth_height_m": facade_wall.plinth_height_m,
        },
        assumptions=ASSUMPTIONS,
        warnings=(),
        generation_version=GENERATION_VERSION,
        disclaimer=DISCLAIMER,
    )


def _project_openings(concept, facade_walls, facade_x, dims, pack_data):
    """Project real plan doors/windows on the facade walls; never invent any."""
    facade_wall_ids = {w.id for w in facade_walls}
    walls = {w.id: w for w in concept.walls}
    openings: list[FacadeOpening] = []
    problems: list[str] = []
    window_height = dims.window_head_height_m - dims.window_sill_height_m
    ratio_range = pack_data.facade_rules.window_proportion_range_w_to_h

    for door in concept.doors:
        if door.wall_id not in facade_wall_ids:
            continue
        interval = _world_interval(walls[door.wall_id], door.position_m, door.width_m)
        xs = sorted(facade_x(p) for p in interval)
        treatment = pack_data.facade_rules.entrance_composition_options[0]
        openings.append(
            FacadeOpening(
                id=f"F-{door.id}",
                source_plan_opening_id=door.id,
                source_plan_wall_id=door.wall_id,
                source_room_id=door.to_space if door.to_space != "exterior" else door.from_space,
                opening_type="door",
                entrance_type=door.entrance_type,
                x_start_m=xs[0],
                width_m=door.width_m,
                sill_elevation_m=0.0,
                head_elevation_m=dims.door_head_height_m,
                style_treatment_id=treatment,
            )
        )
    for window in concept.windows:
        if window.wall_id not in facade_wall_ids:
            continue
        ratio = window.width_m / window_height
        if not (ratio_range.min - 1e-9 <= ratio <= ratio_range.max + 1e-9):
            problems.append(
                f"plan window '{window.id}' ({window.width_m:g} m wide) has w/h ratio "
                f"{ratio:.3f} outside the pack range "
                f"[{ratio_range.min:g}, {ratio_range.max:g}] - the plan is never "
                f"silently altered (unsupported state)"
            )
            continue
        if window.width_m > dims.window_max_width_m + 1e-9:
            problems.append(
                f"plan window '{window.id}' is wider than the pack maximum "
                f"{dims.window_max_width_m:g} m (unsupported state)"
            )
            continue
        interval = _world_interval(walls[window.wall_id], window.position_m, window.width_m)
        xs = sorted(facade_x(p) for p in interval)
        openings.append(
            FacadeOpening(
                id=f"F-{window.id}",
                source_plan_opening_id=window.id,
                source_plan_wall_id=window.wall_id,
                source_room_id=window.room_id,
                opening_type="window",
                x_start_m=xs[0],
                width_m=window.width_m,
                sill_elevation_m=dims.window_sill_height_m,
                head_elevation_m=dims.window_head_height_m,
                style_treatment_id=pack_data.facade_rules.window_group_ids[0],
            )
        )
    openings.sort(key=lambda o: (o.x_start_m, o.id))
    return tuple(openings), problems


def _world_interval(wall, position_m: float, width_m: float) -> tuple[Corner, Corner]:
    length = wall.length_m
    ux = (wall.end[0] - wall.start[0]) / length
    uy = (wall.end[1] - wall.start[1]) / length
    a = (wall.start[0] + ux * position_m, wall.start[1] + uy * position_m)
    b = (
        wall.start[0] + ux * (position_m + width_m),
        wall.start[1] + uy * (position_m + width_m),
    )
    return a, b


def _najdi_template_elements(facade_wall, openings, pack_data) -> tuple[FacadeElement, ...]:
    """The single bounded Najdi demo template - authored composition only."""
    rules = pack_data.facade_rules
    dims = rules.facade_dimensions
    colors = pack_data.materials.color_palette_hex
    # Prerequisites were verified by _template_prerequisites before _build.
    wall_mat, trim_mat, plinth_mat = _REQUIRED_TEMPLATE_MATERIALS
    length = facade_wall.length_m
    band_w = dims.surround_band_width_m
    elements: list[FacadeElement] = [
        FacadeElement(
            id="E-wall-body",
            element_type="wall_body",
            geometry=_rect(0.0, 0.0, length, dims.wall_height_m),
            source_rule_id=rules.wall_treatment_ids[0],
            material_id=wall_mat,
            color_hex=colors[0],
        ),
        FacadeElement(
            id="E-plinth",
            element_type="plinth",
            geometry=_rect(0.0, 0.0, length, facade_wall.plinth_height_m),
            source_rule_id=rules.wall_treatment_ids[0],
            material_id=plinth_mat,
            color_hex=colors[3],
            assumptions=("plinth height = midpoint of the pack plinth range",),
        ),
    ]
    elements.extend(_parapet_crenellation(facade_wall, rules, trim_mat, colors[2]))
    elements.append(
        FacadeElement(
            id="E-band",
            element_type="decorative_band",
            geometry=_rect(
                0.0, dims.ornament_band_elevation_m, length, dims.ornament_band_height_m
            ),
            source_rule_id=rules.wall_treatment_ids[min(1, len(rules.wall_treatment_ids) - 1)],
            material_id=trim_mat,
            color_hex=colors[1],
        )
    )
    for opening in openings:
        frame_type = "entrance_frame" if opening.opening_type == "door" else "window_frame"
        rule = (
            opening.style_treatment_id
            if opening.opening_type == "door"
            else rules.window_group_ids[0]
        )
        elements.append(
            FacadeElement(
                id=f"E-frame-{opening.id}",
                element_type=frame_type,
                geometry=_rect(
                    opening.x_start_m - band_w,
                    max(
                        opening.sill_elevation_m
                        - (band_w if opening.opening_type == "window" else 0.0),
                        0.0,
                    ),
                    opening.width_m + 2 * band_w,
                    (opening.head_elevation_m - opening.sill_elevation_m)
                    + band_w
                    + (band_w if opening.opening_type == "window" else 0.0),
                ),
                source_rule_id=rule,
                host_opening_id=opening.id,
                material_id=trim_mat,
                color_hex=colors[1],
            )
        )
        if opening.opening_type == "window":
            elements.append(
                FacadeElement(
                    id=f"E-shade-{opening.id}",
                    element_type="shading_canopy",
                    geometry=_rect(
                        opening.x_start_m - band_w,
                        opening.head_elevation_m + band_w,
                        opening.width_m + 2 * band_w,
                        band_w,
                    ),
                    source_rule_id=rules.shading_element_ids[0],
                    host_opening_id=opening.id,
                    material_id=trim_mat,
                    color_hex=colors[1],
                    assumptions=("canopy thickness reuses the pack surround band width",),
                )
            )
    return tuple(elements)


def _parapet_crenellation(facade_wall, rules, material_id, color_hex):
    dims = rules.facade_dimensions
    unit, gap = dims.parapet_unit_width_m, dims.parapet_gap_m
    z0 = facade_wall.wall_height_m
    z1 = facade_wall.total_height_m
    elements = []
    x = 0.0
    index = 1
    while x + unit <= facade_wall.length_m + _TOL:
        elements.append(
            FacadeElement(
                id=f"E-parapet-{index:02d}",
                element_type="parapet",
                geometry={
                    "kind": "polygon",
                    "points": [
                        [round(x, 6), z0],
                        [round(x + unit, 6), z0],
                        [round(x + unit / 2.0, 6), z1],
                    ],
                },
                source_rule_id=rules.parapet_family_ids[0],
                material_id=material_id,
                color_hex=color_hex,
            )
        )
        x += unit + gap
        index += 1
    return elements


def _rect(x: float, z: float, w: float, h: float) -> dict:
    return {
        "kind": "rect",
        "x": round(x, 6),
        "z": round(z, 6),
        "w": round(w, 6),
        "h": round(h, 6),
    }


def _dot(a: Corner, b: Corner) -> float:
    return a[0] * b[0] + a[1] * b[1]
