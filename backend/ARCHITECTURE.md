# ARCHITECTURE.md — Saudi Plot Design Studio (MVP)

Scope authority: LOCKED_MVP_SCOPE.md. This document describes how the locked MVP is built — nothing more.

## 1. Overview

A single offline Python package exposing a CLI (`spd`). One-directional pipeline; every stage is a pure function over plain data objects so each stage is testable in isolation.

```
input (CSV/args + lat/lon + edge classes)
      │
      ▼
[plot]        PlotModel: rectangle validation, edge classification
      │
      ▼
[rules]       SetbackRuleSet (demo JSON) → BuildableEnvelope
      │
      ▼
[character]   point-in-polygon over demo GeoJSON → recommendation
      │            │
      │            ▼
      │       user confirmation (required)
      ▼
[styles]      StylePack load + pydantic validation (najdi_demo_v1)
      │
      ▼
[planner]     Compact3BR skeleton → rooms, walls, openings
      │
      ▼
[elevation]   front elevation from street-wall openings + style pack
      │
      ▼
[export]      PDF (reportlab) + DXF (ezdxf) + run.json
```

## 2. Technology stack (locked)

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Geometry/CAD library ecosystem, fast iteration |
| Geometry | shapely 2.x | Robust polygon ops, buffering/offsets, point-in-polygon |
| DXF | ezdxf 1.x | Mature layered DXF writer, no AutoCAD dependency |
| PDF | reportlab 4.x | Deterministic vector PDF, offline |
| Validation | pydantic 2.x | Style pack + input schema enforcement with good errors |
| CLI | argparse (stdlib) | Zero extra deps for the single `generate` command |
| Tests / lint | pytest, ruff | Standard |

No web framework, no database, no network calls at runtime.

## 3. Repository structure (proposed, created from M1 onward)

```
saudi-plot-design/
├── PROJECT_BRIEF.md              # locked brief (input)
├── CLAUDE.md                     # agent guidance
├── PRD.md                        # product requirements
├── ARCHITECTURE.md               # this file
├── LOCKED_MVP_SCOPE.md           # locked scope (change-controlled)
├── NOT_NOW.md                    # locked exclusions
├── SAUDI_CHARACTER_ENGINE.md     # character lookup design
├── STYLE_PACK_SCHEMA.md          # style pack JSON schema
├── GEOSPATIAL_DATA_PROVENANCE.md # data provenance policy + missing data
├── REVIEW_PROCESS.md             # Claude implement / Codex review loop
├── .gitignore
├── pyproject.toml                # M1
├── src/
│   └── saudi_plot_design/
│       ├── __init__.py
│       ├── cli.py                # spd entrypoint: single `generate` command (implemented on owner invocation, 2026-07-14)
│       ├── model.py              # shared dataclasses: PlotModel, Envelope, Opening…
│       ├── output.py             # structured JSON plot/envelope report (M1) with unconditional disclaimer
│       ├── plot/
│       │   ├── geometry.py       # CSV/args ingest, rectangle validation
│       │   └── edges.py          # manual street/neighbor classification
│       ├── rules/
│       │   └── setbacks.py       # rule set load + envelope computation
│       ├── character/
│       │   ├── models.py         # LocationPoint, Zone, CharacterMatch, StyleSelection…
│       │   ├── engine.py         # dataset load + point-in-polygon + confidence
│       │   └── selection.py      # confirmation/override + code-level gate
│       ├── styles/
│       │   ├── schema.py         # pydantic models per STYLE_PACK_SCHEMA.md
│       │   └── loader.py         # strict single-pack loader (najdi_demo_v1)
│       ├── planner/
│       │   ├── skeleton.py       # authored Compact 3BR skeleton data (rooms, doors, windows, mins)
│       │   ├── compact_3br.py    # placement transforms, wall derivation, opening hosting
│       │   └── validation.py     # fixed 15-check livability validator
│       ├── elevation/
│       │   ├── models.py         # PrimaryFacadeSelection, FacadeWall/Opening/Element/Concept
│       │   ├── facade_selection.py  # street boundary -> facing-wall geometric match
│       │   ├── front.py          # orchestration gate + projection + bounded Najdi template
│       │   └── validation.py     # fixed 24-check facade validator
│       ├── export/
│       │   ├── svg_preview.py    # M2 engineering plan preview (renders canonical geometry only)
│       │   ├── svg_elevation.py  # M4 engineering facade preview (canonical geometry only)
│       │   ├── binding.py        # export safety gate (fingerprint binding, M5)
│       │   ├── pdf.py            # reportlab A3 two-sheet export (M5)
│       │   ├── dxf.py            # ezdxf R2018 fixed-layer export (M5)
│       │   ├── runlog.py         # run.json + typed ExportManifest + hashing (M5)
│       │   └── pipeline.py       # export orchestrator: gate -> pdf -> dxf -> audit (M5)
│       └── data/
│           └── demo/             # ALL demo-provenance data; shipped as package data
│               ├── demo_setback_rules.json
│               ├── architectural_character_zones/
│               │   ├── zones.geojson
│               │   └── metadata.json
│               └── styles/
│                   └── najdi_demo_v1/   # style.json, facade_rules.json, materials.json, source_metadata.json
├── samples/
│   └── plot_20x30.csv            # reference input
├── out/                          # generated, gitignored
└── tests/
    ├── test_plot_geometry.py
    ├── test_edges.py
    ├── test_setbacks.py
    ├── test_character_engine.py
    ├── test_style_pack.py
    ├── test_planner.py
    ├── test_elevation.py
    └── test_exports_e2e.py
```

