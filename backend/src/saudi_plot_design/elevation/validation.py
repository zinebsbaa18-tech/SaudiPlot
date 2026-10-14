"""Facade validation - the fixed 24-check list (M4). Nothing beyond it:
no structural, wind, waterproofing, thermal, daylight, municipality,
accessibility, or door-swing analysis (NOT_NOW.md)."""

from __future__ import annotations

import math

from saudi_plot_design.elevation.facade_selection import facing_walls
from saudi_plot_design.elevation.front import (
    MIN_EDGE_CLEARANCE_M,
    MIN_OPENING_SPACING_M,
)
from saudi_plot_design.elevation.models import FacadeConcept, PrimaryFacadeSelection
from saudi_plot_design.model import Concept, PlotModel, ValidationCheck, ValidationReport
from saudi_plot_design.output import DISCLAIMER
from saudi_plot_design.styles.schema import StylePackData

_TOL = 1e-6
_NON_HOSTED_DECOR = ("decorative_band", "recessed_panel")


def validate_facade(
    facade: FacadeConcept,
    plot: PlotModel,
    concept: Concept,
    selection: PrimaryFacadeSelection,
    pack_data: StylePackData,
    *,
    deterministic: bool,
) -> ValidationReport:
    ctx = _Ctx(facade, plot, concept, selection, pack_data, deterministic)
    checks = tuple(
        _result(f"F{i:02d}", name, fn(ctx)) for i, (name, fn) in enumerate(_CHECKS, start=1)
    )
    return ValidationReport(checks=checks)


class _Ctx:
    def __init__(self, facade, plot, concept, selection, pack_data, deterministic):
        self.f = facade
        self.plot = plot
        self.concept = concept
        self.selection = selection
        self.pack = pack_data
        self.dims = pack_data.facade_rules.facade_dimensions
        self.deterministic = deterministic
        self.plan_walls = {w.id: w for w in concept.walls}
        self.plan_doors = {d.id: d for d in concept.doors}
        self.plan_windows = {w.id: w for w in concept.windows}
        self.openings = facade.facade_openings
        self.elements = facade.facade_elements
        self.wall = facade.facade_wall
        # Independent facade transform recomputed from the plan walls (never
        # the transform stored in the facade under validation): a coordinated
        # origin+opening shift must not self-certify.
        self.independent_origin, self.independent_x_dir, self.independent_normal = (
            _independent_transform(plot, concept, self.wall, self.plan_walls)
        )


def _result(check_id: str, name: str, problems: list[str]) -> ValidationCheck:
    return ValidationCheck(
        id=check_id,
        name=name,
        passed=not problems,
        details="; ".join(problems) if problems else "ok",
    )


def _c01_style_gate(ctx) -> list[str]:
    problems = []
    if ctx.f.style_selection_method not in ("user_confirmed", "manual_override"):
        problems.append(f"style selection method is '{ctx.f.style_selection_method}'")
    if not ctx.f.style_pack_id or not ctx.f.style_pack_version:
        problems.append("no confirmed style pack recorded")
    return problems


def _c02_facade_confirmed(ctx) -> list[str]:
    return [] if ctx.selection.user_confirmed else ["primary facade is not user-confirmed"]


def _c03_boundary_street(ctx) -> list[str]:
    idx = int(ctx.selection.selected_plot_boundary_id.rsplit("-", 1)[1]) - 1
    if not (0 <= idx < len(ctx.plot.edges)) or ctx.plot.edges[idx].value != "street":
        return [f"boundary '{ctx.selection.selected_plot_boundary_id}' is not a street"]
    return []


def _c04_walls_face_street(ctx) -> list[str]:
    idx = int(ctx.selection.selected_plot_boundary_id.rsplit("-", 1)[1]) - 1
    actually_facing = {w.id for w in facing_walls(ctx.plot, ctx.concept, idx)}
    selected = set(ctx.selection.selected_building_wall_ids)
    if not selected:
        return ["no building wall selected"]
    problems = [
        f"wall '{w}' does not face the selected street" for w in sorted(selected - actually_facing)
    ]
    # The selection must cover the WHOLE street facade: omitting a facing
    # segment would silently shorten the facade and drop its openings.
    problems += [
        f"street-facing wall '{w}' is missing from the selection"
        for w in sorted(actually_facing - selected)
    ]
    return problems


