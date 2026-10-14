# M6A — Approved Architectural Case Ingestion (IFC first)

Post-MVP milestone on branch `m6-approved-case-library`. This module ingests
ONE professionally designed residential villa candidate (IFC4) and converts
it into a structured, reviewable **Architectural Design Case**. The same
ingestion path may be exercised by an explicitly declared non-residential BIM
stress test, but such a case is permanently template-ineligible. M6A does
**not** generate designs, adapt layouts, or derive templates by itself.

## Scope (strict)

- Exactly one source case; IFC4 architectural models only (export RVT to IFC
  manually before ingestion). Non-IFC4 schemas are rejected with a clear error.
- Not implemented, by design: native RVT reading, DWG parsing, PDF plan
  recognition, OCR, AI image understanding, layout adaptation/generation,
  web interface, additional cases, fine-tuning.
- The MVP pipeline (M0–M5, `spd generate`) is untouched; the `cases` package
  is standalone and `ifcopenshell` is an optional dependency
  (`pip install -e ".[cases]"`).

## Private data safety

- Source lives in gitignored `private_cases/case_001/` with mandatory
  `model.ifc` + `case_metadata.json` (optional `references/`).
- Source files are read in place and **never copied into tracked paths**;
  outputs record only a safe display path (`private_cases/<name>` — or
  `<confidential>` when the case is confidential).
- Ingestion is hard-blocked unless `usage_rights_confirmed` is `true`.
- When `anonymization_required` is set, notes are scrubbed of
  emails/phones/client/owner/address/price markers, the district is dropped,
  `approved_by` and the reviewer name are redacted, and **every IFC-sourced
  text field** (space/wall/slab/opening names, long names, materials, site and
  building names, warnings) is scrubbed before classification and export;
  validation check K12 re-verifies all of it on the assembled case.
- Confidential cases never record the source folder name (it conventionally
  carries the project code): the recorded path is `private_cases/<confidential>`.

## Pipeline

`saudi_plot_design.cases.pipeline.ingest_case(source_dir, out_dir)`:

1. Load + anonymize metadata; enforce the usage-rights gate.
2. Read architectural IFC entities only (project/site/building/storeys,
   spaces, walls, slabs, doors, windows, opening relationships, space
   boundaries, materials). Every object keeps its IFC GlobalId. Missing data
   produces explicit warnings — never fabricated values.
3. Classify spaces/zones/entrances from names (Arabic + English keywords).
   Every classification records method, confidence, source, and
   `reviewer_status="requires_review"`; anything unmatched stays `unknown` at
   confidence 0.0. A reviewer-supplied `review_corrections.json` in the source
   directory overrides inferences (method `manual_correction`, confidence 1.0).
4. Build room adjacency (shared bounding walls from IfcRelSpaceBoundary),
   door-based circulation, zone adjacency, entrance reachability paths
   (guest/family/service), wet-room clusters, facade opening inventory, and
   descriptive metrics (no automatic quality claims).
5. Validate (checks K01–K13) into a structured report — unsupported or
   incomplete models produce report entries/errors, never invented data.
6. Write review artifacts to the (gitignored) output directory:
   `case_manifest.json`, `architectural_case.json`, `spaces.json`,
   `elements.json`, `adjacency_graph.json`, `circulation_graph.json`,
   `facade_openings.json`, `metrics.json`, `validation_report.json`,
   `review_corrections_template.json`, `plan_preview.svg` (technical
   inspection preview, not a presentation drawing).

## Template eligibility

Review state and template eligibility are separate. Every canonical case and
manifest exposes `template_eligible` plus an ordered
`template_ineligibility_reasons` list. An eligible residential-villa candidate
still starts at `requires_review` and is never automatically approved.

Eligibility is evaluated deterministically from declared metadata and current
case content. A candidate must declare `project_type="residential_villa"`,
`case_role="residential_villa_template_candidate"`, a Saudi country value,
an applicable architectural character, a positive floor count, and an
extracted residential program containing a bedroom and bathroom. Usage rights
must be confirmed and all K01-K13 validation checks must pass. Missing source
information remains missing and makes the candidate ineligible where the
policy requires that information; it is never fabricated. Ordinary extraction
warnings are non-blocking unless they produce a failed validation check.

Non-residential, mixed-use office, commercial, ingestion-stress-test, and
other explicitly non-template roles remain available for ingestion,
correction, validation, and `architect_reviewed`, but cannot advance to
`approved_template`. `TEST-OFFICE-001` is a Nordic mixed-use office ingestion
stress test whose project type, country, declared purpose, and inapplicable
Saudi-villa character permanently make it template-ineligible.

## Approval gate

States: `ingested → requires_review → corrected → architect_reviewed →
approved_template | rejected`.

- Ingestion always stops at `requires_review` (or `corrected` when a
  corrections file actually changed at least one classification; corrections
  referencing unknown GlobalIds are rejected, and blank template values mean
  "unchanged").
- Only an explicit `review_decision.json`
  (`{"state", "reviewed_by", "review_date", "case_fingerprint"}`) in the
  source directory can advance a case, and only to `architect_reviewed`,
  `approved_template`, or `rejected`. `case_fingerprint` must equal the
  `review_binding_fingerprint` from the `case_manifest.json` the reviewer
  inspected — it binds the decision to the exact model bytes, metadata, and
  corrections reviewed, so a stale approval cannot unlock changed content.
  The validated `review_date` is persisted in provenance and the manifest.
- An `approved_template` decision is rejected with stable machine-readable
  eligibility reasons when any eligibility rule or blocking validation check
  fails. A valid reviewer, date, and matching fingerprint cannot bypass this
  policy; the existing stale-decision protections remain unchanged.
- `saudi_plot_design.cases.models.assert_template_usable(case)` is the
  defense-in-depth gate for any future generator. It requires
  `approved_template` and re-evaluates current eligibility and validation
  rather than trusting the stored state or eligibility flag alone.

## Tests

`tests/test_m6a_cases.py` with a synthetic IFC4 fixture builder
(`tests/m6a_ifc_fixture.py`). The fixture is clearly labeled TEST DATA — it is
not a professional design and is never treated as an approved template.
