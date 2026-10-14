# Source Versions

Exact provenance of everything in this monorepo. The three source
repositories/folders remain the upstream homes of their content and were not
modified by the export.

## backend/ — saudi-plot-design

| | |
|---|---|
| Source | local repository `saudi-plot-design` |
| Branch | `demo-complete-journey` |
| Commit | `4fb065f66061f66ccaa57d11e9279480add151c2` |
| Import method | `git subtree add --prefix=backend` (full history preserved) |
| Working tree at import | clean (no uncommitted tracked changes) |

Contains the deterministic design core (`src/saudi_plot_design`), the FastAPI
web adapter (`src/saudi_plot_api`), alembic migrations, the 876-test suite,
project configuration, `.env.example`, and all project documentation
(locked scope, provenance rules, ADRs, runbook).

## frontend/ — Saudi-Plot-Frontend-main

| | |
|---|---|
| Source | local repository `Saudi-Plot-Frontend-main` |
| Branch | `demo-backend-integration` |
| Commit | `59405b1e9ec68eb0aed37535743bca7d2c9109f7` |
| Import method | `git subtree add --prefix=frontend` (full history preserved) |
| Working tree at import | clean (no uncommitted tracked changes) |

The accepted frozen journey (routes, questions, labels, ordering, components,
visual design) is unchanged. History: frozen baseline snapshot → backend
integration → StrictMode double-mount fix.

## knowledge/geo/ — sbc_geo_knowledge

| | |
|---|---|
| Source | local working folder `sbc_geo_knowledge` (no usable git history) |
| Package version | v0.1.1, built 2026-07-19 (see `knowledge/geo/VERSION.json`) |
| Import method | file copy of the validated, non-private subset; SHA-256 recorded per file in `knowledge/geo/MANIFEST.csv` |

Excluded from the export: raw source archives (`00_raw_sources/`), extracted
source-document imagery (`02_extracted_documents/`), QA overlay imagery
derived from it, duplicate exports (`11_exports/`), and pipeline/API/viewer
code. `sbc_rules.sqlite` and `sbc_geo_knowledge.gpkg` are tracked with
Git LFS.

## Adaptations made in the monorepo (sources untouched)

1. `backend/.env.example` — `SPD_GEO_KNOWLEDGE_DB` repointed from an absolute
   source-machine path to `../knowledge/geo/07_database/sbc_rules.sqlite`.
2. `frontend/.claude/launch.json` — removed (local agent-tool launch config;
   excluded category for this export). No journey content was touched.
3. `backend/docs/LOCAL_DEMO_RUNBOOK.md` still describes the pre-monorepo
   standalone layout; the canonical monorepo guide is
   [`docs/LOCAL_DEMO_GUIDE.md`](LOCAL_DEMO_GUIDE.md).
