# Saudi Plot Platform

**Private / proprietary — all rights reserved. Not open source. Do not redistribute.**

A full-stack web application that turns a rectangular residential plot in Saudi Arabia into a setback-aware Compact 3BR floor-plan with a Saudi-character front elevation, delivered as PDF / DXF / SVG outputs.

## Architecture

- **Frontend**: React + Vite (`frontend/`) — port **5000** (webview)
- **Backend**: FastAPI + SQLAlchemy (`backend/src/saudi_plot_api/`) — port **8000** (console)
- **Design engine**: Deterministic core (`backend/src/saudi_plot_design/`)
- **Database**: SQLite at `backend/var/saudi_plot_api.db`
- **Geo knowledge**: `knowledge/geo/07_database/sbc_rules.sqlite`

## How to run

Two workflows are configured and start automatically:

| Workflow | Command | Port |
|---|---|---|
| `Start application` | `cd frontend && npm run dev` | 5000 (webview) |
| `Backend API` | `cd backend && uvicorn --factory saudi_plot_api.main:create_app --host 0.0.0.0 --port 8000 --reload` | 8000 (console) |

The Vite dev server proxies all `/api/*` requests to the backend, so cookies and sessions work correctly on Replit without CORS issues.

## Database migrations

```bash
cd backend && python -m saudi_plot_api.migrate
```

## Environment variables

All `SPD_*` variables are set as Replit environment variables (shared). Key settings:

- `SPD_DATABASE_URL` — SQLite path (switch to PostgreSQL URL for production)
- `SPD_CORS_ORIGINS` — set to `["http://localhost:5000"]` for the Vite proxy
- `SPD_COOKIE_SECURE=false` — development only; production enforces `true`
- `GEMINI_API_KEY` — optional; leave empty to run without AI extraction/renders

## AI features (optional)

Set `GEMINI_API_KEY` as a Replit Secret to enable:
- Deed OCR extraction (upload a deed image instead of entering plot data manually)
- Photorealistic AI presentation renders

The app works fully without a Gemini key — manual entry is always available and renders report `render_provider_unconfigured`.

## Demo disclaimer

Every reference dataset (geographic zones, architectural character, style rules) is **demo provenance**. No output is a legal or regulatory document. Geographic zone boundaries carry a declared accuracy of ±3 km. All outputs render this disclaimer unconditionally.

## User preferences

- Keep the existing monorepo structure (`backend/`, `frontend/`, `knowledge/`)
- Do not restructure or migrate to a different stack without explicit request
