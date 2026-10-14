# SAUDI_CHARACTER_ENGINE.md

Design of the architectural-character recommendation engine, as implemented in M3. Scope authority: LOCKED_MVP_SCOPE.md §7 (FR-4 in PRD.md). Code: `src/saudi_plot_design/character/` (`models.py`, `engine.py`, `selection.py`).

## 1. Principle

The plot's **location** determines the **recommended** Saudi architectural character via deterministic point-in-polygon lookup against zone polygons. The user then **confirms or overrides**. The engine is a lookup, not an oracle:

- ✅ local point-in-polygon against zone data + mandatory user confirmation
- ❌ no LLM inference, no imagery/nearby-building analysis, no reverse geocoding, no APIs
- ❌ no scoring heuristics beyond the transparent rule-based confidence in §5

Three concepts are deliberately separate: **administrative location** (the lat/lon point), **architectural character zone** (a polygon in the dataset), and **selected style** (a style pack chosen through the confirmation gate). One never implies another without an explicit rule.

Location note: plot corners are local meters, so a geographic centroid cannot be derived from them. The user-provided lat/lon (`PlotModel.location`) stands in for the plot centroid and is recorded in `LocationPoint.source`.

## 2. Background (context only, not shipped as data)

The Saudi Architecture program (launched 2025 under the Ministry of Municipalities and Housing umbrella) defines regional architectural characters with design guidelines. We do **not** have the official zone polygons or guideline documents in verified machine-readable form. Until provided, all zone geometry and style rules in this repo are demo placeholders per GEOSPATIAL_DATA_PROVENANCE.md.

## 3. Dataset contract

Directory: `src/saudi_plot_design/data/demo/architectural_character_zones/` (packaged):

- `metadata.json` — dataset_id, version, created, publisher, license_note, coverage, crs (EPSG:4326), status, provenance_level (`demo`), limitations. Status is `DEMO SYNTHETIC - NOT OFFICIAL - REQUIRES VERIFICATION`.
- `zones.geojson` — `FeatureCollection` with an `x_provenance` block (`level: demo`), features carrying: `zone_id`, `name_ar`, `name_en`, `style_pack_id` (nullable — a zone may have no installed pack), integer `priority` (lower value = higher precedence), `provenance: demo`, `known_limitations`.

Shipped demo content: three coarse synthetic rectangles (Riyadh/najdi with `najdi_demo_v1`, Jeddah/hejazi and Abha/asiri without packs) so the no-pack and no-match paths are honestly exercisable.

Loader rejections (each a specific `SpdInputError`; untrusted data is never silently repaired):

1. Missing/invalid JSON, missing `metadata.json`, missing `x_provenance`, missing per-feature `provenance`.
2. Any provenance level other than `demo`; any status/provenance field positively claiming `verified`/`official` (denials such as "NOT OFFICIAL" are the point of demo labeling and do not trip the guard).
3. Non-Polygon or invalid (e.g. self-intersecting) geometry — no `buffer(0)` repairs.
4. Duplicate `zone_id`; missing integer `priority`; CRS other than EPSG:4326/CRS84.

Overlaps are **allowed at load** and handled at lookup (§4). Equal priorities are allowed at load; they only matter when overlapping zones both cover a point.

## 4. Lookup algorithm (`recommend_character`)

```
point = Point(lon, lat)                     # GeoJSON axis order
candidates = zones whose polygon covers(point)
no candidates      -> NO_MATCH, unresolved, manual selection required
one candidate      -> selected; boundary checks below
many candidates    -> overlap_detected + warning:
    unique minimum priority  -> that zone selected + "resolved by priority" warning
    tied minimum priority    -> selected None, all candidates returned,
                                demo_low, user selection required
boundary distance (approx meters, deg x ~111 km):
    == 0                     -> boundary match, demo_low, warning
    <= tolerance (250 m cfg) -> near_boundary, demo_reduced, warning
```

`covers` (not `contains`) so boundary points match deterministically. Every path yields a `CharacterMatch` recording: point, matched/selected zone ids, match method, confidence, boundary distance, overlap/near-boundary flags, dataset id + version + status, warnings, and the fixed statement *"Demo geographic classification — requires verification."*

## 5. Confidence (transparent, rule-based)

Fixed labels with bounded values — never an AI score, never an implication of official correctness:

| Situation | Level | Value |
|---|---|---|
| Strictly inside one zone, clear of boundary | `demo_normal` | 0.8 |
| Near boundary (≤ 250 m approx) or overlap resolved by priority | `demo_reduced` | 0.6 |
| Exactly on boundary, or overlap unresolved (tied priority) | `demo_low` | 0.4 |
| No match | `unresolved` | none |

Manual override does not change these: confidence describes the lookup result; the selection method becomes `manual_override` separately.

## 6. Style selection and the confirmation gate (`selection.py`)

`recommend_style` derives an initial selection from the match (`automatic_recommendation`, or `unresolved` when there is no zone/pack). `confirm_selection` records explicit user confirmation of the recommendation; `override_selection` records a manual override and **requires a non-empty reason**.

`confirmation_gate(match, selection, pack)` is the hard code-level gate the facade pipeline (M4+) must pass. It passes only when ALL hold:

1. character lookup completed;
2. a style pack is selected and matches the loaded pack;
3. `selection_method` ∈ {`user_confirmed`, `manual_override`};
4. `user_confirmed` is true;
5. the pack is declared applicable to the selected zone, or an override reason is recorded.

Reference states: **A** recommended-but-unconfirmed → blocked; **B** user confirmed → passes; **C** override without reason → error, with reason + confirmation → passes; **D** no match → unresolved until the user manually selects and confirms the pilot pack (with reason).

## 7. Upgrade path to verified data (documented, not built)

The MVP loader rejects any dataset claiming `verified`/`official` — self-declared metadata can never suppress the disclaimer (GEOSPATIAL_DATA_PROVENANCE.md §1 rule 2). Activating official zone polygons is a future, user-approved scope change requiring a trusted approval mechanism; official overlap semantics will be decided then. The disclaimer remains unconditional until that scope change lands.

## 8. Tests (implemented, M3)

Engine: pilot point → Demo Najdi (`demo_normal`); outside all zones → unresolved; exactly on boundary → `demo_low`; near boundary → `demo_reduced` + warning; overlap with unique priorities → priority resolution + warning; overlap with tied priorities → user selection required; invalid GeoJSON / self-intersecting polygon / missing metadata / missing provenance (file + feature) / official claim / verified claim / duplicate zone_id / non-Polygon / wrong CRS / missing priority → each rejected; deterministic match JSON.

Gate: state A blocked; state B passes; override without reason fails; override with reason passes (including the zone-incompatible pack case); no-match stays unresolved until manual confirmed selection; artifacts carry the unconditional disclaimer and link to `plot_id`.

End-to-end CLI behavior (exit codes, `run.json`) remains M5.
