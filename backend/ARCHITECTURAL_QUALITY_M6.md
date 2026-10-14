# M6 — Architectural Quality Engine

## M6.1 purpose and boundary

M6.1 establishes a deterministic architectural-quality baseline for the existing
Compact 3BR concept. It measures evidence already present in the canonical plan,
reports weaknesses, and recommends priorities for later revision. It does not
change planner geometry, silently apply recommendations, search for alternatives,
or claim that a concept is professionally suitable.

The engine is a concept-design diagnostic. It is not Saudi Building Code or
municipal compliance checking, a permit review, cultural acceptance, daylight or
MEP approval, or licensed architectural approval. The criteria carry explicit
`demo` provenance and are synthetic heuristics rather than official Saudi data.
The repository's unconditional DEMO disclaimer appears in every M6.1 artifact,
the run record, manifest metadata, and CLI output.

## Architecture

`src/saudi_plot_design/quality/` is isolated from plan generation:

- `models.py` defines frozen criteria, finding, category-score, room-assessment,
  plan-metric, and `ArchitecturalQualityAssessment` schemas.
- `criteria.py` defines and validates the one versioned profile,
  `saudi_villa_concept_v1` v1.2.0.
- `evaluator.py` builds internal-door, real-external-door reachability,
  shared-wall, and combined topology evidence from the canonical plan,
  evaluates the stable rule sequence, and calculates scores. Assessment v1.3.0
  uses the unchanged criteria profile v1.2.0.
- `reporting.py` writes the complete JSON assessment and human-readable Markdown.
- `overlay.py` renders a technical SVG plan overlay from the canonical rectangles,
  zones, and assessment evidence.

The evaluator consumes a `Concept` and its `BuildableEnvelope`. It does not infer
rooms, walls, openings, or paths that are absent. The export pipeline evaluates
once after the existing binding gate succeeds, writes the three quality artifacts
in the same staging directory as PDF/DXF, hashes them, writes `run.json`, and
publishes the manifest last through the existing rollback transaction.

## Categories and stable rules

The 53 checks are ordered by category and rule ID. Each category's contributions
sum to 100%.

| Category | Overall weight | Rules |
|---|---:|---|
| Geometric validity | 15% | `GEO-001`–`GEO-007`: overlap, envelope containment, finite/positive geometry, width, aspect, boundaries, opening consistency |
| Program completeness | 10% | `PRO-001`–`PRO-008`: bedrooms, primary bedroom, bathrooms, family living, majlis, kitchen, corridor, entry |
| Room usability | 18% | `USE-001`–`USE-005`: area, clear dimension, proportion, furniture support, door-swing support |
| Adjacency quality | 12% | `ADJ-001`–`ADJ-007`: kitchen relationship, guest WC, bedroom bathrooms, primary privacy depth, public/private doors, service routes, topology coverage |
| Privacy zoning | 12% | `PRI-001`–`PRI-005`: zone coverage, public/bedroom doors, guest route, discouraged transitions, sightline support |
| Circulation | 14% | `CIR-001`–`CIR-007`: connection, reachability, area ratio, isolation, width, transitions, route efficiency |
| Daylight/external-access proxy | 7% | `DAY-001`–`DAY-004`: external wall, external opening, internal habitable rooms, daylight support |
| Wet-area organization | 5% | `WET-001`–`WET-004`: shared-wall clusters, fragmentation, topology distance, plumbing support |
| Saudi-villa functional character | 7% | `SAU-001`–`SAU-006`: zone functions, majlis, guest WC, multiple entrances, guest/family routes, approval boundary |

Every result is a `QualityFinding` with its rule/category/severity/status, affected
object IDs, explanation, evidence, measured and expected values, recommendation,
confidence, and source method. Recommendations are reporting only.

## Criteria configuration

The profile explicitly stores:

- room-type minimum areas, minimum clear dimensions, and maximum aspect ratios;
- preferred functional adjacencies and discouraged zone transitions;
- circulation, route, wet-cluster, and topology-distance thresholds;
- units and stable rule contributions;
- category weights, status/severity contribution factors, coverage thresholds,
  critical-category floors, status constraints, score cap, and rounding;
- demo provenance, non-official statement, and limitations.

Profile validation rejects missing/non-demo provenance, duplicate or unstable
rule IDs, missing categories, category weights not totaling 100%, and within-
category contributions not totaling 100%.

## Scoring and evidence coverage

For each evaluated rule, its configured contribution is multiplied by a factor:

| Result | Blocking | Major | Moderate | Advisory |
|---|---:|---:|---:|---:|
| Pass | 1.00 | 1.00 | 1.00 | 1.00 |
| Warning | 0.25 | 0.55 | 0.70 | 0.90 |
| Fail | 0.00 | 0.20 | 0.40 | 0.75 |

