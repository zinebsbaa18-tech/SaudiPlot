# Web Backend Scope

- **Status:** Active for branch `web-backend-foundation`.
- **Governs:** milestones W0 (frozen contract + architecture) and W1 (FastAPI
  project/session/persistence foundation). Later milestones get their own scope
  entries here before implementation starts.
- **Companions:** ADR-WEB-001 (architecture decision),
  FROZEN_FRONTEND_CONTRACT.md (the frozen UI surface).

## Principles (binding, from ADR-WEB-001)

1. The existing frontend journey is **frozen** — no visual/structural change to any
   screen, question, label, order, button, loading state, error-state location, or
   the result-page layout.
2. The core (`saudi_plot_design`) remains **deterministic and offline**; it gains no
   web, database, HTTP, session, upload, AI-provider, storage, or worker code.
3. The web API (`saudi_plot_api`) **wraps** the core; dependency direction is
   `saudi_plot_api → saudi_plot_design`, never the reverse.
4. User choices must **never be silently ignored** — every collected answer is
   honored or explicitly refused.
5. Unsupported design briefs return a **structured refusal** (the standard error
   envelope with a machine-readable code), never a degraded or fabricated result.
6. AI presentation renders are **not engineering geometry**; plans/elevations/
   PDF/DXF come only from the deterministic core.
7. **API keys remain server-side** — never shipped to or read by the browser.
8. **No legal or regulatory claim is made from demo data**; the unconditional DEMO
   disclaimer applies to everything the web surface exposes.

## W0 — Frozen frontend contract and architecture decision (this milestone)

- Record ADR-WEB-001 and FROZEN_FRONTEND_CONTRACT.md.
- Treat the frontend repository as read-only; document, don't touch.

## W1 — FastAPI project/session/persistence foundation (this milestone)

In scope:

- `src/saudi_plot_api/` package (config, database, models, schemas, dependencies,
  routes, services) behind an optional `[web]` dependency group
  (fastapi, uvicorn, sqlalchemy, alembic, pydantic-settings, python-multipart;
  httpx for API tests).
- SQLite for local development; the repository/service layer written so PostgreSQL
  can be introduced later by changing the database URL, not the code shape.
- Alembic setup + first migration: `anonymous_sessions` (id, token_hash,
  created_at, expires_at, last_seen_at, status) and `projects` (id, session_id,
  status, created_at, updated_at, current_step, schema_version). **No personal deed
  fields yet.**
- Anonymous sessions (the frozen frontend has no login page): cryptographically
  random tokens, only a token hash stored, Secure/HttpOnly/SameSite cookie with a
  local-development Secure=false override, expiration + last-seen update.
  Endpoints: `POST /api/v1/sessions`, `GET /api/v1/sessions/current`.
- Projects belonging to the current session: `POST /api/v1/projects`,
  `GET /api/v1/projects/{project_id}`, `PATCH /api/v1/projects/{project_id}`.
  Cross-session access returns **404** (no existence leak).
- Health: `GET /health/live`, `GET /health/ready` (ready verifies database
  connectivity).
- Stable error envelope on every error:

  ```json
  {
    "error": {"code": "machine_readable_code", "message": "safe user-facing message", "details": {}},
    "request_id": "..."
  }
  ```

  No stack traces, SQL, file paths, or secrets in responses.
- Configuration via pydantic-settings + `.env.example` only (no secrets):
  environment, database URL, cookie name, cookie secure setting, session TTL,
  storage root placeholder, CORS origins. CORS is an explicit origin list — never
  `*` while credentials are enabled.
- Focused API tests; the existing suite, Ruff, and the CLI sample must stay green;
  the core stays importable without web dependencies.

## Explicitly out of scope (not in W0/W1)

- Gemini integration of any kind (the deed OCR stays client-side in the frozen
  frontend until a dedicated milestone moves it server-side).
- Deed OCR endpoints or storage of deed content/personal fields.
- Nano Banana / any AI render integration.
- M8 or any core-engine milestone; general room-program generation.
- Planner modifications — and **no claim that frontend answers already affect the
  generated layout** (they do not; wiring comes later and will say so honestly).
- Retrieval/ranking/adaptation over the template library.
- Production cloud deployment (containers, managed Postgres, TLS termination,
  hosting). W1 targets local development only.
