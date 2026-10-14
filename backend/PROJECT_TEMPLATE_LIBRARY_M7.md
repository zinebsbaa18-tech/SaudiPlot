# M7.1 — Approved Project and Template Library Foundation

## Purpose and boundary

M7.1 provides a deterministic, local, file-based library for source projects,
M6A architectural cases, reviewed residential-villa candidates, approved test
templates, architectural references, stress tests, rejected cases, and archived
versions. It prepares trusted, inspectable data for a future user-approved
retrieval milestone.

M7.1 does **not** retrieve, rank, compare, select, adapt, or generate from a
stored template. It contains no embeddings, vector database, similarity score,
learned weights, plot adaptation, IFC export, Revit integration, rendering,
GUI, web service, or server.

## Architecture

`src/saudi_plot_design/library/` contains:

- `models.py`: frozen, versioned source-bundle, project-package, feature,
  registry, active-index, validation, and manifest schemas;
- `source_bundle.py`: external asset cataloguing, format classification,
  SHA-256 hashing, confidential display-name handling, and M6A source-hash
  references;
- `feature_extraction.py`: evidence-only feature extraction from the existing
  M6A canonical `ArchitecturalDesignCase` and optional M6 quality assessment;
- `fingerprints.py`: canonical content fingerprints and review bindings;
- `validation.py`: package, rights, privacy, eligibility, approval, feature,
  active-index, and no-retrieval checks;
- `storage.py`: immutable version writes, deterministic JSON, local loading,
  and library-manifest hash/size verification;
- `registry.py`: deterministic registry, current-version derivation, active
  template index, validation report, summary, and manifest;
- `commands.py`: lifecycle operations and `spd library` CLI dispatch.

Every command requires an explicit `--library-root`. There is no implicit real
library location. Use a location outside the repository or a directory below
the repository's already-gitignored `out/` tree. Tests use temporary roots.

## Case role, lifecycle, review, and eligibility

These are independent fields:

- Roles: `source_project`, `ingestion_stress_test`,
  `architectural_reference`, `residential_villa_candidate`,
  `architect_reviewed_reference`, `approved_template`, `rejected`, `archived`,
  and `excluded`.
- Lifecycle states: `ingested`, `requires_review`, `corrected`,
  `architect_reviewed`, `approved`, `rejected`, `archived`, `superseded`, and
  `excluded`.
- Review states: `not_reviewed`, `requires_review`, `architect_reviewed`,
  `approved`, `rejected`, and `revoked`.
- Template eligibility is the existing M6A objective policy result and ordered
  reason list. It is recomputed from the canonical M6A case at import; stored
  M6A flags and descriptive metadata are not trusted to bypass the policy.

An active template must simultaneously be the current immutable version, have
role `approved_template`, lifecycle and review state `approved`, carry an
explicit approval decision bound to its current review fingerprint, remain an
eligible Saudi residential villa, pass validation, retain a valid feature
package, have ingestion/internal-review/template-use rights, have no template
revocation, and satisfy its confidentiality gate. No import is automatically
approved.

## Source bundles

Source-bundle manifest schema v1 catalogs IFC, RVT, DWG, PDF, images,
specifications, metadata, and review decisions. Every asset records a stable
asset ID, safe display name, format, role, parser status, size when safely
available, SHA-256 fingerprint, confidentiality and rights status, original
path policy, optional derived references, and warnings.

- Generic IFC assets are fingerprinted and catalogued. Existing M6A IFC4
  parsing is reused through `library import-case` after M6A has produced its
  safe artifact set.
- Native RVT/DWG, PDF, image, specification, and other unsupported content is
  `catalogued_not_parsed` in M7.1.
- Source files stay external and are never copied into the library.
- Confidential filenames are replaced with a digest-derived display name.
- Absolute source paths and `private_cases/` paths are rejected from shareable
  models and validation scans.
- M6A safe artifacts do not disclose source IFC size; that field remains null
  with an explicit validation warning rather than being fabricated.

Ingestion permission, internal-review permission, and revocable template-use
permission are separate strict booleans with a recorded rights basis.

## Canonical project package

`ProjectCasePackage` schema v1 records case/version identity, role, lifecycle,
review state, project type and location metadata, architectural character,
confidentiality, rights, source hashes, source-bundle hash, canonical-case
hash, M6A canonical reference, review binding, eligibility and reasons,
validation and quality summaries, provenance, feature reference, controlled
creation metadata, superseded-version reference, and full package fingerprint.

M6A import verifies every `case_manifest.json` hash before loading
`architectural_case.json`. The package references that safe canonical artifact
by type, schema, digest, and M6A review binding. It does not copy the canonical
values into a second competing model and does not copy the IFC source.

## Reusable features

Feature schema v1 uses stable feature IDs, explicit units, evidence source,
review status, and deterministic ordering. It covers:

