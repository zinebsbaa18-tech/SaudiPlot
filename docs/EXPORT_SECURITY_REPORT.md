# Export Security Report

Scan of the complete monorepo performed 2026-07-20, before the content
commits were pushed anywhere. Scope: every git-tracked file (binary knowledge
databases scanned separately at the cell level). Secret **values** are never
reproduced in this report.

## Method

`git grep` pattern scan over all tracked files, plus a Python cell-level scan
of every table of `knowledge/geo/07_database/sbc_rules.sqlite`, plus targeted
personal-data term searches (Arabic and English).

| Category | Pattern family | Result |
|---|---|---|
| Google/Gemini API keys | `AIza…` (30+ chars) | **0 hits** |
| OpenAI-style keys | `sk-…` (20+ chars) | **0 hits** |
| GitHub tokens | `ghp_…`, `github_pat_…` | **0 hits** |
| Slack tokens | `xox[abprs]-` | **0 hits** |
| AWS access keys | `AKIA…` | **0 hits** |
| Private keys | `BEGIN … PRIVATE KEY` | **0 hits** |
| Authorization headers | `Authorization: Bearer/Basic …` | **0 hits** |
| Assigned secrets | `password/secret/api_key/token = "…"` | **0 hits** |
| User-profile paths | `C:\Users`, `/Users/`, `/home/` | **0 hits** |
| Personal email addresses | common providers | **0 hits** |
| Machine-local absolute paths | `C:\AI`, `C:/AI` | **1 hit** — see finding 3 |
| Deed numbers / owner names | `رقم الصك`, `اسم المالك`, `deed_number`, `owner_name` | **2 hits** — see finding 4 |
| Geo sqlite cells (all tables) | path-like / key-like strings | **0 suspicious cells** |

`.env` files: none tracked anywhere in the repository — verified. Only
`.env.example` templates (no secrets) are committed.

## Findings and dispositions

1. **`backend/.env.example` absolute geo path** — the imported template
   pointed `SPD_GEO_KNOWLEDGE_DB` at an absolute source-machine path.
   **Removed in the monorepo** (repointed to
   `../knowledge/geo/07_database/sbc_rules.sqlite`). Source repo untouched.
2. **`frontend/.claude/launch.json`** — local agent-tool launch config
   (harmless content, excluded category). **Removed from the monorepo.**
3. **`backend/docs/LOCAL_DEMO_RUNBOOK.md`** references the pre-monorepo
   folder layout (`C:\AI\saudi-plot-design`, `C:\AI\Saudi-Plot-Frontend-main`,
   `C:/AI/sbc_geo_knowledge`). Reviewed: machine-local folder names only — no
   username, no personal data, no secrets. **Accepted as-is** (imported
   documentation of the standalone layout); `docs/LOCAL_DEMO_GUIDE.md` is the
   canonical guide for this repository.
4. **Deed/owner term hits are labels, not data** —
   `frontend/src/Pages/ConfirmData/ConfirmData.jsx` contains the UI field
   label «رقم الصك» (deed number), and `backend/tests/test_web_api.py` uses
   `deed_number` as a synthetic fixture field name. **No real deed numbers,
   owner names, or customer addresses exist anywhere in the export.**

## Personal / private data statement

- No uploaded documents, runtime databases, storage roots, or generated
  outputs are tracked (verified against `.gitignore`; `backend/var/`,
  `storage/`, `out/`, `uploads/`, `private_cases/` are all excluded).
- The geo knowledge package contains only published-guide-derived zones,
  rules, and manifests; the cell-level sqlite scan found no paths, keys, or
  personal identifiers. Raw source archives and extracted source-document
  imagery were deliberately not exported.
- Sample/test coordinates (e.g. `26.42, 50.10`) are demo reference values,
  not customer locations.

## Conclusion

**PASS.** No secrets, tokens, private keys, personal emails, deed numbers,
owner names, customer addresses, or user-profile paths in the exported
content. The two removable findings were removed in the monorepo only; the
source repositories were not modified.
