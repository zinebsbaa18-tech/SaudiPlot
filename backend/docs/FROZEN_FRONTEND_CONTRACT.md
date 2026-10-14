# Frozen Frontend Contract

- **Status:** Frozen (product decision, W0). See ADR-WEB-001.
- **Frontend repository:** `C:\AI\Saudi-Plot-Frontend-main` (separate repo; read-only
  for backend milestones — never copied, edited, staged, or committed from here).
- **Stack:** Vite + React 19, `react-router-dom` 7, Zustand 5, i18next (Arabic
  default + fallback, RTL; English secondary), framer-motion, maplibre-gl (lazy),
  pdfjs-dist + jsqr (client-side QR scan), `@fontsource` Arabic fonts.

This document records the accepted frontend surface exactly as inspected on
2026-07-20. It is the reference for "did the UI change?" — the journey below must
keep working identically as backend wiring is introduced. Frozen means: no screen or
prompt may be redesigned, removed, added, reordered, renamed, or visually altered.
Behavioral wiring, data fetching, persistence, validation, accessibility fixes, and
non-visual bug fixes are allowed only when they preserve everything below.

The existing frontend journey is frozen; the deterministic offline core is wrapped —
never modified — by the web API (ADR-WEB-001, all eight binding rules apply).

## 1. Routes (App.jsx)

| Route | Page | Notes |
|---|---|---|
| `/` | `Landing` | Marketing/landing with its own upload card |
| `/upload` | `Upload` | Deed upload + analyze overlay |
| `/manual-entry` | `ExtractionFailed` | Manual entry form; error banner only when navigated with `state.extractionFailed` |
| `/confirm-data` | `ConfirmData` | Review/confirm extracted deed data |
| `/generating` | `Generating` | Generation progress screen |
| `/questions/1`…`/questions/6` | `Question1`…`Question6` | Inside `QuestionsOutlet` (directional slide carousel, reduced-motion aware) |
| `/room-catalog` | `RoomCatalog` | Also inside the carousel outlet |
| `/result-3d` | `Result3D` | Result page |
| `/result` | — | **Commented out** in App.jsx; `Result.jsx` exists but is unrouted. Frozen as unrouted. |

Step order for the carousel: `/questions/1` → … → `/questions/6` → `/room-catalog`.

## 2. The journey

```
Landing ─▶ Upload ─▶ (success) ConfirmData ─▶ Q1…Q6 ─▶ Generating ─▶ Result3D
              │                                  ▲  └▶ RoomCatalog ─▶ Generating
              └▶ (failure) /manual-entry ────────┘
```

### Landing (`/`)
Hero with brand "عَمِّر أرضك", nav (how/features/results + language toggle + CTA to
`/upload`), three step cards, feature cards, its own upload card (file input accepts
`.pdf,.jpg,.jpeg,.png`; "review" navigates to `/upload` with the file in router
state), results section with sample floor-plan image and animated area counter,
final CTA, footer. A "manual entry" style button exists on the upload card
(currently no-op — frozen as-is).

### Upload (`/upload`)
Drag-and-drop card + hidden file input (`application/pdf,image/*`), "choose file"
button, hint text, manual-entry link (→ `/manual-entry`, no error state), privacy
line with lock icon. On file selected:

- Client-side validation (type/size, 20 MB max) → inline error `upload__file-error`
  under the card on failure.
- **Loading state (frozen):** full-screen modal overlay with three sequential steps
  — `reading` → `sending` → `parsing` — each with pending/active-spinner/done-check
  states, then a success checkmark panel ("success" + "redirect" copy) and an
  auto-navigate to `/confirm-data` after ~950 ms.
- QR codes are scanned client-side (jsqr + pdfjs) in parallel, capped at 8 s.
- **Error path (frozen location):** analysis failure navigates to `/manual-entry`
  with `state.extractionFailed = true` and the error message — the error is shown
  *there*, in the banner, not on the Upload page.

