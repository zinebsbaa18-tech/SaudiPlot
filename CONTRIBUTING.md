# Contributing

This is a private, proprietary repository with a deliberately **locked scope**.
Read these before changing anything:

1. `backend/LOCKED_MVP_SCOPE.md` — the locked scope; only the owner changes it.
2. `backend/NOT_NOW.md` — locked exclusions; never build, stub, or surface these.
3. `backend/GEOSPATIAL_DATA_PROVENANCE.md` — data integrity rules.
4. `docs/SOURCE_VERSIONS.md` — where each part of this monorepo came from.

## Ground rules

- **Never fabricate official Saudi geographic, regulatory, or architectural
  data.** All reference data is demo provenance and labeled as such; loaders
  reject any `verified` claim; the DEMO disclaimer renders unconditionally.
- **The frontend journey is frozen.** Do not change its routes, questions,
  labels, text, ordering, components, or visual design without an explicit
  owner decision.
- Architectural character = point-in-polygon lookup + user confirmation. Never
  an LLM, never images.
- The elevation never adds, removes, or splits plan openings.
- No placeholder commands, flags, or UI ("no unimplemented buttons").
- Keep the dependency direction: `saudi_plot_api` → `saudi_plot_design`, never
  the reverse (enforced by tests).

## Workflow

- Work on a branch; keep commits focused (one concern per commit).
- Before committing:
  ```powershell
  backend\.venv\Scripts\python -m ruff check backend
  backend\.venv\Scripts\python -m ruff format --check backend
  .\scripts\test-backend.ps1
  .\scripts\build-frontend.ps1
  ```
- No commits with failing checks. CI runs the same gates.
- Never commit: `.env`, runtime databases, uploads, generated outputs,
  `private_cases/`, `node_modules/`, virtual environments, agent/review logs.
- Large validated knowledge binaries (`*.sqlite`, `*.gpkg`, `*.db`, `*.pdf`
  under `knowledge/`) go through **Git LFS**; ordinary source code never does.