`not_evaluable` weight is excluded from the raw-score denominator and reduces
published evidence coverage; it never becomes a pass. The transparent raw score
is the weighted average of evaluated rules. The coverage-adjusted score is the
raw score multiplied by evaluated-weight coverage. This simple deterministic
adjustment is not a statistical confidence model. The overall score equals that
coverage-adjusted score except when the blocking cap applies.

A category is not rated below 50% weighted evidence. Category coverage is
reported as `complete_evidence` only at 100%, `partial_evidence` from 50% to below
100%, and `insufficient_evidence` below 50%. A partial category can retain its
evaluated-subset score, but its category status cannot be strong. The overall
indicator is not rated below 65% evidence coverage or when geometry, program,
room usability, privacy, circulation, or Saudi-villa function is below 60%
coverage. Strong status additionally requires at least 90% overall evidence and
80% evidence in every critical category.

The versioned internal floors for room usability, privacy, circulation, and
Saudi-villa functional character are 80 for strong, 65 for workable, and 45 for
substantial revision. These are synthetic revision heuristics, not official
minimums. A score below 80 caps status at workable; below 65 caps it at
substantial revision; and below 45 caps it at unsuitable. Any unresolved blocking
finding caps the numeric score at 49.00 and status at unsuitable. Any unresolved
major finding prevents strong status. A failed major rule in a critical
category caps status at substantial revision. Advisory findings retain their
smaller contribution factors and do not independently constrain status; warnings
remain warnings.

Internal indicator labels are:

- 85–100: `strong_concept_candidate`
- 70–84.99: `workable_with_targeted_revisions`
- 50–69.99: `substantial_architectural_revision_required`
- below 50: `unsuitable_concept_baseline`
- insufficient coverage: `not_rated_insufficient_evidence`

The labels are revision indicators, never approvals.

## Outputs and CLI integration

The existing `spd generate` command and arguments are unchanged. Every successful
generation still writes the PDF, DXF, `run.json`, and `export_manifest.json`, and
now also writes:

- `architectural_quality_report.json` — the complete typed assessment;
- `architectural_quality_summary.md` — category scores, priority findings, room
  table, adjacency/privacy/circulation evidence, unsupported checks, priorities,
  provenance, limitations, and disclaimer;
- `architectural_quality_overlay.svg` — a deterministic engineering overlay with
  room IDs/names, zones, warning/failure outlines, external-wall/opening markers,
  and material plan diagnostics.

The manifest records relative paths, sizes, SHA-256 hashes, assessment/profile
versions, raw/adjusted/overall scores, evidence coverage, status constraints, and
blocking/major counts. `run.json` preserves schema
version 1 and adds the backward-compatible `architectural_quality` section plus
quality artifact paths and hashes. The CLI prints raw, adjusted, and overall
internal scores, evidence coverage, constraints, finding counts, and report paths.
A quality target miss does not stop generation;
the existing geometric/facade binding gate still determines export validity.

## Unsupported conclusions and limitations

M6.1 deliberately reports these checks as `not_evaluable`:

- furniture layout and furniture clearances;
- door swings and maneuvering clearances;
- visual privacy and sightlines;
- daylight compliance;
- plumbing/MEP performance;
- cultural, regulatory, permit, or professional approval.

External-wall and opening checks are proxies only. Door-graph distance is not
walking distance. Shared-wall wet clustering is not pipe routing. Zone tags and
topology cannot establish acoustic or social privacy. Rectangular room dimensions
do not prove furniture fit. These limitations remain visible even when all
supported checks pass.

## Reference Compact 3BR baseline

The unchanged documented 20 m × 30 m Riyadh/Najdi reference run produces under
profile v1.2.0:

- raw weighted score: **88.83/100**;
- coverage-adjusted and overall score: **81.46/100**;
- status: **substantial architectural revision required**;
- evidence coverage: **91.70%**;
- blocking findings: **0**;
- non-passing major findings: **4**;
- not-evaluable checks: **6**.

| Category | Score | Coverage |
|---|---:|---:|
| Geometric validity | 100.00 | 100% |
| Program completeness | 100.00 | 100% |
| Room usability | 51.47 | 85% |
| Adjacency quality | 94.60 | 100% |
| Privacy zoning | 100.00 | 85% |
| Circulation | 95.50 | 100% |
| Daylight/external-access proxy | 100.00 | 70% |
| Wet-area organization | 75.00 | 80% |
| Saudi-villa functional character | 91.50 | 90% |