1. site and massing;
2. program;
3. room geometry;
4. zoning;
5. topology;
6. entrances;
7. facade and openings;
8. quality.

Missing M6A evidence stays `source_missing`. In particular, M6A has no space
footprints, plot geometry, facade orientation, or developed elevation
geometry, so room clear dimensions, aspect ratios, perimeters, footprint,
buildable envelope, facade counts, and front-elevation proportions are not
inferred. External-wall contact, real opening relationships, actual-door
entrance evidence, source quantities, classifications, adjacency, door
connectivity, routes, wet groups, and descriptive metrics are retained where
available. M6 quality scores and findings are stored only when an actual M6
assessment is supplied; otherwise the quality feature says `not_evaluated`.

## Versioning and review binding

Case versions are immutable. A target version directory is written once. An
identical replay is idempotent; different bytes at the same case/version are a
conflict and are rejected. Source, metadata, canonical-artifact, correction,
rights, review, approval, rejection, revocation, and archive changes require a
new version. The prior version remains present and traceable.

Replaying a byte-identical operation is idempotent: it reports
`idempotent`, and healthy root artifacts stay byte-untouched. A retry
completes an interrupted root rebuild only when the replay is at least as new
as every trustworthy controlled event (stored version creation metadata and
self-consistent surviving roots); any other stale or conflicting root state
is refused with explicit `rebuild-index --generated-at` guidance instead of
guessing controlled metadata.

`supersedes_case_version` forms the version chain. Registry derivation marks
non-current versions effectively `superseded`, even though their immutable
package bytes are not rewritten. Only a current version can be active.

The review binding covers source fingerprints, source bundle, canonical case,
project metadata, rights, confidentiality, objective eligibility, validation,
quality, features, and provenance. Role/lifecycle/review fields are excluded so
an approval transition can record its decision without changing the evidence
the reviewer inspected. Any changed source, canonical content, features,
rights, or validation changes the binding and makes the old decision stale.

## Registry, active index, and artifacts

The deterministic root contains:

```text
library_registry.json
active_template_index.json
validation_report.json
library_manifest.json
library_summary.md
project_packages/<case>/<version>/
  project_case_package.json
  provenance.json
  validation.json
feature_packages/<case>/<version>/
  template_features.json
source_bundle_manifests/<case>/<version>/
  asset_manifest.json
```

The registry includes every version, original and effective lifecycle status,
current-version flag, role, review/approval states, eligibility, active
status, synthetic-fixture provenance, source and package fingerprints,
feature fingerprint, controlled timestamp, and exclusion reasons. The active
index contains only current packages that pass every gate; every entry
carries a machine-readable `synthetic_test_fixture` flag, and synthetic
entries additionally carry the verbatim test-data disclaimer so a fixture can
never be presented as a real approved template. The library manifest records deterministic
relative paths, sizes, and SHA-256 hashes for every managed artifact except
itself, and binds its own controlled metadata with a non-recursive
`root_fingerprint` (SHA-256 over the canonical manifest content excluding
that field). `library validate` additionally rederives the manifest expected
for the stored controlled timestamp, so changing only the manifest's
`generated_at` is reported as a stale root artifact.

Validation covers schemas, required fields, source/bundle/canonical/package/
feature hashes, rights, confidentiality, case/version consistency, duplicate
and immutable versions, stale approvals, eligibility, active-index integrity,
feature references, missing source sizes/assets, unsupported parser status,
forbidden private/absolute paths (POSIX-absolute, UNC, Windows drive-absolute
and drive-relative forms, in every serialized field), deterministic ordering,
supersession, the permanent TEST-OFFICE exclusion, and the known synthetic
fixture's `synthetic_test_fixture` provenance (a contradicted marker is a
blocking error rejected before the version is written). An ambiguous version
fork — multiple heads, or two versions superseding the same predecessor — is
a blocking error: no version of that case is selected as current or activated.
Unreadable or schema-invalid stored versions are reported as validation
findings. Identifiers must be portable single path components: Windows
reserved device names, trailing dots, and case-only aliases of stored
identifiers are rejected. Failures are machine-readable.

## Lifecycle and CLI

Commands are non-interactive and require an explicit library root:

```text
spd library ingest --library-root ... --asset ...
spd library import-case --library-root ... --artifacts ...
spd library list --library-root ...
spd library show --library-root ... --case-id ... [--case-version ...]
spd library apply-review --library-root ... --case-id ...
spd library archive --library-root ... --case-id ...
spd library rebuild-index --library-root ... --generated-at ...
spd library validate --library-root ...
```

