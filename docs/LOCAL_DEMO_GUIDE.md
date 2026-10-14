# Local Demo Guide

Runs the complete journey from this monorepo. (The imported
`backend/docs/LOCAL_DEMO_RUNBOOK.md` describes the older standalone-repo
layout; this guide supersedes it here.)

- Frontend: http://localhost:5173
- Backend: http://localhost:8000 — API docs: http://localhost:8000/docs

## One-time setup

```powershell
git lfs pull            # knowledge databases (if not fetched at clone)
.\scripts\setup.ps1
```

This creates `backend/.venv`, installs `backend[dev,web]`, runs `npm ci` in
`frontend/`, and copies both `.env.example` templates to gitignored `.env`
files. The defaults work as-is for local HTTP development:

- `SPD_COOKIE_SECURE=false` (required for plain-http localhost)
- `SPD_CORS_ORIGINS=["http://localhost:5173"]`
- `SPD_GEO_KNOWLEDGE_DB=../knowledge/geo/07_database/sbc_rules.sqlite`
- `GEMINI_API_KEY` empty — deed uploads return the structured
  `extraction_unconfigured` state (the journey continues via manual entry)
  and presentation renders record `render_provider_unconfigured`. Set a key
  in `backend/.env` only; it never belongs in any frontend file.

## Start

```powershell
.\scripts\start-demo.ps1        # backend + frontend, each in its own window
```

`start-backend.ps1` applies migrations (`python -m saudi_plot_api.migrate`)
before starting uvicorn.

## The journey

1. **Landing** → "ابدأ الآن" → **Upload**: drop a deed PDF/JPG/PNG, or choose
   manual entry. Without a Gemini key the upload reports that extraction is
   unconfigured and manual entry continues the flow.
2. **Confirm data**: extracted or manually entered plot data (dimensions,
   boundaries, optional coordinates — always latitude and longitude together;
   half pairs are rejected).
3. **Questions 1–6** and **room catalog**: family preferences and the room
   program, validated against the Compact 3BR engine limitation with an
   honest engine note.
4. **Generating**: the design run streams observable states from preparing
   inputs through preparing outputs; non-reference plots produce explicit
   assumptions, never silent changes.
5. **Result**: floor-plan and elevation previews with PDF / DXF / `run.json`
   downloads — every output carries the unconditional DEMO disclaimer — plus
   the optional AI presentation render and a sanitized, coordinate-free share
   link.

## Verifying

```powershell
.\scripts\test-backend.ps1      # full backend suite
.\scripts\build-frontend.ps1    # production build + lint
```

## Troubleshooting

- **Port already in use** — stop older uvicorn/vite processes or change the
  port (then keep `SPD_CORS_ORIGINS` and `VITE_API_BASE_URL` in sync).
- **Geo lookup says knowledge base not configured** — run `git lfs pull`;
  without LFS content the sqlite file is a small text pointer, and
  `SPD_GEO_KNOWLEDGE_DB` must point at the real database.
- **CORS errors in the browser console** — the backend refuses `*`;
  `SPD_CORS_ORIGINS` must list the exact Vite origin as a JSON array.
- **Cookies not set** — keep `SPD_COOKIE_SECURE=false` for plain-http
  localhost; production enforces secure settings.