Two deterministic constraints apply: room usability at 51.47 is below the 65
workable floor, limiting status to substantial revision, and four unresolved
major findings exceed the zero-finding maximum for strong status. No blocking or
coverage constraint applies. Six material conclusions remain unsupported, and
presentation quality is outside this evaluator. The main detected weaknesses are
the corridor's excessive aspect ratio, entry/kitchen/
master-bath area heuristics, maid-room clear dimension, service access through
family/dining space, circulation-area ratio, three wet-room clusters and their
separation, and direct sharing between majlis circulation and the main family
entry.

## M6.2 deterministic layout improvement

M6.2 uses the approved M6.1 rules, numeric scoring, findings, and geometry as a
baseline-relative regression guard and candidate evaluator. Its closeout status
policy is calibrated as documented below. It is a bounded optimizer for the one
authored Compact 3BR skeleton, not arbitrary generative architecture. The
default `--layout-mode baseline` preserves the original layout. Explicit
`--layout-mode optimized` evaluates at most 32 canonical transformation
combinations with a maximum depth of five; it uses no randomization, LLM,
external API, or interactive choice.

The stable ordered transformation set is:

1. `M62-T01-front-room-rebalance` moves adjacent front-band partitions to
   improve entry and kitchen clear dimensions;
2. `M62-T02-wet-service-rebalance` resizes the master-bath/laundry and
   shared-bath/maid/bedroom-2 bands while preserving their combined boundaries;
3. `M62-T03-corridor-reproportion` widens the corridor and resizes its adjacent
   rooms to remove the excessive corridor aspect ratio;
4. `M62-T04-direct-service-access` adds untagged kitchen and maid service doors
   only on real, non-street external host walls and repositions the maid window
   on its same host wall;
5. `M62-T05-separate-guest-family-route` removes the internal majlis-to-entry
   connection so the two existing exterior entrances form separate routes.

Each candidate is rebuilt from canonical room rectangles. Room width, length,
and area are derived from those rectangles. The engine proves footprint
containment, non-overlap, exact room-union tiling, and canonical internal/external
wall boundaries before it rehosts an opening. An opening is accepted only on a
wall matching its room endpoints and, for external openings, its authored world
side. The required 14-room program and all existing 15 planner checks must still
pass. Invalid and duplicate attempts are retained as audit records but never
ranked or exported. The baseline object is immutable.

Selection is lexicographic: eligibility and critical-floor compliance precede
major-finding counts; major failures precede major warnings; room usability,
privacy, Saudi-villa function, and circulation precede the effective score;
baseline-relative warning regressions carry an explicit severity-ordered cost;
then transformation count and candidate ID break ties. Every M6.1 rule status is
compared with baseline. New or worsened failures, loss of previously evaluable
evidence, blocking warnings/failures, and worsened critical-category floor states
are disallowed. Non-blocking warning trade-offs are permitted only when recorded
in the candidate and final report.
The M6.2 search did not change rule criteria, severities, denominators, or
blocking-score behavior. The M6.2 closeout calibration changes only the
strong-status policy: profile and assessment v1.2.0 require zero unresolved major
findings for a strong status; numeric scores and finding contributions are unchanged.

Optimized runs add these transactionally published artifacts:

- `layout_optimization_report.json` — versioned search, candidate, rejection,
  ranking, reversible transformation, full baseline/selected assessment,
  room/adjacency/route/zone-transition comparison, and limitations;
- `layout_candidate_comparison.csv` — stable candidate-level geometry and score
  comparison;
- `layout_optimization_overlay.svg` — dashed baseline boundaries, selected and
  moved boundaries, changed doors, room labels, and finding comparison.

All three carry the unconditional DEMO disclaimer and the heuristic/non-approval
notice. `run.json` includes their portable paths and SHA-256 hashes; the
schema-version-2 optimized manifest includes those paths and hashes plus file
sizes. Baseline exports retain the original file set and schema-version-1
manifest.

For the 20 m × 30 m reference, the selected five-operation candidate improves
room usability from 51.47 to 100.00 and effective score from 81.46 to 88.83. Its
status improves from substantial revision to workable with targeted revisions,
not strong, because it retains one unresolved major finding while preserving zero
blocking findings. It resolves `USE-001`, `USE-002`, `USE-003`, `ADJ-006`, and
`SAU-005`. It introduces an explicitly reported `ADJ-002` major warning and
`SAU-003` moderate warning because the separated majlis route reaches the guest
WC through the exterior/main entry. Wet clustering remains 75.00. Corridor
aspect ratio improves, but circulation area ratio increases and `CIR-003`
remains a warning. These are honest bounded-topology trade-offs, not approval or
proof of operational suitability.