Mutation commands require caller-controlled ISO creation metadata. `ingest`
and `import-case` support `--dry-run`. `--json` emits one machine-readable JSON
object without a leading human banner. Exit code 0 is success, 2 is invalid
input/rights/conflict/review state, and 3 is validation failure. `validate`
re-derives the registry, active index, and full validation findings from the
stored immutable versions, so version-chain, active-index, and TEST-OFFICE
errors fail it, and stale or tampered root artifacts are reported; a failing
rebuilt validation report also makes `rebuild-index` exit 3, and every
non-dry-run mutation command re-reports its rebuilt validation verdict the
same way — a mutation over a library whose validation fails exits 3 instead
of claiming success. A version write interrupted before every immutable
artifact reached disk is completed by the exact identical retry (never by a
differing one); mutations are not serialized across concurrent processes, so
a race that forks a version chain is not prevented, but the fork is a
blocking validation error that the offending mutation itself reports.

Corrections or changed canonical data are applied by importing the corrected
safe M6A artifact set as a new version with `--supersedes`. `apply-review`
supports architect-reviewed, approved, rejected, and revoked decisions. An
approved decision additionally requires `--approve-template-use`; neither a
filename nor a folder name can create approval.

## TEST-OFFICE-001

`TEST-OFFICE-001` is a Nordic mixed-use office IFC ingestion stress test. In
the M7.1 reference library it is registered as `ingestion_stress_test`, remains
`requires_review`, retains its source fingerprint and diagnostic features,
and stays template-ineligible. It is permanently rejected by the active-index
gate even if other fields are forged. Its IFC/RVT source is not copied.

## Synthetic fixture disclaimer

`SYNTHETIC-VILLA-TEST-001` is sanitized automated **test data only**. It is not
a real project, not a professional design, and not evidence of architectural
quality or suitability. Its provenance is explicitly
`synthetic_test_fixture`. It may be explicitly approved only to exercise the
M7.1 active-index gates in tests and the safe reference library. It must never
be presented as a real Saudi villa template.

## M7.2 — Approved villa intake and architect review workflow

M7.2 prepares a stored library case version for HUMAN architect review. It
adds no retrieval, ranking, similarity, adaptation, or generation.

`spd library prepare-review` renders a deterministic 14-file package from the
stored immutable version (never from live sources): `intake_summary.md`,
`source_bundle_manifest.json`, eight review CSVs (program, rooms, entrances,
routes, adjacency, wet areas, facade openings, quality findings),
`architect_corrections_template.json`,
`architect_review_decision_template.json`, `intake_validation_report.json`,
and `review_package_manifest.json` (hashes, sizes, and a non-recursive
`root_fingerprint`; verified by `validate-review-package`, exit 3 on
failure). The package directory holds exactly the manifested files: foreign
files in the output directory block generation, and any unmanifested file on
disk fails validation. All timestamps come from the version's controlled
creation metadata, so regeneration is byte-identical. Synthetic-fixture cases carry
the verbatim disclaimer: "TEST DATA only. Not a real project, not a
professional architectural design, and not evidence of regulatory, cultural,
municipal, or permit approval."

`spd library apply-corrections` consumes the filled corrections template.
Every correction must reference a real canonical ID (rooms, entrance doors,
openings, adjacency pairs, routes, recorded limitations); blank reviewers,
invalid ISO dates, unknown targets, mismatched old values (for room type,
zone, and entrance classification), stale binding fingerprints, and
conflicting duplicates are rejected. Corrections never modify sources or
stored versions: they are recorded as an overlay feature
(`corrections.records`, group `architect_corrections`) in a NEW immutable
version (lifecycle `corrected`, review state `requires_review`, approvals
cleared, an approved-template role demoted to candidate). The changed
feature fingerprint changes the review binding, so every earlier decision
becomes stale.

`spd library apply-architect-decision` consumes the filled decision template
(`requires_revision`, `architect_reviewed`, `rejected`, or
`approved_template`) and routes it through the existing fingerprint-bound
review gates; `approved_template` maps to the full M7.1 approval gate and
nothing is ever inferred from filenames, folder names, labels, or scores.
`spd library show-review-status` reports the derived registry state, review
state, binding fingerprint, recorded corrections, and active-index
membership. All M7.2 commands take an explicit `--library-root`, support
`--dry-run` and `--json`, and keep the documented exit codes.

## Current limitations and M8 distinction

- M7.1 reads only safe M6A canonical artifacts; direct generic source bundles
  remain catalogued until a supported parser workflow produces a canonical
  case.
- Native RVT/DWG, PDF, OCR, image understanding, and specification parsing are
  not implemented.
- Source file availability is external; the library proves recorded hashes but
  does not copy or periodically re-open confidential sources.
- Feature completeness is bounded by source evidence. Missing geometry remains
  missing.
- The file store is local and single-process; it is not a database or service.
- M8 retrieval is not implemented. There is no “best template,” similarity,
  ranking, candidate selection, or adaptation in M7.1.
