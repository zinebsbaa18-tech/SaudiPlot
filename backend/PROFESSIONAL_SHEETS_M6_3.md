# M6.3 Professional 2D Architectural Sheet Engine

## Status and purpose

M6.3 is a deterministic presentation layer over the existing canonical plot,
plan, facade, M6.1 quality assessment, and M6.2.1 route evidence. It produces a
coherent A3 architectural concept set without changing the selected plan,
opening coordinates, facade geometry, quality rules, scores, denominators, or
optimizer ranking.

The sheets are revision and communication artifacts. They are **not**
construction documents, permit drawings, municipality submissions, regulatory
approval, or professional architectural approval. The unconditional DEMO-DATA
disclaimer and `NOT FOR CONSTRUCTION` status appear on every sheet and in every
sheet JSON artifact.

## Architecture

The sheet package is `src/saudi_plot_design/sheets/`:

- `models.py` defines the versioned graphic profile, shared vector primitives,
  sheet/index/validation records, collision records, and export result;
- `graphics.py` renders the same millimetre-space primitives to standalone SVG
  and vector PDF. Exporters do not independently reconstruct geometry;
- `engine.py` composes the five sheets from canonical source objects, places
  annotations and concept symbols, builds schedules, and validates the set;
- `export.py` writes PDFs/SVGs/index/collision report, records sizes and SHA-256
  hashes, and verifies the sheet manifest.

SVG coordinates use a fixed `420 x 297` millimetre view box with page Y
increasing downward. PDF uses the same primitive coordinates, mapped to ISO A3
landscape points. ReportLab invariant mode and fixed caller-supplied metadata
make PDF bytes deterministic. No external CSS, JavaScript, fonts, CDNs, network
resources, or raster images are used.

## Graphic profile

`architectural_concept_a3_v1` fixes:

- ISO A3 landscape (`420 x 297 mm`), 10 mm printable margins, and a 30 mm title
  block;
- ReportLab's system Helvetica/Helvetica-Bold names, with an SVG
  Arial/Helvetica/sans-serif system-font fallback;
- title, heading, body, note, annotation, and schedule text sizes;
- plot, cut-wall, projected-element, opening, dimension, annotation, and hairline
  weights;
- envelope dash, annotation spacing, arrow size, scale-bar convention, and
  metre units;
- revision `P01`, concept-issue status, candidate ID, source geometry
  fingerprint, fixed issue date support, and non-construction status.

The DXF preserves every legacy layer and adds the owner-authorized professional
layers `A-PLOT`, `A-SETB`, `A-WALL-CUT`, `A-WALL-PROJ`, `A-DOOR`, `A-WIND`,
`A-FURN`, `A-FIXT`, `A-DIMS`, `A-ANNO`, `A-HATCH`, `A-TTLB`, and `A-REVIEW`.
Layer colour, valid DXF lineweight, and linetype attributes are explicit and
stable. No DWG is generated.

## Sheet list and output modes

The clean concept PDF contains:

1. `A-001` Cover and Design Basis;
2. `A-101` Site and Ground Floor Plan (clean variant);
3. `A-201` Front Elevation;
4. `A-601` Room, Door and Window Schedules.

The design-review PDF contains the same sequence with the review variant of
`A-101`, then:

5. `A-901` Design Review and Limitations.

Output modes are:

- `none`: retain the pre-M6.3 export surface;
- `concept`: clean PDF plus the four relevant SVG sheets;
- `review`: review PDF plus all five SVG sheets;
- `all`: both PDFs plus all five SVG sheets.

The CLI default is `concept`. The library-level `export_project` default remains
`none` for backward-compatible callers; the CLI passes its selected mode
explicitly.

Generated M6.3 files are:

- `architectural_concept_sheet_set.pdf`;
- `architectural_review_sheet_set.pdf`;
- `sheets/A-001-cover.svg`;
- `sheets/A-101-ground-floor-plan.svg`;
- `sheets/A-201-front-elevation.svg`;
- `sheets/A-601-schedules.svg`;
- `sheets/A-901-design-review.svg`;
- `architectural_sheet_index.json`;
- `annotation_collision_report.json`;
- `architectural_sheet_manifest.json`.

The sheet index records number, title, revision, issue status, media,
orientation, scale, candidate, source geometry fingerprint, filename, and PDF
set membership. The manifest records media, page order, validation results, and
the exact size and SHA-256 hash of every sheet artifact other than the manifest
itself. `run.json` and the top-level export manifest record all sheet paths,
hashes, identity fields, and validation status.

## A-101 annotation and dimension rules

The reference plot fits at actual scale `1:150`. The plan shows plot boundary,
authored boundary classifications and street width, buildable envelope,
footprint, opening-gapped cut/projected walls, canonical doors/windows, local
plot orientation, and a ten-metre scale bar.

The north symbol is explicitly `N* / LOCAL PLOT +Y / NORTH NOT SURVEYED`; it is
not true north and does not invent survey information.

Room labels use this stable sequence:

1. full label inside the room when it fits;
2. compact label inside the room;
3. keyed label with a leader if compact text cannot fit.

Required annotations are never silently omitted. Compact/leader fallbacks and
any unresolved conditions are written to `annotation_collision_report.json`.
The reference uses four resolved compact fallbacks and zero unresolved
collisions. Review mode adds stable `R01...` room tags and finding markers;
clean mode omits technical finding markers. Door/window tags are stable
`D01...` and `W01...`; schedules retain both tag and canonical source ID.

Dimensions come only from canonical geometry: plot width/depth, footprint
width/depth, front setback labels, selected front-room chain segments, room
clear dimensions in labels where space permits, and opening widths in tags and
schedules. Values use stable rounding in metres. No construction tolerances,
structural grids, survey coordinates, or fabricated dimensions are added.

## Door, window, furniture, and fixture symbols

Every door/window symbol references an existing canonical opening and host
wall. Door leaves, hinges, and arcs use a deterministic presentation convention
at the wall-start end of the opening and swing toward the connected room. The
canonical model has no authored hinge, handing, or operation; therefore the
sheets and schedule label the representation `SCHEMATIC / HANDING N/A`.

The limited vector symbol library covers beds, wardrobes, maid bed,
family/majlis seating, dining table, kitchen counter, WC, basin, shower, and
washer. It is labelled `concept furniture layout`. Symbols are placed inside
their canonical room and tested against schematic door-swing clearance boxes.
The DXF uses the same containment and swing-clearance constraints. When no safe
placement is available, the symbol is omitted with a recorded reason. In the
optimized reference the guest-WC and shared-bath fixtures are omitted for this
reason. Furniture never changes plan geometry or quality scoring; furniture
usability remains not evaluable by M6.1.

## Schedules

`A-601` contains all 14 rooms, 15 doors, and 11 windows on one A3 sheet.

Room rows include canonical ID, name, zone, area, clear width/depth, rectangular
perimeter, external-wall contact, external-opening state, and frozen room
quality status.

Door rows include stable tag/canonical ID, connected spaces, internal/external
state, authored entrance classification, width, available front-facade height,
schematic operation/handing statement, and review flag. Internal door height is
`N/A` because it is not authored.

Window rows include tag/canonical ID, room, host wall, width, height, sill,
reference, and review flag. Street-facade sill/head values come from the DEMO
style pack. Other windows show the canonical plan's explicitly nominal
sill/head values and are flagged `PLAN NOMINAL / FACADE N/A`.

## A-201 and A-901

`A-201` reuses the selected facade's elements and openings. Wall, parapet,
plinth, ground line, levels, total height, opening references, and restrained
material fills come only from the facade object and DEMO style pack. It does not
add side/rear elevations or claim final Najdi/official Saudi style approval.

`A-901` reports the frozen M6.2.1 assessment without recalculation: effective
and category scores, evidence coverage, active major/moderate findings,
unsupported checks, authored entrance inventory, and family/guest/service/
guest-WC route summaries. For `candidate-016` it continues to show score 88.89,
workable-with-targeted-revisions status, zero blocking findings, and remaining
major findings `ADJ-006` and `SAU-005` with evidence.

## CLI

The existing command remains valid. New options are:

```text
--sheet-set none|concept|review|all
--paper-size A3
--sheet-language en
```

Only A3 and English are implemented in M6.3. Unsupported values are rejected by
the CLI; there is no interactive prompt and no placeholder surface.

## Validation and determinism

Sheet validation checks graphic profile/media, page presence and order,
candidate/fingerprint consistency, complete primitive and title-block bounds,
body/title-block separation, disclaimers, room/door/window schedule coverage,
annotation collision count, and pass-through of the supplied frozen assessment
without rescoring. PDF reopen tests verify A3 media, page order, text, and no
approval language. DXF tests reopen and audit the file, layer attributes,
symbols, door clearance, and traceability. SVG/PDF/DXF and JSON artifacts are
byte-compared between two fixed-metadata runs, and every sheet/top-level
manifest hash and size is independently recomputed.

Staged publication treats `sheets/` as one rollback-safe directory. Switching
to `none` removes stale managed sheet outputs during a successful transaction;
a publication failure restores the previous directory and audit set.

## Known limitations

- The selected geometry remains a concept skeleton, not a developed design.
- North is not surveyed; external site-path geometry is unavailable.
- Door handing/operation and furniture layouts are schematic and unauthored.
- Only the selected front facade is developed; non-front window elevation data
  remains nominal-plan information.
- No structure, MEP, fire/life-safety, accessibility, energy, municipal,
  constructability, specification, bill-of-quantities, permit, or professional
  approval is evaluated or implied.
- All governed geographic, setback, character, and style data remains DEMO
  provenance.

Construction documents would require coordinated authored assemblies,
structure/MEP, details, specifications, code analysis, surveyed information,
and professional responsibility. Permit drawings would additionally require
the applicable authority's verified rules, submission requirements, and formal
review. M6.3 provides neither.
