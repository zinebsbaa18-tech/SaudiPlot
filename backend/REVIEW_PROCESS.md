# REVIEW_PROCESS.md

How work is produced, reviewed, and accepted in this repository.

## 1. Roles

| Agent | Role | Permissions |
|---|---|---|
| Claude Code | Lead implementer | The **only** agent that modifies files (code, docs, data) |
| Codex | Independent reviewer | **Read-only.** Produces findings; never edits, never commits |
| User | Product owner | Sole authority for scope changes (LOCKED_MVP_SCOPE.md, NOT_NOW.md) |

The Codex Review Gate is enabled for this repo: a fresh Codex review is required before a milestone is considered closed.

## 2. Milestone loop

```
1. Claude implements the milestone (scope: LOCKED_MVP_SCOPE.md only)
2. Claude runs checks: ruff + pytest (all green required)      ← pre-review baseline
3. Claude commits the milestone (one commit per milestone)
4. Codex reviews the diff (read-only)
5. Claude triages every finding (see §3)
6. Claude fixes accepted findings, re-runs ruff + pytest       ← post-fix verification
7. Claude commits review fixes (separate commit: "M<N> review fixes")
8. Gate: no unresolved CRITICAL findings → next milestone may start
```

Milestone 0 (docs only) follows the same loop; step 2/6 checks are reduced to document consistency (cross-references resolve, scope statements do not contradict each other) since there is no code yet.

## 3. Finding triage

Every Codex finding gets exactly one disposition, recorded in the milestone summary:

| Disposition | When | Action |
|---|---|---|
| `FIXED` | Correctness/defect finding inside locked scope, critical or high-confidence | Fix before closing the milestone |
| `ACCEPTED-DEFERRED` | Real but low-severity and inside scope | Tracked note; fix in a later milestone at the latest before M5 close |
| `REJECTED — out of locked scope` | Any suggestion that adds features, data, formats, styles, or integrations beyond LOCKED_MVP_SCOPE.md / onto NOT_NOW.md territory | Not implemented; rejection recorded with one-line reason |
| `REJECTED — incorrect` | Finding is factually wrong | Rejection recorded with evidence |

Severity gate: **CRITICAL findings block progress** — the next milestone must not start while any CRITICAL finding is unresolved (neither fixed nor evidenced-rejected).

## 4. Scope guard (applies to review, not just implementation)

- Codex comments are review input only. A Codex suggestion is never a scope authority.
- If a finding says "you should also support X" and X is not in LOCKED_MVP_SCOPE.md → automatic `REJECTED — out of locked scope`, even if X is a good idea. Good ideas go to NOT_NOW.md candidates in the milestone summary for the user to consider.
- If a finding reveals that LOCKED_MVP_SCOPE.md itself is ambiguous or self-contradictory, Claude does not resolve it unilaterally: the ambiguity is surfaced to the user with a recommended resolution.

## 5. Checks

| Stage | Check |
|---|---|
| Before every commit | `ruff check .` and `ruff format --check .` clean (from M1) |
| Before every commit | `pytest` green (from M1) |
| Before milestone close | Acceptance criteria of the milestone (PRD.md §6/§7) demonstrably met |
| After review fixes | Full re-run of the above — a review fix that breaks tests is not a fix |

## 6. Commit conventions

- One commit per milestone: `M<N>: <summary>`.
- Review-fix commits: `M<N> review fixes: <summary>`.
- No mixed milestone/fix commits. No commits with failing checks.

## 7. Milestone closure report

Each milestone ends with a summary to the user containing: files created/modified, checks run + results, Codex findings with dispositions, unresolved items (must be non-critical), and the plan for the next milestone.