def _c05_length_matches(ctx) -> list[str]:
    problems = []
    total = sum(ctx.plan_walls[w].length_m for w in ctx.wall.source_plan_wall_ids)
    if abs(total - ctx.wall.length_m) > 0.01:
        problems.append(
            f"facade length {ctx.wall.length_m:g} m != source plan walls total {total:g} m"
        )
    # The stored transform metadata must equal the independently recomputed
    # one - corrupted origin/axis/normal values (including NaN, which defeats
    # plain > comparisons) must not pass even when the opening coordinates
    # themselves are consistent.
    if ctx.independent_origin is not None:
        for label, stored, expected, tol in (
            ("origin", ctx.wall.local_origin_world_xy, ctx.independent_origin, _POSITION_TOL_M),
            ("x-axis", ctx.wall.x_axis_world_dir, ctx.independent_x_dir, 1e-6),
            ("outward normal", ctx.wall.outward_normal_world_dir, ctx.independent_normal, 1e-6),
        ):
            if _vector_mismatch(stored, expected, tol):
                problems.append(
                    f"stored facade {label} {stored} differs from the recomputed value {expected}"
                )
    return problems


def _vector_mismatch(stored, expected, tol: float) -> bool:
    return any(
        not math.isfinite(s) or abs(s - e) > tol for s, e in zip(stored, expected, strict=True)
    )


def _independent_transform(plot, concept, facade_wall, plan_walls):
    """Recompute the facade origin/axis from the source plan walls, exactly
    as the generator defines them (outward normal rotated 90 deg CCW; origin
    at the minimal-X endpoint). Returns (None, None) when unavailable - the
    traceability checks then report the missing sources instead."""
    from saudi_plot_design.elevation.facade_selection import outward_normal

    if facade_wall is None:
        return None, None, None
    walls = [plan_walls[w] for w in facade_wall.source_plan_wall_ids if w in plan_walls]
    if not walls:
        return None, None, None
    normal = outward_normal(plot, concept, walls[0])
    x_dir = (-normal[1], normal[0])
    endpoints = [p for w in walls for p in (w.start, w.end)]
    projections = [p[0] * x_dir[0] + p[1] * x_dir[1] for p in endpoints]
    return endpoints[projections.index(min(projections))], x_dir, normal


def _expected_x_start(ctx, plan_wall_id: str, position_m: float, width_m: float) -> float | None:
    """Facade x of a plan opening via the INDEPENDENT transform (not the one
    stored in the facade under validation)."""
    if ctx.independent_origin is None:
        return None
    wall = ctx.plan_walls[plan_wall_id]
    length = wall.length_m
    ux = (wall.end[0] - wall.start[0]) / length
    uy = (wall.end[1] - wall.start[1]) / length
    ox, oy = ctx.independent_origin
    dx, dy = ctx.independent_x_dir
    xa = (wall.start[0] + ux * position_m - ox) * dx + (wall.start[1] + uy * position_m - oy) * dy
    xb = (wall.start[0] + ux * (position_m + width_m) - ox) * dx + (
        wall.start[1] + uy * (position_m + width_m) - oy
    ) * dy
    return min(xa, xb)


_POSITION_TOL_M = 1e-3


