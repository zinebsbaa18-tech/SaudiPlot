# CLAUDE.md — Saudi Plot Design Studio

Guidance for Claude Code working in this repository.

## What this project is

A CLI tool (`spd`) that turns one rectangular residential plot into a setback-aware Compact 3BR plan skeleton with a Saudi-character front elevation, exported as PDF + layered DXF. Full definition: LOCKED_MVP_SCOPE.md (locked), PRD.md, ARCHITECTURE.md.

## Read these before changing anything

1. **LOCKED_MVP_SCOPE.md** — the scope. It is locked; only the user can change it.
2. **NOT_NOW.md** — locked exclusions. Never build, stub, or reference these in UI/CLI surface.
3. **REVIEW_PROCESS.md** — how milestones are implemented, reviewed by Codex, and closed.
4. **GEOSPATIAL_DATA_PROVENANCE.md** — data integrity rules (the project's biggest risk).

## Roles

- Claude Code is the **lead implementer and the only agent that modifies files**.
- Codex is a **read-only reviewer**; its findings are review comments, triaged per REVIEW_PROCESS.md §3. Never implement a Codex suggestion that expands the locked scope.

## Hard rules

- Do not expand the MVP scope; do not implement more than the one pilot style pack (`najdi_demo_v1` — the loader loads exactly that file and errors on extras).
- Never fabricate official Saudi geographic, regulatory, or architectural data. All shipped reference data is `demo` provenance, labeled in-file; loaders reject any `verified` claim in the MVP; the DEMO disclaimer is unconditional on every output including `run.json` and CLI summaries (GEOSPATIAL_DATA_PROVENANCE.md).
- Architectural character comes from point-in-polygon lookup + user confirmation only — never from an LLM or images (SAUDI_CHARACTER_ENGINE.md). The confirmed character slug resolves deterministically to its pack (`najdi` → `najdi_demo_v1`).
- No placeholder CLI commands/flags ("no unimplemented buttons"). `generate` is the only command, and the `spd` entry point is registered only in M5 when it works end to end.
- The elevation never adds, removes, or splits openings; oversized plan windows are a validation error.
- One commit per milestone; review-fix commits separate; no commits with failing checks.

## Stack & commands

Python 3.11+, shapely, ezdxf, reportlab, pydantic; argparse CLI. From M1 onward:

```bash
python -m pip install -e ".[dev]"   # setup
ruff check . && ruff format --check .
pytest
# The only CLI command (without --confirm-character it prints the
# recommendation + disclaimer and exits 2 without writing anything;
# --confirm-facade confirms the primary street facade):
spd generate --csv samples/plot_20x30.csv --lat 24.65 --lon 46.71 \
    --edges street,neighbor,neighbor,neighbor --street-width 15 \
    --confirm-character najdi --confirm-facade --out out/demo-run
```

## Layout

`src/saudi_plot_design/` — pipeline modules (`plot/`, `rules/`, `character/`, `styles/`, `planner/`, `elevation/`, `export/`); `src/saudi_plot_design/data/demo/` — all demo-provenance data, shipped as package data so installed copies work offline; `samples/` — reference inputs; `tests/`; `out/` — generated, gitignored. Full tree: ARCHITECTURE.md §3.

## Design invariants (don't break)

- D1: PDF and DXF render from the same geometry objects — never compute geometry inside an exporter.
- D3: character confirmation is a hard code-path gate before the planner runs.
- D4: loaders reject reference files without provenance and any file claiming `verified`; the DEMO disclaimer renders unconditionally.
- D5: the elevation only draws openings that exist in the floor plan.

## Milestones

M0 docs (done) → M1 plot/setbacks → M2 planner → M3 character+styles → M4 elevation → M5 exports+e2e. Details: PRD.md §7.

Post-MVP (branch `m6-approved-case-library`): M6A ingests one private IFC4 villa into a reviewable design case (`src/saudi_plot_design/cases/`, optional `[cases]` dependency, gitignored `private_cases/` source). See CASE_INGESTION_M6A.md — the approval gate (`assert_template_usable`) blocks any non-approved case from generator use.
