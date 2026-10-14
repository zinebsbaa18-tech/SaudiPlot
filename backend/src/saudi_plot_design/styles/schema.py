"""Pydantic schemas for the 4-file style pack (STYLE_PACK_SCHEMA.md).

The pack carries DEMO design data for future facade use (M4). Nothing here
renders geometry. All schemas use extra="forbid" so drift surfaces
immediately.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_SEMVER = r"^\d+\.\d+\.\d+$"
_SLUG = r"^[a-z0-9_]+$"


class StyleCore(BaseModel):
    """style.json"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    style_pack_id: str = Field(pattern=_SLUG)
    name_ar: str
    name_en: str
    version: str = Field(pattern=_SEMVER)
    status: Literal["demo_requires_architect_review"]
    applicable_zone_ids: tuple[str, ...] = Field(min_length=1)
    allowed_building_type: Literal["detached_single_storey_villa"]
    massing_category: str
    prohibited_elements: tuple[str, ...]
    human_review_notes: tuple[str, ...]


class ProportionRange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # allow_inf_nan=False: JSON 1e400 decodes to +inf and would pass gt=0,
    # reaching M4 geometry as non-finite coordinates.
    min: float = Field(gt=0, allow_inf_nan=False)
    max: float = Field(gt=0, allow_inf_nan=False)


class FacadeDimensions(BaseModel):
    """Dimensional data the M4 elevation stage derives geometry from (FR-6):
    the style pack - not code - governs facade height and opening geometry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    wall_height_m: float = Field(ge=2.7, le=5.0, allow_inf_nan=False)
    parapet_height_m: float = Field(gt=0, le=1.5, allow_inf_nan=False)
    parapet_unit_width_m: float = Field(gt=0, allow_inf_nan=False)
    parapet_gap_m: float = Field(gt=0, allow_inf_nan=False)
    window_sill_height_m: float = Field(gt=0, allow_inf_nan=False)
    window_head_height_m: float = Field(gt=0, allow_inf_nan=False)
    window_max_width_m: float = Field(gt=0, allow_inf_nan=False)
    door_head_height_m: float = Field(gt=0, allow_inf_nan=False)
    surround_band_width_m: float = Field(gt=0, le=0.5, allow_inf_nan=False)
    ornament_band_elevation_m: float = Field(gt=0, allow_inf_nan=False)
    ornament_band_height_m: float = Field(gt=0, le=1.0, allow_inf_nan=False)


class FacadeRules(BaseModel):
    """facade_rules.json - DEMO rule identifiers + dimensions for M4."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: Literal["demo"]
    entrance_composition_options: tuple[str, ...] = Field(min_length=1)
    window_proportion_range_w_to_h: ProportionRange
    window_group_ids: tuple[str, ...]
    shading_element_ids: tuple[str, ...]
    parapet_family_ids: tuple[str, ...] = Field(min_length=1)
    plinth_height_range_m: ProportionRange
    wall_treatment_ids: tuple[str, ...]
    fence_gate_family_id: str
    facade_dimensions: FacadeDimensions


class MaterialEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=_SLUG)
    name_ar: str
    name_en: str
    finish_note: str


class Materials(BaseModel):
    """materials.json"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: Literal["demo"]
    material_palette: tuple[MaterialEntry, ...] = Field(min_length=1)
    color_palette_hex: tuple[str, ...] = Field(min_length=1)


class SourceMetadata(BaseModel):
    """source_metadata.json"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance_level: Literal["demo"]
    statement: str
    sources: tuple[str, ...]
    created: str
    reviewer: str | None
    review_date: str | None
    limitations: tuple[str, ...] = Field(min_length=1)


class StylePackData(BaseModel):
    """The full validated pack content."""

    model_config = ConfigDict(frozen=True)

    core: StyleCore
    facade_rules: FacadeRules
    materials: Materials
    source_metadata: SourceMetadata

    @property
    def fingerprint(self) -> str:
        """Content hash over the COMPLETE consumed pack - id+version alone
        cannot bind provenance (same-version drift)."""
        from saudi_plot_design.model import content_fingerprint

        return content_fingerprint(self.model_dump_json())
