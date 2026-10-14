# NOT_NOW.md

**Status: LOCKED before implementation.** These items are explicitly excluded from the MVP. They may only move into scope via an explicit user instruction that also updates LOCKED_MVP_SCOPE.md. Codex review comments may never move an item off this list.

Rule for implementers: if a feature is on this list, do not build it, do not stub it, and do not add UI affordances (buttons, flags, menu entries) that reference it. Unimplemented buttons are forbidden.

## Input & data acquisition
- OCR of deeds, krokis, or scanned plans
- Automatic plot extraction from PDFs, images, or satellite imagery
- Any plot shape other than a rectangle; plots other than the 20 m × 30 m reference case
- Multiple plots / batch processing
- Automatic street/neighbor edge detection (from maps, imagery, or heuristics)
- Parcel or basemap API integrations (Balady, national geoportals, Google/HERE, OSM import)

## Regulations & compliance
- Real municipal setback/zoning rule ingestion; per-amanah rule databases
- Compliance checking or certification claims of any kind
- Municipality / Balady / permit-system integration
- FAR, height, coverage, or parking calculations beyond the single demo setback rule set

## Design generation
- Multi-floor support (ground + first, basements, roof annexes)
- More than one floor-plan skeleton (only "Compact 3BR")
- Room-by-room parametric customization or interactive plan editing
- Structural design of any kind (columns, beams, slabs, foundations)
- MEP (electrical, plumbing, HVAC) of any kind
- Courtyard, duplex, apartment, or villa-with-annex typologies

## Saudi character & styles
- More than one pilot style pack (only `najdi_demo_v1`)
- Inferring architectural character from an LLM
- Inferring architectural character from photos of nearby buildings
- Claiming any zone polygon or style rule is official Saudi data before verified data is provided
- Style blending, style transfer, or user-authored style editors

## Outputs
- Any 3D output (GLB, OBJ, FBX, meshes, extrusions)
- Revit (RVT/RFA) or IFC export/import
- Photorealistic or AI-image rendering
- Side/rear elevations, sections, interior elevations (front elevation only)
- BOQ, cost estimation, or quantity takeoff
- Web viewer, web UI, mobile app, or any GUI (CLI only in MVP)

## Platform & operations
- User accounts, authentication, multi-tenancy
- Cloud deployment, APIs, job queues
- Databases (files on disk only)
- Localization/Arabic UI (output labels are English in the slice; Arabic is a later milestone)
- Payment, licensing, telemetry