def _c06_doors_real(ctx) -> list[str]:
    problems = []
    facade_door_sources = set()
    for o in ctx.openings:
        if o.opening_type != "door":
            continue
        src = ctx.plan_doors.get(o.source_plan_opening_id)
        if src is None:
            problems.append(f"facade door '{o.id}' has no real plan door source")
        elif abs(src.width_m - o.width_m) > _TOL or src.wall_id != o.source_plan_wall_id:
            problems.append(f"facade door '{o.id}' does not match its plan source geometry")
        else:
            expected = _expected_x_start(ctx, src.wall_id, src.position_m, src.width_m)
            if expected is not None and abs(expected - o.x_start_m) > _POSITION_TOL_M:
                problems.append(
                    f"facade door '{o.id}' moved from its true plan position "
                    f"({o.x_start_m:g} vs expected {expected:g})"
                )
        facade_door_sources.add(o.source_plan_opening_id)
    for d in ctx.concept.doors:
        if d.wall_id in ctx.wall.source_plan_wall_ids and d.id not in facade_door_sources:
            problems.append(f"plan door '{d.id}' on the facade wall was removed")
    return problems


def _c07_windows_real(ctx) -> list[str]:
    problems = []
    facade_window_sources = set()
    for o in ctx.openings:
        if o.opening_type != "window":
            continue
        src = ctx.plan_windows.get(o.source_plan_opening_id)
        if src is None:
            problems.append(f"facade window '{o.id}' has no real plan window source")
        elif abs(src.width_m - o.width_m) > _TOL or src.wall_id != o.source_plan_wall_id:
            problems.append(f"facade window '{o.id}' does not match its plan source geometry")
        else:
            expected = _expected_x_start(ctx, src.wall_id, src.position_m, src.width_m)
            if expected is not None and abs(expected - o.x_start_m) > _POSITION_TOL_M:
                problems.append(
                    f"facade window '{o.id}' moved from its true plan position "
                    f"({o.x_start_m:g} vs expected {expected:g})"
                )
        facade_window_sources.add(o.source_plan_opening_id)
    for w in ctx.concept.windows:
        if w.wall_id in ctx.wall.source_plan_wall_ids and w.id not in facade_window_sources:
            problems.append(f"plan window '{w.id}' on the facade wall was removed")
    return problems


def _c08_openings_on_facade_wall(ctx) -> list[str]:
    problems = []
    for o in ctx.openings:
        if o.source_plan_wall_id not in ctx.wall.source_plan_wall_ids:
            problems.append(
                f"opening '{o.id}' sources wall '{o.source_plan_wall_id}' which is not "
                f"part of the selected facade"
            )
    return problems


def _c09_inside_extents(ctx) -> list[str]:
    return [
        f"opening '{o.id}' lies outside the facade extents"
        for o in ctx.openings
        if o.x_start_m < -_TOL or o.x_start_m + o.width_m > ctx.wall.length_m + _TOL
    ]


def _c10_positive_dims(ctx) -> list[str]:
    return [
        f"opening '{o.id}' has non-positive dimensions"
        for o in ctx.openings
        if o.width_m <= 0 or o.head_elevation_m - o.sill_elevation_m <= 0
    ]


def _c11_no_overlap(ctx) -> list[str]:
    problems = []
    spans = sorted(ctx.openings, key=lambda o: o.x_start_m)
    for a, b in zip(spans, spans[1:]):
        if b.x_start_m < a.x_start_m + a.width_m - _TOL:
            problems.append(f"openings '{a.id}' and '{b.id}' overlap")
    return problems


def _c12_edge_clearance(ctx) -> list[str]:
    problems = []
    for o in ctx.openings:
        if (
            o.x_start_m < MIN_EDGE_CLEARANCE_M - _TOL
            or o.x_start_m + o.width_m > ctx.wall.length_m - MIN_EDGE_CLEARANCE_M + _TOL
        ):
            problems.append(f"opening '{o.id}' violates the minimum edge clearance")
    return problems


def _c13_spacing(ctx) -> list[str]:
    problems = []
    spans = sorted(ctx.openings, key=lambda o: o.x_start_m)
    for a, b in zip(spans, spans[1:]):
        gap = b.x_start_m - (a.x_start_m + a.width_m)
        if gap < MIN_OPENING_SPACING_M - _TOL:
            problems.append(
                f"openings '{a.id}' and '{b.id}' are {gap:.2f} m apart "
                f"(minimum {MIN_OPENING_SPACING_M:g} m)"
            )
    return problems