## M6.2.1 entrance and route semantics hardening

This section supersedes the M6.2 route-selection result above while preserving
its historical record. Assessment v1.3.0 removes the free shared `exterior`
routing node. `EXTERIOR` remains a canonical endpoint on real external doors,
but internal circulation uses only room-to-room doors. Any external alternative
must identify a real exit door and re-entry door, insert an explicit
`external_path`, add two exterior-door crossings and a non-zero traversal cost,
state its route policy, and remain distinct from internal adjacency.

The deterministic entrance inventory supports `family_main`, `guest_majlis`,
`service`, `secondary`, and `unknown`. Each item retains door ID, connected room,
host wall, authored classification method, confidence, evidence, and review
status. Only authored real doors on valid external host walls receive supported
intent. External-wall contact does not create an entrance, and unknown intent
never supplies route-separation credit.

Guest and guest-WC policies disallow exit/re-entry as preferred access and
discourage family/private intermediate zones. Family routes start at the
classified family entrance and cannot borrow guest or service entrances. A
service-to-service external pair may be reported as a supported but reviewable
alternative; it cannot replace or automatically outrank internal kitchen-to-maid
circulation. External service routes through bedrooms or majlis are disallowed.

T04 now accurately describes two classified exterior service doors as a
reviewable external alternative, not direct internal service access. T05 removes
the majlis-to-entry door only when distinct authored family and guest exterior
doors exist. It separates entrance paths but does not prove guest-WC circulation;
absent entrance evidence rejects the transformation.

Optimizer schema v2 / engine v1.1.0 adds explicit penalties for disallowed
external routes, external guest-WC detours, unknown entrances used as dedicated
entrances, unnecessary exit/re-entry, selected external alternatives, and extra
external-route cost. These general penalties precede category-score tie-breakers;
no candidate ID is hard-coded.

For the 20 m x 30 m synthetic reference, the previous M6.2 selection
`candidate-031` remains geometrically valid but is no longer selection-eligible.
Its guest-WC route is `majlis -> d_majlis_ext -> external_path -> d_main -> entry
-> d_guest_wc -> guest_wc`, with one internal door, two exterior-door crossings,
two traversal steps, total cost 5, and total route penalty 174. `ADJ-002`,
`PRI-003`, `SAU-003`, and `SAU-005` fail, so the regression guard rejects it.

The empirical new selection is `candidate-016` using T01, T02, and T03. It has
raw score **96.93**, effective score **88.89**, status
`workable_with_targeted_revisions`, zero blocking findings, and zero external
route penalty. Its remaining non-passing major findings are `ADJ-006` and
`SAU-005`: internal service circulation still crosses dining, and the guest-WC
route still shares entry circulation with the family route. Wet-area score
remains 75.00 and `CIR-003` remains a moderate warning. These are deterministic
revision diagnostics, not cultural, regulatory, permit, or professional
approval.

## M6.3 professional 2D architectural sheet presentation

M6.3 adds a deterministic A3 presentation layer without changing M6.1 scoring
or M6.2.1 selection. The engine consumes the frozen selected concept, facade,
assessment, and route audit; it does not mutate geometry, recalculate findings,
change `not_evaluable` denominators, alter blocking-score behavior, or rerank
candidates.

For the optimized synthetic reference, every sheet is bound to
`candidate-016` and its source geometry fingerprint. A-001 and A-101 report the
frozen effective score **88.89**, `workable_with_targeted_revisions` status,
91.7% evidence coverage, zero blocking findings, and the two remaining active
major findings `ADJ-006` and `SAU-005`. A-901 preserves those findings and their
evidence, category scores/coverage, moderate findings, unsupported checks, and
M6.2.1 route summaries. Clean A-101 removes finding markers but continues to
state the major limitations and non-approval status.

The sheet engine does not promote newly drawn schematic door swings or concept
furniture into evaluable quality evidence. Door handing/operation remains
unauthored and is scheduled as `N/A`; furniture-layout usability remains
`not_evaluable`. Front-facade window sill/head values come from the DEMO style
pack, while non-front schedule values are explicitly marked as nominal plan
data with facade development unavailable.

The CLI default `--sheet-set concept` adds the clean four-sheet PDF, individual
SVGs, sheet index, annotation-collision report, and sheet manifest. `review`
adds the five-sheet review PDF and A-901; `all` writes both; `none` preserves the
legacy library export surface. The top-level run and export manifests include
portable paths, SHA-256 hashes, file sizes, selected candidate, source geometry
fingerprint, page-set mode, and sheet validation status. Full architecture,
annotation, schedule, validation, determinism, and limitation details are in
`PROFESSIONAL_SHEETS_M6_3.md`.
