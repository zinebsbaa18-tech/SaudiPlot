# LOCKED_MVP_SCOPE.md

**Status: LOCKED — approved via the Claude–Codex strategy debate recorded in PROJECT_BRIEF.md.**
**Any change to this file requires an explicit user instruction. Codex review comments may never expand this scope.**

## Product (one sentence)

A CLI tool that takes one rectangular residential plot, applies a demo setback rule set, generates a Compact 3BR single-floor plan skeleton, recommends a Saudi architectural character via point-in-polygon lookup against clearly labeled demo zone data (with mandatory user confirmation), applies one pilot Saudi facade style, and exports a vector front elevation and plan as one PDF and one layered DXF.

## Locked first vertical slice

The MVP is exactly this pipeline, end to end, and nothing else:

| # | Capability | Locked definition |
|---|------------|-------------------|
| 1 | Plot input | One rectangular plot, 20 m × 30 m (20 m street frontage, 30 m depth). Corners supplied manually via the single CSV format defined in PRD.md §5.1, or constructed from CLI dimension arguments (`--width`/`--depth`, axis-aligned counterclockwise from the origin — the same rectangle). The validation layer structurally accepts 4–6 unique points (closure, self-intersection, winding, plausible-area checks; owner instruction, 2026-07-13), but generation proceeds only for the 20 m × 30 m reference rectangle. No other input formats. |
| 2 | Plot location | One WGS84 point (`--lat`, `--lon`) used only for character-zone lookup. |
| 3 | Edge classification | Manual only: each boundary edge is declared `street`, `neighbor`, `path`, or `unknown` by the user (classes `path`/`unknown` added by owner instruction, 2026-07-13). Exactly one `street` edge in the slice. The user also supplies the street width manually (plausibility-checked 3–60 m; demo setbacks do not depend on it). No automatic detection. |
| 4 | Setbacks | One demo rule set (`DEMO-SETBACK-01`): front 3.0 m, side 2.0 m, side 2.0 m, rear 2.0 m. Clearly labeled DEMO, not an official Saudi regulation. |
| 5 | Buildable envelope | Rectangle produced by offsetting the plot by the setbacks (16 m × 25 m for the reference plot). |
| 6 | Floor plan | One authored skeleton only: "Compact 3BR", single floor. Program (expanded by owner instruction, 2026-07-13): men's majlis with separate street entrance, guest WC, family living, dining, closed kitchen, master bedroom + en-suite master bath, bedrooms 2–3, shared bathroom, maid room, laundry/service, entry hall + corridor circulation, main family entrance. Rectangular rooms tiling the footprint, derived walls, wall-hosted doors, external-wall-hosted windows. Runtime freedoms limited to placement, street-derived orientation, mirroring, and bounded authored scaling — no search or topology generation; unfit skeletons return a structured rejection. Validated by the fixed 15-check livability list (PRD FR-5.6). M2 outputs: canonical concept JSON + engineering SVG preview (technical preview, not a deliverable sheet). No structural design. |
| 7 | Character engine | Point-in-polygon lookup of the plot location against the packaged DEMO zone dataset `src/saudi_plot_design/data/demo/architectural_character_zones/` (structure per owner instruction, 2026-07-13). Produces a typed CharacterMatch with rule-based demo confidence, boundary/overlap handling, and provenance. The user must confirm or override (with reason) through the code-level confirmation gate before generation continues. No LLM inference, no image-based inference, no external APIs. |
| 8 | Facade style | Exactly one pilot style pack: `najdi_demo_v1` (a clearly labeled demo interpretation of the Najdi character, 4-file directory pack, status `demo_requires_architect_review`). The loader loads exactly this pack and errors on a second. No second style. |
| 9 | Front elevation | One vector front elevation of the street-facing facade, derived from the real door/window openings placed by the floor-plan skeleton — not a decorative template. Style pack controls heights, opening proportions, and ornament (e.g., parapet crenellation). Implemented in M4 with geometric primary-facade selection + explicit confirmation, full plan-opening traceability, a fixed 24-check validator, and an engineering SVG preview (technical preview; PDF/DXF remain M5). Exactly one elevation — no side/rear/corner-secondary elevations. |
| 10 | PDF export | One PDF (A3): site + plan sheet and front elevation sheet, with title block and a mandatory DEMO-DATA disclaimer. |
| 11 | DXF export | One DXF (R2018) with the fixed layer set defined in ARCHITECTURE.md §7. |

## Locked technology stack

- Python 3.11+
- `shapely` 2.x — geometry, offsets, point-in-polygon
- `ezdxf` 1.x — layered DXF export
- `reportlab` 4.x — vector PDF export
- `pydantic` 2.x — style pack and input validation
- `pytest` — tests; `ruff` — lint/format
- Interface: CLI only (`spd` with a single `generate` command; lookup-only usage is `generate` without confirmation). No web UI, no GUI, therefore no buttons of any kind in the MVP.

## Locked data policy

- All geographic and architectural reference data ships as DEMO data, labeled with demo provenance inside each file (per-file contract in GEOSPATIAL_DATA_PROVENANCE.md §1 rule 4).
- The DEMO disclaimer is **unconditional**: every output of every run renders it — PDF, DXF, `run.json`, and all CLI summaries.
- MVP loaders reject any reference file claiming `verified` provenance; self-declared metadata can never make data look official. Verified-data activation is a future, user-approved scope change.
- No official Saudi geographic, zoning, setback, or architectural-character data is fabricated or implied to be real. See GEOSPATIAL_DATA_PROVENANCE.md.

## Explicit exclusions

Everything in NOT_NOW.md is out of scope. Highlights: OCR, Revit/IFC/GLB, any 3D, photorealistic rendering, municipality integration, multi-floor, structural design, MEP, more than one style pack, automatic edge classification, LLM/image-based character inference.

## Change control

1. Scope changes require an explicit user instruction referencing this file.
2. Codex findings that require scope expansion are recorded in REVIEW_PROCESS.md triage as `REJECTED — out of locked scope` and are not implemented.
3. Bug fixes and refactors inside the slice above are always in scope.
