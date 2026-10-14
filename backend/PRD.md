# PRD.md — Saudi Plot Design Studio (MVP)

Working name: **Saudi Plot Design Studio** (`saudi_plot_design`, CLI: `spd`).
Scope authority: LOCKED_MVP_SCOPE.md. Exclusions: NOT_NOW.md. This PRD describes only the locked MVP.

## 1. Problem

Saudi homeowners and small design offices who own a residential plot have no quick way to see a regulation-shaped, culturally appropriate concept for their land. Existing tools are generic CAD (too slow, no Saudi character) or foreign plan catalogs (ignore setbacks, orientation, and Saudi architectural identity as promoted by the Saudi Architecture program).

## 2. Target users (MVP)

- U1: A plot owner with plot corner dimensions from a deed/kroki, technically able to run a CLI or be assisted by one.
- U2: A junior designer at a small Saudi design office preparing a first concept sheet for a client meeting.

## 3. Goals / success criteria

- G1: From plot input to PDF + DXF in under 60 seconds on a normal laptop, fully offline.
- G2: The front elevation is derived from the actual plan openings (verifiable: moving a window in the plan data moves it in the elevation).
- G3: Every output visibly discloses that geographic/style data is DEMO until verified data is provided.
- G4: The recommended character always comes from point-in-polygon lookup + explicit user confirmation — never from an LLM or imagery.

## 4. Non-goals

Everything in NOT_NOW.md. This section intentionally defers to that file to avoid divergence.

## 5. Functional requirements

### 5.1 Plot input (FR-1)

- FR-1.1 The user provides plot corners either via CLI dimension arguments (`--width 20 --depth 30`, which construct the four axis-aligned corners counterclockwise from the origin — exactly the rectangle the CSV below expresses) or as one CSV file.
- FR-1.2 CSV format (the only accepted file format):

  ```csv
  id,x_m,y_m
  1,0.0,0.0
  2,20.0,0.0
  3,20.0,30.0
  4,0.0,30.0
  ```

  - Units: meters, local plot coordinate system, counterclockwise order, first corner at origin. An explicit closing row (repeating corner 1) is tolerated and dropped.
  - The validation layer accepts 4–6 unique corner rows and checks closure, duplicates, self-intersection, winding order, and plausible area (50–10,000 m²) — owner instruction, 2026-07-13.
  - The generation gate then requires the 20 m × 30 m reference rectangle (right angles within 0.5°); anything else is rejected with a clear message (`only the 20 m x 30 m reference plot is supported in this MVP`).
- FR-1.3 The plot's geographic location is one WGS84 point: `--lat`, `--lon`. Used only by the character engine (FR-4).

### 5.2 Edge classification (FR-2)

- FR-2.1 Manual only. The user classifies each edge: `--edges street,neighbor,neighbor,neighbor` (edge i runs from corner i to corner i+1). Classes: `street`, `neighbor`, `path`, `unknown` (owner instruction, 2026-07-13).
- FR-2.2 Exactly one `street` edge is required in the slice; anything else is rejected with a clear message.
- FR-2.3 The street edge is treated as the front; the opposite edge is the rear; remaining edges are sides (non-street classes all take the side/rear setback of their position).
- FR-2.4 The user supplies the street width manually (meters, plausibility range 3–60 m). It is recorded and echoed in outputs; the demo setback rule set does not depend on it.

### 5.3 Setbacks and envelope (FR-3)

- FR-3.1 One demo rule set `DEMO-SETBACK-01`: front 3.0 m, sides 2.0 m, rear 2.0 m. Stored in `src/saudi_plot_design/data/demo/demo_setback_rules.json` with `"provenance": "demo"`.
- FR-3.2 The buildable envelope is the plot rectangle inset by the per-edge setbacks (16 m × 25 m for the reference plot).
- FR-3.3 The rule set id and its DEMO provenance appear in the PDF title block and DXF metadata.

### 5.4 Character recommendation (FR-4)

- FR-4.1 The plot point (lat/lon) is tested against the packaged DEMO zone dataset `src/saudi_plot_design/data/demo/architectural_character_zones/` (metadata + GeoJSON; see GEOSPATIAL_DATA_PROVENANCE.md and SAUDI_CHARACTER_ENGINE.md §3).
- FR-4.2 If the point falls in a zone, that zone's character is recommended with rule-based demo confidence; boundary and near-boundary points reduce confidence with warnings; overlapping zones resolve by documented unique priority or return all candidates for user selection; no match reports "unresolved" and requires manual selection. (Implemented in M3.)
- FR-4.3 The user must confirm a **character slug**: `--confirm-character najdi` (or interactively answer y/n to the recommended character). Generation never proceeds on an unconfirmed recommendation. Running non-interactively without `--confirm-character` prints the recommendation, the installed **character slugs** with their packs (`najdi (style pack: najdi_demo_v1)`), and the full DEMO disclaimer, then exits 2 with nothing written — this doubles as the lookup-only use case.
- FR-4.4 The confirmed character resolves deterministically to its style pack (`najdi` → `najdi_demo_v1`). A confirmed character with no installed pack stops the run with a clear message (only `najdi_demo_v1` is installed in the MVP).
- FR-4.5 No LLM, image, or heuristic inference of character — lookup + confirmation only.

