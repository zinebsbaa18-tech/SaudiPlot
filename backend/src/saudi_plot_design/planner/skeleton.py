"""The single authored Compact 3BR skeleton (LOCKED_MVP_SCOPE.md capability 6).

Everything here is authored design data, not generated: room rectangles tile
the base footprint exactly, adjacencies are fixed, and doors/windows reference
authored room pairs and wall sides. The runtime (compact_3br.py) may only
place, rotate to approved orientations, mirror, and scale within the bounds
declared below. No search, no backtracking, no topology generation.

Local skeleton frame: origin at the front-left footprint corner, +x to the
right along the street, +y into the plot (front wall at y=0 faces the street).
"""

from __future__ import annotations

from dataclasses import dataclass

from saudi_plot_design.model import Zone

SKELETON_ID = "compact_3br"
SKELETON_VERSION = 1

BASE_WIDTH_M = 13.5  # along the street
BASE_DEPTH_M = 15.9  # into the plot

# Bounded per-axis resizing limits (approved transform set). The Y floor is
# 1.0 because the master-bath/laundry band is exactly 1.5 m deep - its
# authored MIN_DIMS narrow side; any vertical shrink violates it. The X axis
# tolerates 5% shrink (all narrow sides and door clearances still clear their
# minimums). No permitted transform can produce an invalid concept.
SCALE_X_MIN = 0.95
SCALE_X_MAX = 1.10
SCALE_Y_MIN = 1.0
SCALE_Y_MAX = 1.10

EXTERNAL_WALL_THICKNESS_M = 0.25
INTERNAL_WALL_THICKNESS_M = 0.15
WALL_HEIGHT_PLACEHOLDER_M = 3.0  # nominal; style pack governs facade height (M4)

# Nominal opening heights for the plan model; the style pack governs the
# elevation (ARCHITECTURE.md D5 note, STYLE_PACK_SCHEMA.md par.4).
WINDOW_SILL_M = 1.1
WINDOW_HEAD_M = 2.4

MIN_DOOR_EDGE_CLEARANCE_M = 0.1  # required clear wall length on each side of a door


@dataclass(frozen=True)
class RoomSpec:
    id: str
    type: str
    name: str
    rect: tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y), local frame
    zone: Zone
    priority: int
    habitable: bool
    wet: bool
    requires_external_wall: bool
    requires_window: bool
    access_via_room: str | None = None


@dataclass(frozen=True)
class DoorSpec:
    id: str
    from_space: str  # room id or "exterior"
    to_space: str
    width_m: float
    entrance_type: str | None = None  # authored main/majlis/service/secondary intent
    side: str | None = None  # local side (S/N/E/W) for exterior doors
    fraction: float = 0.5  # door center position along the host wall


@dataclass(frozen=True)
class WindowSpec:
    id: str
    room_id: str
    side: str  # local side of the room's external wall: S/N/E/W
    width_m: float
    fraction: float = 0.5


# Room rectangles tile the 13.5 x 15.9 base footprint exactly (no gaps,
# no overlaps); tests assert the tiling invariant.
ROOMS: tuple[RoomSpec, ...] = (
    RoomSpec(
        "majlis",
        "majlis",
        "Men's Majlis",
        (0.0, 0.0, 5.7, 4.5),
        Zone.PUBLIC,
        1,
        True,
        False,
        True,
        True,
    ),
    RoomSpec(
        "entry",
        "entry",
        "Entry Hall",
        (5.7, 0.0, 7.5, 2.7),
        Zone.CIRCULATION,
        4,
        False,
        False,
        True,
        False,
    ),
    RoomSpec(
        "guest_wc",
        "guest_wc",
        "Guest WC",
        (7.5, 0.0, 9.3, 2.7),
        Zone.PUBLIC,
        3,
        False,
        True,
        False,
        False,
    ),
    RoomSpec(
        "kitchen",
        "kitchen",
        "Closed Kitchen",
        (9.3, 0.0, 13.5, 2.7),
        Zone.WET_SERVICE,
        2,
        True,
        True,
        True,
        True,
    ),
    RoomSpec(
        "dining", "dining", "Dining", (7.5, 2.7, 13.5, 6.3), Zone.FAMILY, 2, True, False, True, True
    ),
    RoomSpec(
        "corridor",
        "corridor",
        "Corridor",
        (5.7, 2.7, 7.5, 15.9),
        Zone.CIRCULATION,
        4,
        False,
        False,
        False,
        False,
    ),
    RoomSpec(
        "family_living",
        "family_living",
        "Family Living",
        (0.0, 4.5, 5.7, 9.9),
        Zone.FAMILY,
        1,
        True,
        False,
        True,
        True,
    ),
    RoomSpec(
        "shared_bath",
        "shared_bath",
        "Shared Bathroom",
        (7.5, 6.3, 9.3, 8.7),
        Zone.PRIVATE,
        3,
        False,
        True,
        False,
        False,
    ),
    RoomSpec(
        "maid_room",
        "maid_room",
        "Maid Room",
        (9.3, 6.3, 13.5, 8.7),
        Zone.WET_SERVICE,
        3,
        True,
        False,
        True,
        True,
    ),
    RoomSpec(
        "bedroom_2",
        "bedroom",
        "Bedroom 2",
        (7.5, 8.7, 13.5, 12.3),
        Zone.PRIVATE,
        1,
        True,
        False,
        True,
        True,
    ),
    RoomSpec(
        "bedroom_3",
        "bedroom",
        "Bedroom 3",
        (7.5, 12.3, 13.5, 15.9),
        Zone.PRIVATE,
        1,
        True,
        False,
        True,
        True,
    ),
    RoomSpec(
        "master_bath",
        "master_bath",
        "Master Bathroom",
        (0.0, 9.9, 2.4, 11.4),
        Zone.PRIVATE,
        3,
        False,
        True,
        False,
        False,
        "master_bedroom",
    ),
    RoomSpec(
        "laundry",
        "laundry",
        "Laundry / Service",
        (2.4, 9.9, 5.7, 11.4),
        Zone.WET_SERVICE,
        3,
        False,
        True,
        False,
        False,
    ),
    RoomSpec(
        "master_bedroom",
        "master_bedroom",
        "Master Bedroom",
        (0.0, 11.4, 5.7, 15.9),
        Zone.PRIVATE,
        1,
        True,
        False,
        True,
        True,
    ),
)