## 4. Core data model (`model.py`)

Plain dataclasses / pydantic models passed between stages:

- `PlotModel`: corners (4 × (x, y) m, CCW), edges (`EdgeClass` per edge: STREET/NEIGHBOR), location (lat, lon).
- `SetbackRuleSet`: id, provenance, front/side/rear distances (m).
- `BuildableEnvelope`: rectangle (m), derived from PlotModel + SetbackRuleSet.
- `Room`: name, rect, function tag.
- `Opening`: kind (DOOR/WINDOW), wall reference, offset along wall (m), width (m); sill/head heights are style-pack concerns, not plan concerns.
- `FloorPlan`: rooms, walls, openings; `street_wall_openings()` accessor feeds the elevation.
- `CharacterMatch` / `StyleSelection` / `StylePackReference` (in `character/models.py`): typed classification, selection, and gate results with provenance, confidence, and warnings (M3).
- `StylePackData`: per STYLE_PACK_SCHEMA.md (4-file directory pack, `styles/schema.py`).
- `ElevationGeometry`: list of primitives (polyline, rect, hatch-tag) with layer tags — shared by both exporters so PDF and DXF are always consistent.

## 5. Key design decisions

- **D1 — Single geometry source for both exports.** `ElevationGeometry`/plan geometry with layer tags is computed once; `export/pdf.py` and `export/dxf.py` are dumb renderers. Prevents PDF/DXF divergence.
- **D2 — Local metric CRS for design, WGS84 only for lookup.** Drawings live in a local meter frame (origin = corner 1). Only the character engine touches geographic coordinates. No projection math in the MVP.
- **D3 — Confirmation is a hard gate.** `character/engine.py` returns a recommendation; the pipeline refuses to call the planner without an explicit confirmed **character slug** (e.g., `najdi`), which is then resolved deterministically to its style pack (`najdi` → `najdi_demo_v1`). A confirmed character with no pack aborts. Enforced by code path, not convention.
- **D4 — Provenance travels with data, and the MVP trusts none of it.** Every governed reference file (zones, rules, style packs) embeds provenance; loaders reject files without it AND reject any file claiming `verified` — only `demo` loads in the MVP. The DEMO disclaimer is rendered unconditionally on every output (PDF, DXF, `run.json`, CLI summaries). See GEOSPATIAL_DATA_PROVENANCE.md §1.
- **D5 — Openings are the contract between plan and elevation.** The elevation consumes `FloorPlan.street_wall_openings()`; it never invents openings. This is what makes the elevation "derived from real plan openings".
- **D6 — No plugin system.** Style packs are 4-file JSON directories; the loader loads exactly one pack and errors on a second — no scanning or combining. One pack ships. Extensibility is a schema property, not a framework.

## 6. Error handling