Current data source: `analyzeDeed()` calls Gemini **directly from the browser**
using `VITE_GEMINI_API_KEY` (`src/utils/geminiService.js`, `geminiClient.js` with a
primary→fallback model chain). This is a known pre-backend state; replacing it with
a server-side call is behavioral wiring (allowed later), but the overlay steps,
timings, and navigation targets above stay identical. API keys must end up
server-side only.

### ExtractionFailed (`/manual-entry`)
When `state.extractionFailed`: error banner ("!" mark, title + message) at the top,
"retry" secondary button (→ `/upload`), divider, then the manual form. Without that
state: the manual form only. Form (all required): width (m), height (m), street
width (m) — numeric inputs; map-picker button (lazy MapLibre modal with draggable
pin, plot rectangle, rotation handle); lat/lng numeric inputs; inline coords error
after touch. Continue button (disabled until complete) saves dimensions +
coordinates + rotation to the store and navigates to `/questions/1`.

### ConfirmData (`/confirm-data`)
Badge, title, subtitle. Then, in frozen order:

1. **Boundary card** — five editable rows (total area, north, south, east, west
   boundaries) with per-row "edit" toggling an inline input. Prefilled from the
   extracted deed; static fallback values when extraction data is absent.
2. **Plot dimensions (required)** — width/height numeric inputs, prefilled by
   parsing leading numbers from north/east boundary strings; inline error after
   touch.
3. **Coordinates (required)** — hint varies by source (QR vs manual), dimension
   badge, map picker button (pick vs relocate label), source hint (QR / map),
   formatted lat/lng display row, Google Maps link, manual lat/lng inputs, inline
   error after touch.
4. **Document info**, **Property info**, **Owners**, **QR codes + verification
   link**, **Extra information** — read-only sections rendered only when the deed
   data contains them (Arabic field labels are part of the frozen surface).
5. Source line ("extracted from deed #…" or fallback), then the confirm button
   (disabled until dimensions + coordinates complete) → saves to store →
   `/questions/1`.

### The six questions (frozen wording, order, and controls)

Shared `QuestionLayout`: step label, title, subtitle, back/next buttons, wizard
stepper header with six icons (family, accessibility, hospitality, kitchen,
services, final) — order fixed in `wizardSteps.js`.

| # | Topic | Control (frozen) | Store field |
|---|---|---|---|
| 1 | Family size | Two steppers: adults (min 1), children (min 0) | `familyMembers {adults, children}` |
| 2 | Elderly / accessibility | Yes / No chips | `hasElderly` |
| 3 | Guest reception | Three option cards: `independent` (مجلس بمدخل مستقل), `split` (مجلسان رجال/نساء), `living-room` (تكفي الصالة) | `guestReceptionId` |
| 4 | Kitchen | Three chips: مفتوح على الصالة / مغلق / مغلق + مطبخ تحضيري | `kitchenType` |
| 5 | Services | Multi-select chips, two rows: [غسيل وكيّ، غرفة عاملة منزلية بحمّام، غرفة سائق بحمّام] / [لا شيء، مدخل خدمة مستقل، مستودع]; selected chips gain "✓" | `services[]` |
| 6 | Space summary | Read-only colored space tags (master 28m², bedrooms ×3 46m², baths ×3 19m², living 38m², prep kitchen 28m², majlis+dining 46m², guest bath 5m², driver 24m², laundry 8m²), an "edit" button → `/room-catalog`, summary line; single "next" action → `/generating` | — |

### RoomCatalog (`/room-catalog`)
Title + subtitle; four categories of steppers (bedrooms: master/bedroom/bathroom/
closet[auto]; living: living/kitchen/prepKitchen[auto]; hospitality: majlis/
dining[auto]/guestBath[auto]; services: driver/laundry/storage) writing to
`roomCatalog` counts; summary sidebar with total-room count, fourteen fixed colored
tags, info banner, and a full-width button → `/generating`. "auto" badge text comes
from `stepper.auto`.