def _c14_sill_head_valid(ctx) -> list[str]:
    problems = []
    for o in ctx.openings:
        if o.opening_type == "window":
            if (
                abs(o.sill_elevation_m - ctx.dims.window_sill_height_m) > _TOL
                or abs(o.head_elevation_m - ctx.dims.window_head_height_m) > _TOL
            ):
                problems.append(f"window '{o.id}' sill/head do not match the style pack")
        else:
            if (
                o.sill_elevation_m != 0.0
                or abs(o.head_elevation_m - ctx.dims.door_head_height_m) > _TOL
            ):
                problems.append(f"door '{o.id}' base/head do not match the style pack")
    return problems


def _c15_head_below_limits(ctx) -> list[str]:
    return [
        f"opening '{o.id}' head {o.head_elevation_m:g} m reaches the wall/parapet limit"
        for o in ctx.openings
        if o.head_elevation_m >= ctx.wall.wall_height_m - _TOL
    ]


def _c16_entrance_distinguishable(ctx) -> list[str]:
    problems = []
    mains = [o for o in ctx.openings if o.entrance_type == "main"]
    if len(mains) != 1:
        problems.append(f"expected exactly one main entrance on the facade, got {len(mains)}")
        return problems
    main = mains[0]
    if main.opening_type != "door" or main.sill_elevation_m != 0.0:
        problems.append("main entrance is not a ground-level door")
    frames = [
        e
        for e in ctx.elements
        if e.element_type == "entrance_frame" and e.host_opening_id == main.id
    ]
    if not frames:
        problems.append("main entrance has no entrance_frame treatment")
    return problems


def _c17_decor_in_zones(ctx) -> list[str]:
    problems = []
    band = ctx.dims.surround_band_width_m
    for e in ctx.elements:
        x0, z0, x1, z1 = _bbox(e.geometry)
        if (
            x0 < -band - _TOL
            or x1 > ctx.wall.length_m + band + _TOL
            or z0 < -_TOL
            or z1 > ctx.wall.total_height_m + _TOL
        ):
            problems.append(f"element '{e.id}' lies outside the permitted facade zone")
    return problems


def _c18_decor_not_covering_openings(ctx) -> list[str]:
    problems = []
    for e in ctx.elements:
        if e.element_type not in _NON_HOSTED_DECOR:
            continue
        ex0, ez0, ex1, ez1 = _bbox(e.geometry)
        for o in ctx.openings:
            ox0, ox1 = o.x_start_m, o.x_start_m + o.width_m
            oz0, oz1 = o.sill_elevation_m, o.head_elevation_m
            if ex0 < ox1 - _TOL and ox0 < ex1 - _TOL and ez0 < oz1 - _TOL and oz0 < ez1 - _TOL:
                problems.append(f"decorative element '{e.id}' covers opening '{o.id}'")
    return problems


def _c19_valid_element_geometry(ctx) -> list[str]:
    problems = []
    for e in ctx.elements:
        g = e.geometry
        if g["kind"] == "rect":
            if g["w"] <= 0 or g["h"] <= 0:
                problems.append(f"element '{e.id}' has zero-size geometry")
        elif g["kind"] == "polygon":
            if len(g["points"]) < 3 or abs(_polygon_area(g["points"])) <= _TOL:
                problems.append(f"element '{e.id}' has degenerate polygon geometry")
        else:
            problems.append(f"element '{e.id}' has unknown geometry kind '{g['kind']}'")
    return problems


def _c20_parapet_plinth_match_pack(ctx) -> list[str]:
    problems = []
    rng = ctx.pack.facade_rules.plinth_height_range_m
    if not (rng.min - _TOL <= ctx.wall.plinth_height_m <= rng.max + _TOL):
        problems.append("plinth height is outside the style-pack range")
    if abs(ctx.wall.parapet_height_m - ctx.dims.parapet_height_m) > _TOL:
        problems.append("parapet height does not match the style pack")
    for e in ctx.elements:
        if e.element_type == "parapet":
            _, z0, _, z1 = _bbox(e.geometry)
            if abs(z0 - ctx.wall.wall_height_m) > _TOL or abs(z1 - ctx.wall.total_height_m) > _TOL:
                problems.append(f"parapet element '{e.id}' violates pack dimensions")
    return problems


