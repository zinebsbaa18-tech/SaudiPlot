# ADR-WEB-001 — Frozen Frontend and Web Adapter Architecture

- **Status:** Accepted
- **Date:** 2026-07-20
- **Deciders:** Product owner (accepted the frontend); Claude Code (implementer)
- **Scope:** Web milestones W0+ on branch `web-backend-foundation`. This ADR does not
  change LOCKED_MVP_SCOPE.md, NOT_NOW.md, or any CLI behavior.

## Context

The project has two accepted, working artifacts:

1. **The deterministic offline core** — the `saudi_plot_design` Python package
   (`src/saudi_plot_design/`). A CLI (`spd generate`) that turns one rectangular plot
   into a setback-aware plan skeleton with a Saudi-character front elevation, exported
   as PDF + layered DXF. Its scope is locked (LOCKED_MVP_SCOPE.md), its reference data
   is demo-provenance only (GEOSPATIAL_DATA_PROVENANCE.md), and its outputs are
   deterministic and reproducible.

2. **The accepted React frontend** — a separate Vite + React 19 repository
   (`Saudi-Plot-Frontend-main`), an Arabic-first (RTL, i18n ar/en) guided journey:
   Landing → deed Upload → ConfirmData → six wizard Questions → RoomCatalog →
   Generating → Result3D. The product owner has accepted this journey as-is.

The next phase connects the two with a web backend. Two decisions are needed before
any backend code exists: what happens to the frontend, and where web code lives.

## Decision 1 — The frontend journey is frozen

The accepted frontend is **frozen** in its:

- visual design, routes, and pages
- questions, labels, wording, and their order
- buttons and their placement
- loading states (Upload analyze overlay; Generating step list)
- error-state locations (inline field errors; the `/manual-entry` error banner)
- result-page layout (Result3D with its 2D/3D/MAP toggle and sidebar)

No screen or prompt is redesigned, removed, added, reordered, renamed, or visually
altered. Allowed changes are strictly non-visual: behavioral wiring (calling the real
API instead of mocks), data fetching, persistence, validation, accessibility fixes,
and non-visual bug fixes — and only when they preserve the accepted UI exactly.
The authoritative description of the frozen surface is
[FROZEN_FRONTEND_CONTRACT.md](FROZEN_FRONTEND_CONTRACT.md).

During W0/W1 the frontend repository is treated as **read-only**: it was inspected
only to document the contract; no frontend file is copied, moved, edited, staged, or
committed from this repository.

## Decision 2 — The core stays deterministic and offline; the web API wraps it

The existing `saudi_plot_design` package remains the deterministic offline core.
It gains **no** knowledge of the web: no FastAPI, no database code, no HTTP models,
no sessions, no file uploads, no Gemini/Nano Banana calls, no storage backends, no
worker logic inside core engine modules.

All web concerns live in a separate adapter/application package:

```
src/saudi_plot_api/
```

The dependency direction is one-way and non-negotiable:

```
saudi_plot_api  ──▶  saudi_plot_design
```

`saudi_plot_design` never imports from `saudi_plot_api`. The core must remain
installable and fully functional (CLI included) without any web dependency
installed; web dependencies are an optional extra (`[web]`).

## Consequences and binding rules

1. **The existing frontend journey is frozen** (Decision 1). Any change request that
   would alter a screen, question, label, order, button, loading state, error-state
   location, or the result-page layout requires an explicit product-owner decision
   first — it is out of scope for implementation work.
2. **The core remains deterministic and offline.** Same inputs produce the same
   outputs; nothing in the core performs network I/O or depends on request context.
3. **The web API wraps the core.** It adapts HTTP/session/persistence concerns onto
   core calls; it never re-implements or forks core logic.
4. **User choices must never be silently ignored.** Every answer the frontend
   collects is either honored by the backend, or the backend returns an explicit,
   visible signal that it cannot be honored. Dropping or overriding an answer
   without telling the user is a defect. Until real wiring exists, no claim is made
   that frontend answers affect the generated layout (see WEB_BACKEND_SCOPE.md).
5. **Unsupported design briefs return a structured refusal.** When a requested brief
   is outside what the deterministic core supports (e.g. plot shape, size, or program
   beyond the locked engine), the API responds with a machine-readable refusal in the
   standard error envelope — never a silently degraded or fabricated result.
6. **AI presentation renders are not engineering geometry.** Any future AI-generated
   imagery (e.g. Nano Banana renders) is presentation only. Engineering geometry
   (plans, elevations, PDF/DXF) comes exclusively from the deterministic core, and
   the two must never be conflated in UI or API responses.
7. **API keys remain server-side.** No provider key (Gemini or otherwise) is ever
   shipped to, embedded in, or read by the browser. The accepted frontend currently
   calls Gemini directly with a `VITE_GEMINI_API_KEY`; that is a known pre-backend
   state that must be replaced by a server-side proxy in a later milestone — never
   reproduced in new code.
8. **No legal or regulatory claim is made from demo data.** All shipped reference
   data is `demo` provenance; loaders reject `verified` claims; the unconditional
   DEMO disclaimer applies to every output the web surface exposes, exactly as it
   does for the CLI (GEOSPATIAL_DATA_PROVENANCE.md).

## Alternatives considered

- **Embed FastAPI in `saudi_plot_design`** — rejected: couples the locked core to
  web dependencies, breaks offline installs, and violates the locked-scope rule that
  the core stays a deterministic CLI engine.
- **Redesign the frontend around the backend's data model** — rejected: the frontend
  is the accepted product surface; the backend adapts to it, not the reverse.