### 5.5 Floor-plan skeleton (FR-5)

- FR-5.1 One authored skeleton: **Compact 3BR**, single floor, fits inside the envelope with margins. Runtime freedoms are limited to placement, street-derived orientation, mirroring, and bounded authored scaling (no search, no backtracking, no topology generation). An unfit skeleton returns an honest structured rejection.
- FR-5.2 Program (owner instruction, 2026-07-13): men's majlis (separate street entrance), guest WC, family living, dining, closed kitchen, master bedroom + en-suite master bath, bedroom 2, bedroom 3, shared bathroom, maid room, laundry/service, entry hall + corridor circulation, main family entrance. Rooms are rectangles that tile the footprint exactly; parking/garden remain site-level reserved zones.
- FR-5.3 Adjacency constraints: majlis adjacent to entry (guest separation), kitchen adjacent to dining, bedrooms accessed from the corridor, master bath authored as en-suite via the master bedroom, authored plumbing-wall relationships for wet rooms. These encode common Saudi privacy conventions as design defaults, not regulations.
- FR-5.4 The skeleton places door and window openings with real positions and widths on derived walls; the street-facing wall's openings drive the elevation (FR-6). Plan-level sill/head heights are nominal; the style pack governs the elevation.
- FR-5.5 Output is schematic: derived wall segments with schematic thicknesses, room name + area labels. No structure, no MEP, no furniture.
- FR-5.6 The concept is validated by a fixed 15-check minimum-livability list (containment, overlap, min areas/widths, wall geometry, door hosting/clearance, external walls, windows, no circulation through bedrooms, wet-zone plumbing, main/majlis entrance rules, opening overlap/extent). Nothing beyond these checks (no daylight, furniture, structural, fire, energy, MEP, accessibility, or municipal compliance claims).
- FR-5.7 M2 outputs: canonical concept JSON (with unconditional disclaimer) + engineering SVG technical preview rendered from the canonical geometry (D1) — not a deliverable sheet.

### 5.6 Front elevation (FR-6) — implemented in M4

- FR-6.1 One vector front elevation of the street-facing facade, width equal to the built front, height from the style pack (single floor + parapet). The primary facade is selected by geometric facing (wall orientation + outward normal + projection overlap onto the confirmed STREET boundary — never wall names or nearest-midpoint) and requires explicit user confirmation; the M4 orchestration gate (which embeds the M3 style confirmation gate) blocks generation with specific reasons otherwise. The facade spans all collinear street-facing external wall segments (the plan derives one per fronting room), so the facade wall records plural source ids. Coordinate system: facade X left-to-right as seen from the street (outward normal rotated 90° CCW), Z up from finished ground, origin at the minimal-X facade end — stable under mirroring/rotation.
- FR-6.2 Every opening on the street-facing wall in the plan appears in the elevation at its true horizontal position with full source traceability (plan opening id + wall id + room); sill/head heights come from the style pack. The elevation never adds, removes, moves, resizes, splits, or duplicates openings; a plan window incompatible with the pack's width/proportion rules is a structured unsupported-state rejection (the plan is never silently altered). Validated by a fixed 24-check facade list; template composition minimums (0.3 m edge clearance/spacing) are authored constants of the single Najdi demo template. Fence/gate is omitted (the pack declares only a family id, no dimensions); side/rear elevations remain out of scope.
- FR-6.3 The style pack (`najdi_demo_v1`) controls: wall height, parapet/crenellation geometry, opening proportion adjustments, surrounds/lintels, ornament bands, and layer/color mapping. See STYLE_PACK_SCHEMA.md.
- FR-6.4 The elevation is 2D vector geometry only (lines/polylines/hatch references) — no raster, no 3D.

### 5.7 Exports (FR-7)

- FR-7.1 PDF (A3 landscape, reportlab, implemented in M5): exactly two sheets — Sheet 1 site + floor plan (schedule, areas, setback assumptions, dimensions), Sheet 2 character + front elevation (classification, legend, traceability, limitations). Title band on each sheet with ids + short fingerprints; the unconditional disclaimer on both sheets; DEMO status in PDF metadata; byte-deterministic (`invariant=1`). Arabic style name stored in logical Unicode order in PDF metadata (Keywords) — documented fallback because base-14 fonts cannot shape Arabic and external fonts are out of scope.
- FR-7.2 DXF (ezdxf, R2018, implemented in M5): model space in meters, fixed 29-layer set per ARCHITECTURE.md §7; plan at origin, elevation at +30 m X; DEMO disclaimer on layer `DISCLAIMERS`, fingerprints + opening traceability on `TRACEABILITY` and as XDATA; byte-deterministic; ezdxf audit must be clean.
- FR-7.4 Export binding (M5): the export gate blocks unless the confirmed selection, facade, style pack version, and content fingerprints all match the exact plot/concept being exported; a typed manifest records SHA-256 hashes of every output.
- FR-7.3 Output paths: `out/<run-name>/design.pdf`, `out/<run-name>/design.dxf`, plus `run.json` echoing all inputs, the recommendation, and the confirmation for traceability. `run.json` must also contain the full DEMO disclaimer text in a `disclaimer` field and the provenance records of all three governed datasets consumed (zones, setback rules, style pack) — the disclaimer is unconditional on every output and every CLI summary (GEOSPATIAL_DATA_PROVENANCE.md §1 rule 3).

