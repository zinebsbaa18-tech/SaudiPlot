# Geo Knowledge Package (sbc_geo_knowledge v0.1.1)

Versioned, validated export of the **advisory architectural-character
knowledge base** for the East Coast (Dammam metropolitan area): style-zone
polygons, extracted character rules, rule–zone links, recorded conflicts, and
the runtime SQLite database the backend queries.

> **⚠️ Accuracy and status — read before use**
>
> - **Zone boundaries are approximate (declared accuracy about ±3 km).** The
>   source maps were georeferenced with *estimated* control points at coastal
>   landmarks, not survey measurements. Never use these results to determine
>   individual parcels, legal zoning, or official regulatory compliance.
> - **Review state is preserved, not hidden.** 154 of 200 rules are approved;
>   46 remain `pending_review`. 9 of 15 zone-overlap conflicts have recorded
>   resolutions; 6 are auto-classified boundary slivers awaiting human review.
>   The backend surfaces pending items with warnings and never presents them
>   as approved guidance.
> - Sources are **architectural-character guides** (styles, facades,
>   materials); they contain no quantitative municipal requirements
>   (setbacks, coverage ratios).

## Contents

Paths mirror the upstream package so upstream documentation stays valid:

| Path | Content |
|---|---|
| `01_inventory/` | Source-document manifests (`sources.csv/json`, inventory report) |
| `03_extracted_maps/map_index/maps.json` | Index of the five style-distribution maps (MAP-DMA-01…05) |
| `04_georeferencing/` | Georeferencing report + control-point record (accuracy provenance) |
| `05_vector_gis/zones/` | Approved zone polygons per map (GeoJSON, EPSG:4326) + canonical zone records |
| `06_rules_knowledge/` | Extracted rules (`rules.jsonl`), normalized rule–zone links, conflict records and resolutions |
| `07_database/` | **Runtime artifacts (Git LFS):** `sbc_rules.sqlite` (full DB, 14 tables + FTS), `sbc_geo_knowledge.gpkg` (GeoPackage) |
| `10_quality_control/reports/qa_report.html` | Quality report for the build |
| `README.source.ar.md`, `CHANGELOG.source.ar.md` | Original upstream documentation (Arabic) |
| `VERSION.json` | Version, counts, review status, accuracy limitations |
| `MANIFEST.csv` | SHA-256 of every exported file |

Deliberately **not** exported: raw source archives, extracted page images of
the source documents, QA overlay imagery derived from them, duplicate export
formats (`11_exports/`), and the pipeline/API/viewer code — the upstream
working folder remains the home of the full pipeline.

## How the backend uses it

`backend/.env.example` points `SPD_GEO_KNOWLEDGE_DB` at
`knowledge/geo/07_database/sbc_rules.sqlite`. The backend opens it
**read-only** and replicates the published point-in-polygon semantics (bbox
prefilter + containment, city maps over the metropolitan map). Guidance flows
only through fully approved chains (approved zone → approved link → approved
rule); everything else stays visible as candidates/conflicts with warnings.

## Verifying integrity

```powershell
# Any file's hash must match its MANIFEST.csv row:
Get-FileHash knowledge/geo/07_database/sbc_rules.sqlite -Algorithm SHA256
```

Zone level → allowed character families: level 1 = traditional; level 2 =
traditional + transitional; level 3 = traditional + transitional +
contemporary; excluded areas fall outside character requirements.
