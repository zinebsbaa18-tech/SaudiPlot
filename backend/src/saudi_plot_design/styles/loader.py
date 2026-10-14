"""Strict single-pack style loader (M3).

Loads exactly ONE pilot pack from the configured styles root. The loader
never scans for or combines multiple packs: a second pack directory is a
startup error, matching the one-pilot-style lock (LOCKED_MVP_SCOPE.md
capability 8). Files claiming verified/official status are rejected.
"""

from __future__ import annotations

import json
import re
from importlib.resources import as_file, files
from pathlib import Path

from pydantic import ValidationError

from saudi_plot_design.character.models import StylePackReference
from saudi_plot_design.model import SpdInputError
from saudi_plot_design.styles.schema import (
    FacadeRules,
    Materials,
    SourceMetadata,
    StyleCore,
    StylePackData,
)

REQUIRED_FILES = ("style.json", "facade_rules.json", "materials.json", "source_metadata.json")

# The sole pack supported by the MVP (LOCKED_MVP_SCOPE.md capability 8). Any
# other pack id/directory - even a well-formed demo pack - is rejected.
PILOT_STYLE_PACK_ID = "najdi_demo_v1"

_FORBIDDEN_STATUS_TOKENS = ("verified", "official")
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_RATIO_TOL = 1e-9  # float-rounding tolerance for proportion-bound checks


def default_styles_root() -> Path:
    resource = files("saudi_plot_design").joinpath("data/demo/styles")
    with as_file(resource) as path:
        return Path(path)


def load_pilot_style_pack(
    styles_root: str | Path | None = None,
    *,
    known_zone_ids: tuple[str, ...] | None = None,
) -> tuple[StylePackReference, StylePackData]:
    """Load the single pilot pack; reject anything but exactly one pack."""
    root = Path(styles_root) if styles_root is not None else default_styles_root()
    if not root.is_dir():
        raise SpdInputError(f"styles directory not found: {root}")
    pack_dirs = sorted(p for p in root.iterdir() if p.is_dir())
    if len(pack_dirs) != 1:
        raise SpdInputError(
            f"exactly one pilot style pack must be installed, found {len(pack_dirs)} "
            f"pack directories in {root} (the MVP supports a single active pack)"
        )
    if pack_dirs[0].name != PILOT_STYLE_PACK_ID:
        raise SpdInputError(
            f"the MVP supports only the locked pilot pack '{PILOT_STYLE_PACK_ID}', "
            f"found '{pack_dirs[0].name}'"
        )
    return _load_pack_dir(pack_dirs[0], known_zone_ids)


