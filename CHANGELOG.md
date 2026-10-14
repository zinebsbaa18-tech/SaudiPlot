# Changelog

## demo-v0.1.0 — 2026-07-20

First integrated frontend–backend architectural design demo.

- Monorepo assembled from three source repositories (see
  `docs/SOURCE_VERSIONS.md` for exact branches and SHAs):
  - `backend/` — deterministic design engine + FastAPI web adapter
    (imported with full git history)
  - `frontend/` — frozen accepted React journey wired to the live backend
    (imported with full git history)
  - `knowledge/geo/` — versioned advisory geo knowledge package v0.1.1
    (validated, non-private subset; binaries in Git LFS)
- Complete local demo journey: deed upload or manual entry → guided
  questions → deterministic Compact 3BR generation → PDF/DXF/SVG outputs,
  optional server-side AI extraction and presentation render.
- Separated backend and frontend CI workflows.
- Unconditional DEMO disclaimer on all outputs; geographic accuracy ±3 km
  (declared, advisory only).
