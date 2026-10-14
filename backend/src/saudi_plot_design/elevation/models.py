"""Typed facade models (M4).

Coordinate system (documented, deterministic):
- Facade X: distance in meters along the selected exterior facade line,
  increasing left-to-right AS SEEN FROM THE STREET. The X unit vector is the
  facade's outward normal rotated 90 degrees counterclockwise, so mirrored or
  rotated plans never unpredictably reverse the drawing.
- Facade Z: vertical meters above finished ground level (Z=0).
- Origin: the facade-line endpoint with the minimal X projection, at ground.

The facade of the Compact 3BR spans several collinear external plan wall
segments (one per fronting room), so FacadeWall records source_plan_wall_ids
(plural) while every opening references its own actual source segment.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from saudi_plot_design.model import Corner, ValidationReport

GENERATION_VERSION = 1


class PrimaryFacadeSelection(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str  # plot_id (descriptive, NOT unique)
    concept_id: str
    # Content fingerprints binding this confirmation to the exact plot and
    # concept it was made for (ids alone are not unique).
    plot_fingerprint: str
    concept_fingerprint: str
    selected_plot_boundary_id: str  # "plot-edge-<n>" (1-based)
    selected_building_wall_ids: tuple[str, ...]  # collinear facing segments
    selection_method: str  # "geometric_facing_match"
    user_confirmed: bool
    confirmation_timestamp: str | None = None
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class FacadeWall(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_plan_wall_ids: tuple[str, ...]
    length_m: float
    base_elevation_m: float  # finished ground = 0.0
    wall_height_m: float
    parapet_height_m: float
    total_height_m: float
    plinth_height_m: float
    local_origin_world_xy: Corner  # world point at facade (X=0, Z=0)
    x_axis_world_dir: Corner  # unit vector: facade X in plan coordinates
    outward_normal_world_dir: Corner  # unit vector toward the street


class FacadeOpening(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    source_plan_opening_id: str
    source_plan_wall_id: str
    source_room_id: str | None  # room for windows; entrance target for doors
    opening_type: str  # "door" | "window"
    entrance_type: str | None = None  # "main" | "majlis" | None
    x_start_m: float
    width_m: float
    sill_elevation_m: float  # 0.0 for doors
    head_elevation_m: float
    style_treatment_id: str


class FacadeElement(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    element_type: str  # wall_body | plinth | parapet | entrance_frame |
    # window_frame | shading_canopy | decorative_band
    geometry: dict  # {"kind": "rect", x, z, w, h} or {"kind": "polygon", points}
    source_rule_id: str  # style-pack rule/family identifier
    host_opening_id: str | None = None
    material_id: str
    color_hex: str
    assumptions: tuple[str, ...] = ()


class FacadeConcept(BaseModel):
    """A generated facade, or an honest structured rejection.

    A rejected facade has non-empty ``rejection_reasons`` and empty geometry
    collections (pre-generation blocks) or a failing validation report.
    """

    model_config = ConfigDict(frozen=True)

    facade_concept_id: str
    project_id: str
    plan_concept_id: str
    # Content fingerprints of the exact plot/concept/style-pack this facade
    # was built from (M5 export binding; ids alone are not unique).
    plot_fingerprint: str = ""
    concept_fingerprint: str = ""
    style_pack_fingerprint: str = ""
    primary_facade_selection: PrimaryFacadeSelection | None
    character_match_zone_id: str | None
    style_selection_method: str | None
    style_pack_id: str | None
    style_pack_version: str | None
    facade_wall: FacadeWall | None = None
    facade_openings: tuple[FacadeOpening, ...] = ()
    facade_elements: tuple[FacadeElement, ...] = ()
    dimensions: dict = {}
    validation: ValidationReport | None = None
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    rejection_reasons: tuple[str, ...] = ()
    generation_version: int = GENERATION_VERSION
    disclaimer: str = ""

    @property
    def is_valid(self) -> bool:
        return not self.rejection_reasons and self.validation is not None and self.validation.passed
