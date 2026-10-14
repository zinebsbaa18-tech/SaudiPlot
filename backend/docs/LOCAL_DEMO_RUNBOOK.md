# Local Demo Runbook

Runs the complete frozen frontend journey against the local backend.

- Backend: http://localhost:8000 (API docs: http://localhost:8000/docs)
- Frontend: http://localhost:5173

## One-time setup

Backend (repository `C:\AI\saudi-plot-design`):

```powershell
cd C:\AI\saudi-plot-design
py -3.14 -m venv .venv          # if .venv does not exist yet
.venv\Scripts\python -m pip install -e ".[dev,web]"
Copy-Item .env.example .env      # then edit .env as needed (see below)
.venv\Scripts\python -m alembic upgrade head
```

`.env` notes:

- `SPD_COOKIE_SECURE=false` is required for plain-http local development.
- `SPD_CORS_ORIGINS=["http://localhost:5173"]` must list the Vite origin.
- `SPD_GEO_KNOWLEDGE_DB` points at the sbc_geo_knowledge SQLite build
  (default template value: `C:/AI/sbc_geo_knowledge/07_database/sbc_rules.sqlite`).
- `GEMINI_API_KEY` is optional. Without it, deed uploads return the structured
  code `extraction_unconfigured` (the journey continues via manual entry) and
  presentation renders record `render_provider_unconfigured`. The key lives in
  the backend environment only — never in any frontend file.

Frontend (repository `C:\AI\Saudi-Plot-Frontend-main`):

```powershell
cd C:\AI\Saudi-Plot-Frontend-main
npm install
Copy-Item .env.example .env      # sets VITE_API_BASE_URL=http://localhost:8000
```

## Start (two PowerShell terminals)

Terminal 1 — backend:

```powershell
cd C:\AI\saudi-plot-design
.venv\Scripts\python -m uvicorn --factory saudi_plot_api.main:create_app --host 127.0.0.1 --port 8000
```

Terminal 2 — frontend:

```powershell
cd C:\AI\Saudi-Plot-Frontend-main
npm run dev
```

Open http://localhost:5173.

## The journey

1. Landing → "ابدأ الآن" → Upload. Uploading a deed PDF/JPG/PNG sends it to
   the backend (`POST /api/v1/projects/{id}/documents`); with a configured
   Gemini key the extracted data lands on ConfirmData, otherwise the existing
   failure path opens manual entry with a clear message.
2. Manual entry works with no AI at all: dimensions + street width + map
   coordinates → saved as the project's plot record.
3. ConfirmData edits are persisted as corrections with the plot.
4. Questions 1–6 and the room catalogue persist on every step.
5. The Generating screen starts a real design run and polls
   `GET /api/v1/design-runs/{id}` — the four progress rows advance on actual
   backend statuses (no timers).
6. Result page: 2D tab shows the generated ground-floor SVG; the 3D tab shows
   the AI presentation render when the provider is configured (otherwise the
   accepted illustration remains); MAP shows the stored plot; PDF/DXF/SVG
   download real run outputs; DWG calls the conversion endpoint (structured
   `dwg_converter_unavailable` without an installed ODA File Converter);
   share copies an expiring sanitized link; the price comes from
   `GET /api/v1/pricing/current`.
7. Refreshing the browser restores the project through the anonymous session
   cookie + stored project id.

## Honesty notes (read before demoing)

- The engine generates its validated 20 m × 30 m Compact 3BR reference plan.
  Other plot dimensions and all questionnaire/room answers are persisted and
  reported under `assumptions` / `unapplied_answers` on the run result —
  the run finishes as `completed_with_assumptions`, never pretending the
  answers shaped the geometry.
- Geo knowledge is advisory architectural-character guidance (±3 km declared
  accuracy) — no legal zoning or regulatory-compliance claim.
- All outputs carry the unconditional DEMO disclaimer of the core engine.
