# Security Policy

This is a **private, proprietary** repository. Do not make it public, fork it
publicly, or redistribute any part of it.

## Reporting

Report suspected vulnerabilities or data exposure privately to the repository
owner. Do not open public issues for security matters.

## Secrets

- No API keys, tokens, or passwords are committed to this repository, and none
  may ever be. `.env` files are gitignored; only `.env.example` templates are
  tracked.
- The Gemini API key is **server-side only** (`backend/.env`). The frontend
  must never receive or embed an AI provider key.
- CI workflows contain no credentials and must stay that way; use GitHub
  Actions secrets if a workflow ever needs one.

## Personal data

- Deed documents, extracted deed fields, owner details, and coordinates are
  personal data. They live only in the local runtime database and storage root
  (both gitignored) and are never committed.
- Share links are sanitized: no coordinates, deed data, owner names, session
  identifiers, or filesystem paths are exposed.
- The knowledge package under `knowledge/geo/` was scanned before export; see
  `docs/EXPORT_SECURITY_REPORT.md`.

## Hardening posture (backend)

- Anonymous sessions: only a SHA-256 token hash is stored; cookies are
  HttpOnly with SameSite; production refuses insecure cookie settings.
- Origin/Referer CSRF guard on state-changing endpoints; CORS uses an explicit
  origin allow-list (never `*`).
- Uploads are size- and MIME-restricted, stored under server-generated names;
  path traversal is rejected at the storage layer.
- Stable error envelope; unexpected errors never leak stack traces to clients.
