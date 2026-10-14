# STYLE_PACK_SCHEMA.md

Schema for facade style packs, as implemented in M3. Scope authority: LOCKED_MVP_SCOPE.md §8 — exactly one pack (`najdi_demo_v1`) ships in the MVP. The schema separates style data from rendering code so future verified packs can reuse the same shape; activating any verified or additional pack is a user-approved scope change that will also relax the demo-only validator and single-pack loader policy (code changes expected). It is **not** an invitation to author more packs now.

## 1. What a style pack is

A **directory** of four JSON files carrying DEMO design data that the M4 elevation stage will consume. Nothing in M3 renders geometry, and a pack never adds, removes, or splits plan openings (openings come from the floor plan — D5 in ARCHITECTURE.md).

```
src/saudi_plot_design/data/demo/styles/najdi_demo_v1/
  style.json             # identity, version, status, applicability
  facade_rules.json      # rule identifiers + ranges for M4 (not rendered yet)
  materials.json         # material + color palettes
  source_metadata.json   # provenance, reviewer, limitations
```

Schemas: `src/saudi_plot_design/styles/schema.py` (pydantic, `extra="forbid"`). Loader: `styles/loader.py`.

**MVP loading rule:** `load_pilot_style_pack` loads exactly one pack directory from the configured styles root, and that directory must be the locked pilot id `najdi_demo_v1` — a single well-formed pack with any other id is rejected. Zero packs or a second pack directory is a startup error; the loader never scans for or combines multiple packs.

## 2. File contracts (v1)

### style.json
`schema_version` (=1), `style_pack_id` (slug; must match the directory name and contain `demo`), `name_ar` (الطابع النجدي التجريبي), `name_en`, `version` (semver, `0.1.0`), `status` (must be `demo_requires_architect_review`), `applicable_zone_ids` (≥1; validated against the zone dataset when provided), `allowed_building_type` (must be `detached_single_storey_villa`), `massing_category`, `prohibited_elements`, `human_review_notes`.

### facade_rules.json
`provenance` (=`demo`), `entrance_composition_options` (≥1), `window_proportion_range_w_to_h` (min/max, min ≤ max, finite), `window_group_ids`, `shading_element_ids`, `parapet_family_ids` (≥1), `plinth_height_range_m` (min ≤ max, finite), `wall_treatment_ids`, `fence_gate_family_id`, and `facade_dimensions` — the dimensional block FR-6 requires so the pack (not code) governs facade geometry: `wall_height_m` (2.7–5.0), parapet height/unit width/gap, window sill/head heights (0 < sill < head ≤ wall height), `window_max_width_m`, `door_head_height_m` (≤ wall height), surround band width, ornament band elevation (< wall height) and height. All numerics reject inf/NaN; all identifiers are `demo_`-prefixed placeholders for M4.

### materials.json
`provenance` (=`demo`), `material_palette` (≥1 entries: id, name_ar, name_en, finish_note), `color_palette_hex` (≥1, `#rrggbb` validated).

### source_metadata.json
`provenance_level` (=`demo`), `statement` (must plainly deny official derivation), `sources`, `created`, `reviewer` (null until a licensed architect reviews), `review_date`, `limitations` (≥1).

## 3. Loader rejections

Missing required file; invalid JSON; schema violation (unknown fields, bad enum, bad semver); id ≠ directory name; id without `demo`; any positive `verified`/`official` claim in status/provenance fields (Literal-validated to demo values, plus a token guard as second defense — free-text denials like "NOT official" are fine); unknown `applicable_zone_ids`; inverted ranges; invalid hex colors; more or fewer than exactly one pack directory.

The loader produces a typed `StylePackReference` (identity + provenance summary for artifacts) and `StylePackData` (full validated content).

## 4. How M4 consumes a pack (implemented)

`elevation/front.py` maps street-wall plan openings to facade geometry using the rule identifiers and `facade_dimensions` above — the pack is the single source of facade dimensional truth (no duplicated constants). The bounded Najdi template renders: wall body, plinth (midpoint of the pack range), triangular crenellation parapet, entrance/window frames and shading canopies sized by the surround band width, and the ornament band. A plan window incompatible with the pack's width/proportion rules is a structured unsupported-state rejection: the elevation never invents, moves, resizes, or splits openings, and the plan is never silently altered. Materials/colors used by elements must exist in the pack (validated). PDF fills and DXF layers reuse the same geometry in M5 (D1).

## 5. Out of scope for v1 (recorded, not implemented)

Second packs, style blending/editors, textures/images, 3D parameters, per-room facade logic, automatic pack discovery, verified-pack activation (needs the future trusted approval mechanism). See NOT_NOW.md.

## 6. Tests (implemented, M3)

Shipped pack loads with expected identity/status/zones; all rule identifiers and material ids are `demo_`-labeled; rejections covered for: second pack, zero packs, missing file, unknown schema field, official status claim, verified provenance claim, unknown zone reference, id/directory mismatch, non-demo id, bad semver, inverted ranges, invalid hex color.