# Fixed pre-authored entrance options + internal door set. Fractions position
# the door center along its host wall; entrance doors host on the named side.
DOORS: tuple[DoorSpec, ...] = (
    DoorSpec("d_main", "exterior", "entry", 1.1, entrance_type="main", side="S"),
    DoorSpec(
        "d_majlis_ext", "exterior", "majlis", 1.0, entrance_type="majlis", side="S", fraction=0.8
    ),
    DoorSpec("d_majlis_entry", "majlis", "entry", 0.9),
    DoorSpec("d_entry_corridor", "entry", "corridor", 1.5),
    DoorSpec("d_guest_wc", "entry", "guest_wc", 0.8),
    DoorSpec("d_dining", "corridor", "dining", 1.0),
    DoorSpec("d_kitchen", "dining", "kitchen", 0.9, fraction=0.3),
    DoorSpec("d_living", "corridor", "family_living", 1.2),
    DoorSpec("d_shared_bath", "corridor", "shared_bath", 0.8),
    DoorSpec("d_maid", "dining", "maid_room", 0.8, fraction=0.75),
    DoorSpec("d_bedroom_2", "corridor", "bedroom_2", 0.9),
    DoorSpec("d_bedroom_3", "corridor", "bedroom_3", 0.9, fraction=0.35),
    DoorSpec("d_laundry", "corridor", "laundry", 0.8),
    DoorSpec("d_master", "corridor", "master_bedroom", 0.9, fraction=0.3),
    DoorSpec("d_master_bath", "master_bedroom", "master_bath", 0.8, fraction=0.3),
)

WINDOWS: tuple[WindowSpec, ...] = (
    # Fractions keep >= 0.3 m between openings on the street facade (the M4
    # facade composition minimum) - authored here, never adjusted downstream.
    WindowSpec("w_majlis_1", "majlis", "S", 1.2, fraction=0.2),
    WindowSpec("w_majlis_2", "majlis", "S", 1.2, fraction=0.5),
    WindowSpec("w_kitchen", "kitchen", "S", 1.2),
    WindowSpec("w_dining", "dining", "E", 1.2),
    WindowSpec("w_living_1", "family_living", "W", 1.2, fraction=0.3),
    WindowSpec("w_living_2", "family_living", "W", 1.2, fraction=0.7),
    WindowSpec("w_maid", "maid_room", "E", 1.0),
    WindowSpec("w_bedroom_2", "bedroom_2", "E", 1.2),
    WindowSpec("w_bedroom_3", "bedroom_3", "E", 1.2),
    WindowSpec("w_master_1", "master_bedroom", "W", 1.2),
    WindowSpec("w_master_2", "master_bedroom", "N", 1.2, fraction=0.3),
)

# Minimum livability dimensions per room type (authored design minimums for
# this skeleton - demo values, not municipal regulations).
MIN_DIMS: dict[str, tuple[float, float]] = {
    # type: (min_area_m2, min_narrow_side_m)
    "majlis": (16.0, 3.5),
    "entry": (3.0, 1.2),
    "guest_wc": (1.8, 1.2),
    "kitchen": (7.0, 2.4),
    "dining": (9.0, 2.7),
    "corridor": (6.0, 1.05),
    "family_living": (16.0, 3.5),
    "shared_bath": (3.0, 1.5),
    "maid_room": (5.0, 1.8),
    "bedroom": (10.0, 2.7),
    "master_bath": (3.0, 1.5),
    "laundry": (3.0, 1.5),
    "master_bedroom": (12.0, 3.0),
}

# Required program: every one of these room ids exactly once.
REQUIRED_ROOM_IDS: tuple[str, ...] = tuple(spec.id for spec in ROOMS)

# Authored plumbing relationships: each wet room's designated plumbing partner
# wall. A wet room must share a wall with its partner (adjacent stack) - the
# shared_bath stacks on an authored service shaft in its corridor-side wall.
PLUMBING_PARTNERS: dict[str, str] = {
    "guest_wc": "kitchen",
    "kitchen": "guest_wc",
    "master_bath": "laundry",
    "laundry": "master_bath",
    "shared_bath": "corridor",  # authored service shaft in the corridor wall
}

ASSUMPTIONS: tuple[str, ...] = (
    "Wall thicknesses are schematic (0.25 m external / 0.15 m internal); no structural design.",
    "Wall and opening heights are nominal placeholders; the style pack governs the facade at elevation stage (M4).",
    "Parking and garden are site-level reserved zones in the remaining envelope area; not detailed in this milestone.",
    "North direction is unknown in local plot coordinates; the street direction is the drawing reference.",
    "Maid room is accessed through the dining area (authored service path of this skeleton).",
    "Master bathroom is an en-suite reached through the master bedroom (authored exemption).",
    "DEMO design data - authored for pipeline development, not derived from official Saudi guidelines.",
)
