"""Typed, immutable models for the M6.3 architectural sheet engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from saudi_plot_design.output import DISCLAIMER

SHEET_ENGINE_VERSION = "1.0.0"
SHEET_SCHEMA_VERSION = 1
GRAPHIC_PROFILE_ID = "architectural_concept_a3_v1"
SheetSetMode = Literal["none", "concept", "review", "all"]


@dataclass(frozen=True)
class GraphicProfile:
    """Versioned A3 graphic standard expressed in millimetres and points."""

    profile_id: str = GRAPHIC_PROFILE_ID
    paper_size: str = "A3"
    orientation: str = "landscape"
    paper_width_mm: float = 420.0
    paper_height_mm: float = 297.0
    margin_mm: float = 10.0
    title_block_top_mm: float = 257.0
    title_block_bottom_mm: float = 287.0
    font_regular: str = "Helvetica"
    font_bold: str = "Helvetica-Bold"
    title_pt: float = 18.0
    heading_pt: float = 9.0
    body_pt: float = 6.5
    note_pt: float = 5.5
    schedule_pt: float = 5.0
    line_plot_mm: float = 0.50
    line_cut_mm: float = 0.60
    line_medium_mm: float = 0.32
    line_light_mm: float = 0.18
    line_hair_mm: float = 0.10
    dash_mm: tuple[float, ...] = (2.2, 1.2)
    annotation_spacing_mm: float = 1.5
    arrow_mm: float = 1.6
    unit: str = "m"
    disclaimer: str = DISCLAIMER

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.paper_size != "A3" or self.orientation != "landscape":
            errors.append("M6.3 supports only ISO A3 landscape")
        if (self.paper_width_mm, self.paper_height_mm) != (420.0, 297.0):
            errors.append("A3 landscape must be 420 x 297 mm")
        if not 0 < self.margin_mm < 25:
            errors.append("printable margin must be between 0 and 25 mm")
        if not (
            self.margin_mm
            < self.title_block_top_mm
            < self.title_block_bottom_mm
            <= self.paper_height_mm - self.margin_mm
        ):
            errors.append("title block must be inside the printable area")
        if not (
            self.line_cut_mm
            >= self.line_plot_mm
            > self.line_medium_mm
            > self.line_light_mm
            > self.line_hair_mm
            > 0
        ):
            errors.append("line-weight hierarchy is invalid")
        if not self.font_regular or not self.font_bold:
            errors.append("system font names are required")
        return tuple(errors)


GRAPHIC_PROFILE = GraphicProfile()


@dataclass(frozen=True)
class Primitive:
    """One format-neutral vector primitive in page millimetres (Y down)."""

    kind: str
    points: tuple[tuple[float, float], ...] = ()
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    radius: float = 0.0
    text: str = ""
    font_size_pt: float = 6.5
    stroke: str = "#111111"
    fill: str = "none"
    stroke_width_mm: float = 0.18
    dash_mm: tuple[float, ...] = ()
    opacity: float = 1.0
    anchor: str = "start"
    bold: bool = False
    rotation_deg: float = 0.0
    role: str = "graphic"
    source_id: str = ""


@dataclass(frozen=True)
class SheetPage:
    number: str
    title: str
    scale: str
    revision: str
    issue_status: str
    issue_date: str
    candidate_id: str
    geometry_fingerprint: str
    primitives: tuple[Primitive, ...]
    review_variant: bool = False


@dataclass(frozen=True)
class CollisionRecord:
    annotation_id: str
    room_id: str | None
    disposition: str
    details: str
    unresolved: bool = False


@dataclass(frozen=True)
class FurnitureRecord:
    symbol_id: str
    room_id: str
    symbol_type: str
    disposition: str
    reason: str = ""


@dataclass(frozen=True)
class SheetIndexEntry:
    sheet_number: str
    title: str
    revision: str
    issue_status: str
    paper_size: str
    orientation: str
    scale: str
    source_candidate_id: str
    source_geometry_fingerprint: str
    output_filename: str
    included_in: tuple[str, ...]


@dataclass(frozen=True)
class SheetValidation:
    passed: bool
    checks: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class ArchitecturalSheetBuild:
    profile: GraphicProfile
    concept_pages: tuple[SheetPage, ...]
    review_pages: tuple[SheetPage, ...]
    individual_pages: tuple[tuple[str, SheetPage], ...]
    index_entries: tuple[SheetIndexEntry, ...]
    collisions: tuple[CollisionRecord, ...] = ()
    furniture: tuple[FurnitureRecord, ...] = ()
    validation: SheetValidation = field(default_factory=lambda: SheetValidation(False, ()))


@dataclass(frozen=True)
class ArchitecturalSheetExport:
    mode: SheetSetMode
    profile_id: str
    output_paths: tuple[str, ...]
    concept_pdf_path: str | None
    review_pdf_path: str | None
    sheet_index_path: str
    sheet_manifest_path: str
    collision_report_path: str
    svg_paths: tuple[str, ...]
    sheet_numbers: tuple[str, ...]
    validation_status: str
    collision_count: int
    unresolved_collision_count: int
