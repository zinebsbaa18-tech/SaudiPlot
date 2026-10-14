# GEOSPATIAL_DATA_PROVENANCE.md

Policy for every piece of geographic, regulatory, and architectural-style data in this repository. This policy exists because the single biggest integrity risk of this product is presenting fabricated Saudi data as official.

## 1. Provenance levels and hard rules

Two kinds of data exist and are governed differently:

- **Governed reference datasets** — character zones, setback rules, style packs. These carry embedded provenance and are subject to every rule below.
- **User inputs** — plot corners (CSV or CLI dimensions), edge classes, location point. These are assigned provenance `user` at ingestion; they carry **no embedded provenance field** and can never make anything "official".

| Level | Meaning | Allowed uses |
|---|---|---|
| `demo` | Fabricated by the development team purely to exercise the pipeline. Explicitly NOT real. | Development, tests, demos — always with visible disclaimer |
| `user` | Supplied by the end user for their own plot. Assigned at ingestion, never embedded in files. | Their run only; echoed to `run.json` |
| `verified` | Obtained from an authoritative source with recorded source, date, license, and transformation history. | **Rejected by MVP loaders** (see rule 2). Reserved for a future, explicitly approved scope change. |

Hard rules:

1. **Never fabricate `verified` data.**
2. **MVP loaders accept only `demo` provenance for governed reference datasets.** A file claiming `verified` (or any other level) is rejected at load with an error. This makes disclaimer suppression via self-declared metadata impossible: provenance metadata alone must never be able to make data look official. Verified-data activation is a future scope change requiring an explicit user instruction plus a trusted approval mechanism (e.g., a reviewed allowlist/manifest maintained outside the data files) — designing that mechanism is out of MVP scope.
3. **The DEMO disclaimer is unconditional in the MVP.** Every output of every run renders it: PDF title block, DXF `ANNOTATION` layer, `run.json` (full text in a `disclaimer` field plus per-dataset provenance records for zones, setback rules, and style pack), and every CLI summary — including recommendation-only output. Text: *"DEMO DATA — geographic zones, setback rules, and style rules are demonstration data, not official Saudi regulations or official Saudi Architecture guidelines."*
4. Every governed reference file carries provenance **inside the file** (not just in docs); loaders reject files without it (ARCHITECTURE.md D4). Per-file contract: GeoJSON zone files use a top-level `x_provenance` block plus per-feature `provenance` (SAUDI_CHARACTER_ENGINE.md §3); setback rule files use a top-level `provenance` field; style packs use a `provenance` object (STYLE_PACK_SCHEMA.md §2). All three normalize to one internal provenance model at load.
5. Demo governed files live only under `src/saudi_plot_design/data/demo/` and carry `demo` in the filename. Id conventions: zone and rule-set ids use a `DEMO-` prefix; style pack ids must contain `demo` (e.g. `najdi_demo_v1`; amended by owner instruction, 2026-07-13). `samples/` contains sample **user inputs** (no embedded provenance; classified `user` at ingestion like any user file).
6. No file in this repo may reproduce content from official documents without license verification first.

## 2. Current inventory (MVP)

| File | Level | Notes |
|---|---|---|
| `src/saudi_plot_design/data/demo/architectural_character_zones/` (`zones.geojson` + `metadata.json`) | demo | 3 hand-drawn rectangles (Riyadh/najdi, Jeddah/hejazi, Abha/asiri), labeled DEMO SYNTHETIC - NOT OFFICIAL - REQUIRES VERIFICATION. Coarse on purpose so nobody mistakes them for a real map. |
| `src/saudi_plot_design/data/demo/demo_setback_rules.json` | demo | `DEMO-SETBACK-01`: front 3.0 / sides 2.0 / rear 2.0 m. Plausible magnitudes, invented values. |
| `src/saudi_plot_design/data/demo/styles/najdi_demo_v1/` (4 JSON files) | demo | Demo interpretation of Najdi character, status `demo_requires_architect_review`; not from official guidelines. |
| `samples/plot_20x30.csv` | user (sample) | Synthetic sample **user input** — not a governed reference dataset; classified `user` at ingestion, no embedded provenance field. |

## 3. Metadata contract for future `verified` data (NOT accepted by the MVP)

**MVP loaders reject any file claiming `verified` (§1 rule 2).** This section only records what a verified file will have to embed once a future, user-approved scope change introduces a trusted approval mechanism; metadata presence alone will never be sufficient. The fields below nest under each format's existing provenance key from §1 rule 4 — `x_provenance` for GeoJSON zone files, `provenance` for setback rule files and style packs (the block is shown with the GeoJSON key as an example):

```json
"x_provenance": {
  "level": "verified",
  "source_name": "…",            // issuing authority
  "source_document": "…",        // title + version/edition
  "source_url_or_ref": "…",
  "publication_date": "YYYY-MM-DD",
  "retrieved_date": "YYYY-MM-DD",
  "license": "…",                // license/permission basis
  "transformations": ["…"],      // every processing step from source to file
  "verified_by": "…"             // person who checked source fidelity
}
```

In the MVP, files claiming `verified` are rejected outright — with or without these fields.

## 4. Missing verified Saudi datasets (the authoritative list)

| # | Dataset | Needed for | Expected authority | Status |
|---|---|---|---|---|
| V1 | Saudi Architecture character map — official zone polygons for the announced regional characters | Character engine zones | Saudi Architecture program / Ministry of Municipalities and Housing (MoMaH) | Not obtained. No public machine-readable polygons known to us; must be provided or licensed. |
| V2 | Official design guidelines per character (Najdi first) — proportions, openings, ornament, materials | Style packs | Saudi Architecture program design guideline documents | Not obtained in verified machine-readable form. |
| V3 | Municipal setback / residential zoning regulations (per amanah; Riyadh first) | Setback rule sets | MoMaH / Balady / relevant amanah | Not obtained. Demo values are placeholders. |
| V4 | Parcel geometry source (deed/kroki conventions or cadastral extracts) | Plot ingest beyond manual entry | GASGI / Saudi cadastre / user documents | Out of MVP scope (manual entry only), listed for the roadmap. |
| V5 | Verified material & color palettes per character | Style pack materials | Saudi Architecture guidelines | Not obtained. |

Acquisition plan: request V1–V3 from the user/stakeholders with license terms. Ingesting them — and any relaxation of the unconditional disclaimer — is a future scope change per §1 rule 2 and §3; it is not something the MVP can do.

## 5. Recorded open questions (not MVP work)

- Official zone overlap/precedence semantics (MVP demo data is authored non-overlapping and the loader enforces it).
- CRS of official deliveries (assume EPSG:4326; reproject as a documented transformation if not).
- Update cadence of the official map and versioning of zone files.