def _load_pack_dir(
    pack_dir: Path, known_zone_ids: tuple[str, ...] | None
) -> tuple[StylePackReference, StylePackData]:
    for name in REQUIRED_FILES:
        if not (pack_dir / name).is_file():
            raise SpdInputError(f"style pack '{pack_dir.name}' is missing required file '{name}'")

    core = _parse(pack_dir / "style.json", StyleCore, "style.json")
    facade_rules = _parse(pack_dir / "facade_rules.json", FacadeRules, "facade_rules.json")
    materials = _parse(pack_dir / "materials.json", Materials, "materials.json")
    source_metadata = _parse(
        pack_dir / "source_metadata.json", SourceMetadata, "source_metadata.json"
    )

    if core.style_pack_id != pack_dir.name:
        raise SpdInputError(
            f"style pack id '{core.style_pack_id}' must match its directory name '{pack_dir.name}'"
        )
    if "demo" not in core.style_pack_id:
        raise SpdInputError(
            f"demo style pack id '{core.style_pack_id}' must contain 'demo' "
            f"(GEOSPATIAL_DATA_PROVENANCE.md id convention)"
        )
    # Status/provenance fields are Literal-validated to demo values by the
    # schemas; this token check is a second line of defense. Free-text fields
    # (statements, limitations) are NOT scanned - they legitimately deny
    # official status ("NOT official ...").
    _reject_official_claims(f"style pack '{core.style_pack_id}'", core.status)
    if known_zone_ids is not None:
        unknown = [z for z in core.applicable_zone_ids if z not in known_zone_ids]
        if unknown:
            raise SpdInputError(
                f"style pack '{core.style_pack_id}' references unknown zone ids: "
                f"{', '.join(unknown)}"
            )
    rng = facade_rules.window_proportion_range_w_to_h
    if rng.min > rng.max:
        raise SpdInputError(f"style pack '{core.style_pack_id}': window proportion range min > max")
    plinth = facade_rules.plinth_height_range_m
    if plinth.min > plinth.max:
        raise SpdInputError(f"style pack '{core.style_pack_id}': plinth range min > max")
    dims = facade_rules.facade_dimensions
    if not (dims.window_sill_height_m < dims.window_head_height_m <= dims.wall_height_m):
        raise SpdInputError(
            f"style pack '{core.style_pack_id}': window sill/head heights must satisfy "
            f"0 < sill < head <= wall height"
        )
    window_height = dims.window_head_height_m - dims.window_sill_height_m
    max_ratio = dims.window_max_width_m / window_height
    # Tolerance-aware bounds: decimal values that mathematically land exactly
    # on a bound (e.g. 0.68 / 1.7 = 0.4) can round a hair past it in binary
    # floats and must not reject a valid pack.
    if max_ratio > rng.max + _RATIO_TOL:
        raise SpdInputError(
            f"style pack '{core.style_pack_id}': internally inconsistent - the widest "
            f"allowed window ({dims.window_max_width_m:g} m over {window_height:g} m "
            f"height) has w/h ratio {max_ratio:.3f}, above the pack's declared "
            f"maximum {rng.max:g}"
        )
    if max_ratio < rng.min - _RATIO_TOL:
        raise SpdInputError(
            f"style pack '{core.style_pack_id}': internally inconsistent - even the "
            f"widest allowed window ({dims.window_max_width_m:g} m over "
            f"{window_height:g} m height) has w/h ratio {max_ratio:.3f}, below the "
            f"pack's declared minimum {rng.min:g}; no window can satisfy the range"
        )
    if dims.door_head_height_m > dims.wall_height_m:
        raise SpdInputError(
            f"style pack '{core.style_pack_id}': door head height exceeds wall height"
        )
    if dims.ornament_band_elevation_m >= dims.wall_height_m:
        raise SpdInputError(
            f"style pack '{core.style_pack_id}': ornament band elevation must be below "
            f"the wall height"
        )
    for color in materials.color_palette_hex:
        if not _HEX_COLOR.fullmatch(color):
            raise SpdInputError(f"style pack '{core.style_pack_id}': invalid hex color '{color}'")

    reference = StylePackReference(
        style_pack_id=core.style_pack_id,
        name_ar=core.name_ar,
        name_en=core.name_en,
        version=core.version,
        status=core.status,
        applicable_zone_ids=core.applicable_zone_ids,
        source_metadata=source_metadata.model_dump(mode="json"),
        reviewer=source_metadata.reviewer,
        review_date=source_metadata.review_date,
        limitations=source_metadata.limitations,
    )
    data = StylePackData(
        core=core,
        facade_rules=facade_rules,
        materials=materials,
        source_metadata=source_metadata,
    )
    return reference, data


def _parse(path: Path, model, what: str):
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpdInputError(f"style pack file {what} is not valid JSON: {exc}") from None
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(loc) for loc in first["loc"]) or "<root>"
        raise SpdInputError(
            f"style pack file {what} rejected at '{field}': {first['msg']} "
            f"(the MVP loads only demo packs with status demo_requires_architect_review)"
        ) from None


def _reject_official_claims(context: str, *values: str) -> None:
    for value in values:
        # Denials ("NOT OFFICIAL", "unofficial") are the point of demo
        # labeling - strip them before scanning so only positive claims trip.
        lowered = value.lower()
        for negation in ("not official", "not verified", "unofficial", "non-official"):
            lowered = lowered.replace(negation, "")
        for token in _FORBIDDEN_STATUS_TOKENS:
            if token in lowered:
                raise SpdInputError(
                    f"{context} claims '{token}' status - the MVP loads only demo packs; "
                    f"verified-data activation is NOT NOW"
                )