### Generating (`/generating`)
**Loading state (frozen):** spinner, title, a card of four steps advanced on random
1–5 s timers with done-check/active/pending marks, hint line; then a success phase
(animated checkmark, success title + hint) shown ~1.8 s before navigating to
`/result-3d`. On success it assembles `buildPayload()` and currently only logs it
to the console — the *intended* backend submission point. The steps are currently
simulated timers, not real progress; wiring them to real backend progress is
behavioral (allowed) as long as the visible sequence, layout, and success phase are
preserved. **No claim is made today that the answers affect the generated layout.**

### Result3D (`/result-3d`)
RTL page, frozen layout: header (title + subtitle), green success banner, then a
two-column layout —

- **View area:** toggle buttons 2D / 3D / MAP. 3D and 2D currently show a static
  isometric house SVG with two Arabic labels and +/− zoom buttons; MAP renders the
  real plot rectangle (MapLibre) from stored coordinates/dimensions/rotation.
  Footer note line under the view.
- **Sidebar:** summary card with five rows (total area, streets, dimensions,
  kitchen, design — currently static sample values), primary "PDF" button,
  outline "share" button, file-format buttons **DWG / DXF / SVG**, price block
  ("18,000 ر.س"), two extra buttons ("EPC 240 / RCA", "ألوان الواجهة (CFD/CFM)"),
  footer note.

Buttons are currently unwired; wiring them to real backend artifacts is behavioral
(allowed), the layout and labels are not.

## 3. Zustand store (`src/Store/useFormStore.js`) — frozen field contract

| Field | Shape / default |
|---|---|
| `deed` | Static template from `objects/format.json` (mock; to be replaced by backend OCR later) |
| `extractedDeedRaw` | Raw JSON from deed analysis (plus `_coordinates` injected from QR scan) |
| `landDimensions` | `{ width: "", height: "" }` (metres, strings from inputs) |
| `landCoordinates` | `{ lat: "", lng: "" }` |
| `landRotation` | `0` (degrees; visual orientation only) |
| `familyMembers` | `{ adults: 4, children: 3 }` |
| `hasElderly` | `true` |
| `guestReceptionId` | `"independent"` |
| `kitchenType` | `"مغلق + مطبخ تحضيري"` |
| `services` | `["غرفة عاملة منزلية بحمّام", "غرفة سائق بحمّام"]` |
| `roomCatalog` | 13 counts: master 1, bedroom 3, bathroom 2, closet 1, living 1, kitchen 1, prepKitchen 1, majlis 1, dining 1, guestBath 1, driver 1, laundry 1, storage 0 |

`buildPayload()` merges the deed template with `land_dimensions {width_m, height_m}`
and `family_preferences`:

- `family_members { count_range ("2-4"/"5-7"/"8-10"/"10+"), estimated_count }`
- `elderly_or_accessibility { has_elderly }`
- `bedrooms { count }` (= bedroom + master), `master_bedrooms { count }`
- `guest_reception { type: majlis_separate | majlis_two | living_room, label }`
- `kitchen { type: open | closed | closed_with_pantry, label }`
- `additional_rooms { laundry_room, maid_room, maid_entrance, storage_room, driver_room }` (from Q5 chips)
- `room_catalog` (the 13 counts)

This payload shape is the **frontend→backend submission contract**. The backend
adapts to it; the frontend is not reshaped to suit the backend. Every field in it is
a user choice: the backend must honor each one or return a structured refusal —
never silently ignore or override an answer (ADR-WEB-001 rules 4–5).

## 4. Current integration state (as frozen)

- `src/Api/Api.js` is **empty** — no backend calls exist yet anywhere in the app.
- Deed OCR runs client-side via Gemini with a Vite-exposed key (to be moved
  server-side; keys never remain in the browser).
- QR scanning runs client-side (jsqr + pdfjs) and injects coordinates.
- `Generating` progress is simulated; the payload is only logged.
- `Result3D` content is static except the MAP view.
- No login/authentication surface exists anywhere in the journey — the backend must
  use anonymous sessions (cookies), never a login page.

## 5. Change control

Any deviation from this document — a new screen, removed question, renamed label,
reordered step, moved error message, altered loading sequence, or changed result
layout — requires an explicit product-owner decision recorded as a new ADR before
implementation. Backend milestones verify against this contract; "the backend needed
it" is never a justification for a frontend change.