### 5.8 CLI (FR-8)

- FR-8.1 Single command pipeline, e.g.:

  ```
  spd generate --csv samples/plot_20x30.csv --lat 24.65 --lon 46.71 \
      --edges street,neighbor,neighbor,neighbor \
      --confirm-character najdi --out out/demo-run
  ```

- FR-8.2 `generate` is the **only** command. Lookup-only usage is `generate` without `--confirm-character` (FR-4.3); input validation errors are reported by `generate` before any work happens. No other subcommands.
- FR-8.3 Every implemented command and flag works end to end; no placeholder commands or flags (the CLI equivalent of "no unimplemented buttons"). Consequently the `spd` console entry point is created and registered only in M5, when `generate` works end to end — earlier milestones ship importable modules and tests only.

## 6. Acceptance criteria for the vertical slice

1. Running the FR-8.1 command on the sample CSV produces `design.pdf`, `design.dxf`, and `run.json` with zero errors, offline.
2. The DXF opens in a CAD viewer with exactly the documented layers; the PDF opens with 2 sheets and the disclaimer visible.
3. Editing a window position in the generated plan data and re-exporting moves the corresponding elevation opening (G2 verification, covered by a test).
4. A lat/lon inside the demo Najdi zone recommends `najdi`; a point outside all zones yields "no zone match"; both paths tested.
5. Refusing confirmation (or confirming a character with no installed pack) aborts before any file is written.
6. `pytest` and `ruff` pass clean.

## 7. Milestones

- **M0** — This documentation set + proposed repository structure + commit. (No code.)
- **M1** — Scaffold (`pyproject.toml`, package layout, CI-less local checks) + plot module: CSV/args ingest, rectangle validation, edge classification, demo setbacks, envelope. Tests. No CLI entry point (FR-8.3).
- **M2** — Compact 3BR skeleton + opening placement. Tests.
- **M3** — Character engine (demo GeoJSON + point-in-polygon + confirmation flow) and style-pack loader/validator with `najdi_demo_v1`. Tests.
- **M4** — Front elevation generator from plan openings + style pack. Tests.
- **M5** — PDF and DXF exporters + export binding gate + run.json/manifest (implemented per owner instruction, 2026-07-13, which scoped M5 to exports only). The `cli.py` + `spd` entry point was implemented afterwards on explicit owner invocation (2026-07-14): single `generate` command per FR-8, with `--confirm-character`/`--override-reason` and `--confirm-facade` surfacing the M3/M4 code-level gates, exit-2 lookup-only mode, and the M5 export pipeline underneath. The only accepted input file remains the corners CSV (FR-1.2) — no JSON project format.

Files planned for Milestone 1: `pyproject.toml`, `src/saudi_plot_design/{__init__.py,model.py,plot/geometry.py,plot/edges.py,rules/setbacks.py}`, `src/saudi_plot_design/data/demo/demo_setback_rules.json`, `samples/plot_20x30.csv`, `tests/test_plot_geometry.py`, `tests/test_edges.py`, `tests/test_setbacks.py`. (`.gitignore` was created in M0; no `cli.py` until M5 per FR-8.3.)

## 8. Assumptions

- A1: Local plot coordinates in meters are acceptable for design output; georeferencing of drawings is not required (only the lookup point is geographic).
- A2: The demo setback values (3/2/2/2) are plausible placeholders; real values differ by municipality and must come from verified data later.
- A3: The Najdi style pack is a demo interpretation (proportions, crenellation motifs) and is NOT derived from the official Saudi Architecture Design Guidelines documents, which we do not have in verified machine-readable form.
- A4: Single-floor massing is acceptable for a first concept even though most Saudi villas are two floors (multi-floor is on NOT_NOW).
- A5: Users can run a Python CLI (pipx/pip install).

## 9. Missing verified Saudi data (required before any "real data" claim)

See GEOSPATIAL_DATA_PROVENANCE.md §4 for the authoritative list and acquisition plan. Summary: official Saudi Architecture character-zone polygons; official per-style design guideline rules; municipal setback/zoning regulations per amanah; parcel geometry source; verified material/color palettes per style.