- All user-input errors (bad CSV, non-rectangle, wrong edge count, unknown character, missing pack) raise `SpdInputError` with a one-line actionable message; CLI exits 2.
- Internal invariant violations raise normally (bug = traceback); CLI exits 1.
- No partial output: exporters write to a temp dir and move into `out/<run-name>/` only on full success.

## 7. Export architecture (implemented in M5)

**Binding gate** (`export/binding.py`): export runs only when the whole chain binds to the exact objects — plot/concept validity, confirmed facade selection and style (pack version bound), facade validity, and content-fingerprint equality between the facade's recorded `plot_fingerprint`/`concept_fingerprint` and the objects being exported. Stale/substituted artifacts fail with specific reasons and nothing is written.

**PDF** (`export/pdf.py`, ReportLab, `invariant=1` → byte-deterministic): one A3-landscape document, exactly two sheets. Sheet 1 site + floor plan (~1:200 approx, else NTS): plot/edges/street width, envelope, footprint, rooms/walls/openings, dimensions, room schedule, area summary, demo setback note, location/reference notes, title band with ids + short fingerprints, disclaimer footer. Sheet 2 character + front elevation (~1:77 approx): facade elements/openings from FacadeConcept, dimensions, classification block, material legend, style-element summary, opening traceability, limitations, disclaimer. Arabic fallback (documented): base-14 PDF fonts cannot shape Arabic and external fonts are out of scope, so the Arabic style name is stored in logical Unicode order in PDF metadata (Keywords) with an on-sheet note; DXF and run.json carry it directly.

**DXF** (`export/dxf.py`, ezdxf, R2018/AC1032, `$INSUNITS=6` meters, `write_fixed_meta_data_for_testing` + pinned header GUIDs/timestamps → byte-deterministic): fixed layer set of 29 — plan/site `PLOT_BOUNDARY, PLOT_EDGE_LABELS, STREET, SETBACKS, BUILDABLE_ENVELOPE, BUILDING_FOOTPRINT, WALLS_EXTERNAL, WALLS_INTERNAL, DOORS, WINDOWS, ROOM_NAMES, ROOM_AREAS, DIMENSIONS, NORTH_ARROW, SITE_TEXT`; elevation `ELEVATION_WALL, ELEVATION_DOORS, ELEVATION_WINDOWS, ELEVATION_SHADING, ELEVATION_PARAPET, ELEVATION_PLINTH, ELEVATION_DECORATION, ELEVATION_FENCE, ELEVATION_GATE, ELEVATION_DIMENSIONS, ELEVATION_TEXT` (fence/gate layers exist but stay empty — the template omits them); audit `TITLE_BLOCK, DISCLAIMERS, TRACEABILITY` (+ ezdxf-mandated `0`/`Defpoints`). Writing outside the set or an unsupported geometry kind is a structured failure. Openings carry source ids as XDATA (appid `SPD`); room names/areas are editable TEXT; dimensions are real DIMENSION entities. Placement: plan at plot-local origin; elevation X/Z → model X/Y at +30 m X offset, ground at y=0.

**run.json / manifest** (`export/runlog.py`, `export/pipeline.py`): run.json records ids, fingerprints, dataset/pack versions, confirmations, validation summaries, setbacks/envelope, inputs, output files (relative paths) and their SHA-256; deterministic except the injectable `run_id`/`generation_timestamp`. The typed `ExportManifest` hashes all three outputs and proves which exact plot/concept/facade produced them. Reopen validation is automated: pypdf (page count/size/text/metadata) and ezdxf (`audit()` must be error-free); AutoCAD is not required.

## 8. Testing strategy

- Unit tests per module (geometry math, envelope numbers, point-in-polygon in/out/edge cases, pack validation failures).
- One end-to-end test: sample CSV → files exist, DXF layer names exact, PDF page count = 2.
- The G2 test: mutate one street-wall opening's offset in the FloorPlan, regenerate elevation, assert the elevation primitive moved by the same amount.
- Tests never hit the network; demo data files are the fixtures.

## 9. Performance & footprint

Trivial by construction (one plot, hundreds of primitives). No optimization work is in scope; the only budget is PRD G1 (< 60 s end to end), which is expected to be < 2 s in practice.