def _c21_materials_exist(ctx) -> list[str]:
    problems = []
    material_ids = {m.id for m in ctx.pack.materials.material_palette}
    colors = set(ctx.pack.materials.color_palette_hex)
    for e in ctx.elements:
        if e.material_id not in material_ids:
            problems.append(f"element '{e.id}' uses unknown material '{e.material_id}'")
        if e.color_hex not in colors:
            problems.append(f"element '{e.id}' uses unknown color '{e.color_hex}'")
    return problems


def _c22_no_fake_openings(ctx) -> list[str]:
    problems = []
    seen: set[str] = set()
    for o in ctx.openings:
        if o.source_plan_opening_id in seen:
            problems.append(f"plan opening '{o.source_plan_opening_id}' is duplicated")
        seen.add(o.source_plan_opening_id)
        if (
            o.source_plan_opening_id not in ctx.plan_doors
            and o.source_plan_opening_id not in ctx.plan_windows
        ):
            problems.append(f"facade opening '{o.id}' references no real plan opening")
    return problems


def _c23_disclaimer(ctx) -> list[str]:
    return [] if ctx.f.disclaimer == DISCLAIMER else ["the DEMO disclaimer is missing"]


def _c24_deterministic(ctx) -> list[str]:
    return [] if ctx.deterministic else ["regeneration produced different output"]


_CHECKS = (
    ("style confirmation gate passes", _c01_style_gate),
    ("primary facade is user-confirmed", _c02_facade_confirmed),
    ("selected boundary is classified STREET", _c03_boundary_street),
    ("selected building wall faces the street", _c04_walls_face_street),
    ("facade length matches source plan walls", _c05_length_matches),
    ("every facade door maps to a real plan door", _c06_doors_real),
    ("every facade window maps to a real plan window", _c07_windows_real),
    ("openings belong to the selected exterior wall", _c08_openings_on_facade_wall),
    ("openings lie inside facade extents", _c09_inside_extents),
    ("openings have positive dimensions", _c10_positive_dims),
    ("openings do not overlap", _c11_no_overlap),
    ("openings meet minimum edge clearance", _c12_edge_clearance),
    ("openings meet minimum spacing", _c13_spacing),
    ("sill and head elevations are valid", _c14_sill_head_valid),
    ("head elevations stay below wall/parapet limits", _c15_head_below_limits),
    ("entrance remains visibly distinguishable", _c16_entrance_distinguishable),
    ("decorative elements lie inside permitted zones", _c17_decor_in_zones),
    ("decorative elements do not cover openings", _c18_decor_not_covering_openings),
    ("frames and shading have valid non-zero geometry", _c19_valid_element_geometry),
    ("parapet and plinth match the style pack", _c20_parapet_plinth_match_pack),
    ("materials and colors exist in the style pack", _c21_materials_exist),
    ("no unreferenced fake opening exists", _c22_no_fake_openings),
    ("the DEMO disclaimer is present", _c23_disclaimer),
    ("output is deterministic", _c24_deterministic),
)


def _bbox(geometry: dict) -> tuple[float, float, float, float]:
    if geometry["kind"] == "rect":
        return (
            geometry["x"],
            geometry["z"],
            geometry["x"] + geometry["w"],
            geometry["z"] + geometry["h"],
        )
    xs = [p[0] for p in geometry["points"]]
    zs = [p[1] for p in geometry["points"]]
    return (min(xs), min(zs), max(xs), max(zs))


def _polygon_area(points) -> float:
    area = 0.0
    for i, (x1, z1) in enumerate(points):
        x2, z2 = points[(i + 1) % len(points)]
        area += x1 * z2 - x2 * z1
    return area / 2.0
