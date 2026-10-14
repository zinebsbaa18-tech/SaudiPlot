"""Layered DXF export: M5 legacy layers plus owner-authorized M6.3 layers.

Every entity maps directly from a canonical object (no geometry
recalculation). Writing to a layer outside the fixed set, or an unsupported
geometry kind, is a structured export failure (SpdInputError). Doors and
windows carry their source ids as XDATA under the registered appid ``SPD``
plus nearby traceability text.

Placement convention (documented): plan/site at the plot's own local
coordinates (origin = plot corner 1); the elevation is drawn with its local
X/Z mapped to model-space X/Y at ``ELEVATION_OFFSET_X_M`` to the right of
the plot, ground line at y=0.
"""

from __future__ import annotations

import math
from pathlib import Path

import ezdxf

from saudi_plot_design.model import SpdInputError
from saudi_plot_design.output import DISCLAIMER

DXF_VERSION = "R2018"
ELEVATION_OFFSET_X_M = 30.0
APPID = "SPD"

PLAN_LAYERS = {
    "PLOT_BOUNDARY": 7,
    "PLOT_EDGE_LABELS": 8,
    "STREET": 1,
    "SETBACKS": 1,
    "BUILDABLE_ENVELOPE": 3,
    "BUILDING_FOOTPRINT": 5,
    "WALLS_EXTERNAL": 7,
    "WALLS_INTERNAL": 8,
    "DOORS": 30,
    "WINDOWS": 4,
    "ROOM_NAMES": 2,
    "ROOM_AREAS": 8,
    "DIMENSIONS": 6,
    "NORTH_ARROW": 2,
    "SITE_TEXT": 8,
}
ELEVATION_LAYERS = {
    "ELEVATION_WALL": 7,
    "ELEVATION_DOORS": 30,
    "ELEVATION_WINDOWS": 4,
    "ELEVATION_SHADING": 32,
    "ELEVATION_PARAPET": 2,
    "ELEVATION_PLINTH": 8,
    "ELEVATION_DECORATION": 32,
    "ELEVATION_FENCE": 8,  # created but unused: template omits fence (documented)
    "ELEVATION_GATE": 8,  # created but unused: template omits gate (documented)
    "ELEVATION_DIMENSIONS": 6,
    "ELEVATION_TEXT": 8,
}
AUDIT_LAYERS = {"TITLE_BLOCK": 7, "DISCLAIMERS": 1, "TRACEABILITY": 8}
PROFESSIONAL_LAYER_SPECS = {
    "A-PLOT": {"color": 7, "lineweight": 50, "linetype": "Continuous"},
    "A-SETB": {"color": 3, "lineweight": 18, "linetype": "DASHED"},
    "A-WALL-CUT": {"color": 7, "lineweight": 60, "linetype": "Continuous"},
    "A-WALL-PROJ": {"color": 8, "lineweight": 30, "linetype": "Continuous"},
    "A-DOOR": {"color": 30, "lineweight": 25, "linetype": "Continuous"},
    "A-WIND": {"color": 4, "lineweight": 25, "linetype": "Continuous"},
    "A-FURN": {"color": 8, "lineweight": 13, "linetype": "Continuous"},
    "A-FIXT": {"color": 6, "lineweight": 13, "linetype": "Continuous"},
    "A-DIMS": {"color": 6, "lineweight": 13, "linetype": "Continuous"},
    "A-ANNO": {"color": 2, "lineweight": 13, "linetype": "Continuous"},
    "A-HATCH": {"color": 9, "lineweight": 9, "linetype": "Continuous"},
    "A-TTLB": {"color": 7, "lineweight": 25, "linetype": "Continuous"},
    "A-REVIEW": {"color": 1, "lineweight": 25, "linetype": "Continuous"},
}
PROFESSIONAL_LAYERS = {name: int(spec["color"]) for name, spec in PROFESSIONAL_LAYER_SPECS.items()}
FIXED_LAYERS = {
    **PLAN_LAYERS,
    **ELEVATION_LAYERS,
    **AUDIT_LAYERS,
    **PROFESSIONAL_LAYERS,
}

_ELEMENT_LAYER = {
    "wall_body": "ELEVATION_WALL",
    "plinth": "ELEVATION_PLINTH",
    "parapet": "ELEVATION_PARAPET",
    "entrance_frame": "ELEVATION_DECORATION",
    "window_frame": "ELEVATION_DECORATION",
    "shading_canopy": "ELEVATION_SHADING",
    "decorative_band": "ELEVATION_DECORATION",
    "recessed_panel": "ELEVATION_DECORATION",
    "fence": "ELEVATION_FENCE",
    "gate": "ELEVATION_GATE",
}


def _write_dxf(
    path: str | Path,
    plot,
    envelope,
    rules,
    concept,
    match,
    pack_ref,
    selection,
    facade,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The fixed-meta option must cover ezdxf.new() too: the CREATED_BY_EZDXF
    # stamp is written at document creation, WRITTEN_BY_EZDXF at save.
    previous = ezdxf.options.write_fixed_meta_data_for_testing
    ezdxf.options.write_fixed_meta_data_for_testing = True
    try:
        return _write_document(
            path, plot, envelope, rules, concept, match, pack_ref, selection, facade
        )
    finally:
        ezdxf.options.write_fixed_meta_data_for_testing = previous


def _write_document(path, plot, envelope, rules, concept, match, pack_ref, selection, facade):
    doc = ezdxf.new(DXF_VERSION, setup=True)
    doc.header["$INSUNITS"] = 6  # meters
    # Deterministic output: pin the volatile header variables ezdxf stamps
    # (creation/update julian timestamps and document GUIDs).
    for var in ("$TDCREATE", "$TDUCREATE", "$TDUPDATE", "$TDUUPDATE", "$TDINDWG"):
        doc.header[var] = 0.0
    doc.header["$FINGERPRINTGUID"] = "{00000000-0000-0000-0000-000000000000}"
    doc.header["$VERSIONGUID"] = "{00000000-0000-0000-0000-000000000000}"
    doc.appids.add(APPID)
    for name, color in {**PLAN_LAYERS, **ELEVATION_LAYERS, **AUDIT_LAYERS}.items():
        doc.layers.add(name, color=color)
    for name, spec in PROFESSIONAL_LAYER_SPECS.items():
        doc.layers.add(
            name,
            color=int(spec["color"]),
            lineweight=int(spec["lineweight"]),
            linetype=str(spec["linetype"]),
        )
    msp = doc.modelspace()

    def add(kind: str, layer: str, *args, **kwargs):
        if layer not in FIXED_LAYERS:
            raise SpdInputError(
                f"export failure: layer '{layer}' is not in the fixed DXF layer set"
            )
        kwargs["dxfattribs"] = {**kwargs.get("dxfattribs", {}), "layer": layer}
        return getattr(msp, f"add_{kind}")(*args, **kwargs)

    _plan(add, msp, plot, envelope, rules, concept)
    _professional_plan(add, plot, envelope, concept)
    _elevation(add, msp, facade)
    _audit_text(add, plot, concept, match, pack_ref, selection, facade, rules)
    # Cross-process byte-determinism: ezdxf collects required CLASS records
    # at save time from a SET of entity types, so their order follows the
    # interpreter hash seed. Pre-register them here and pin a sorted order -
    # the save-time pass then adds nothing and the section is deterministic
    # for every caller (CLI and library alike).
    doc.classes.add_required_classes(doc.dxfversion)
    ordered = sorted(doc.classes.classes.items(), key=lambda item: item[0])
    doc.classes.classes.clear()
    doc.classes.classes.update(ordered)
    doc.saveas(path)
    return path


def _text(add, layer, text, x, y, height=0.35):
    entity = add("text", layer, text, dxfattribs={"height": height})
    entity.set_placement((x, y))
    return entity


def _plan(add, msp, plot, envelope, rules, concept):
    add("lwpolyline", "PLOT_BOUNDARY", plot.corners, close=True)
    for i in range(len(plot.corners)):
        (x1, y1), (x2, y2) = plot.edge_corners(i)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        label = f"edge {i + 1}: {plot.edges[i].value}"
        _text(add, "PLOT_EDGE_LABELS", label, mx - 1.5, my + (-1.2 if my <= 0.01 else 0.5))
        if plot.edges[i].value == "street":
            dx, dy = (x2 - x1), (y2 - y1)
            length = (dx**2 + dy**2) ** 0.5
            nx, ny = dy / length, -dx / length  # outward for CCW plot
            offset = 2.0
            add(
                "line",
                "STREET",
                (x1 + nx * offset, y1 + ny * offset),
                (x2 + nx * offset, y2 + ny * offset),
            )
            _text(
                add,
                "STREET",
                f"STREET (width {plot.street_width_m:g} m)",
                mx - 3.0,
                my + ny * offset * 1.6,
            )

    env = list(envelope.corners)
    add("lwpolyline", "BUILDABLE_ENVELOPE", env, close=True)
    exs = [c[0] for c in env]
    eys = [c[1] for c in env]
    pxs = [c[0] for c in plot.corners]
    pys = [c[1] for c in plot.corners]
    for label, p_a, p_b, text_at in (
        (f"front {rules.front_m:g} m", (sum(pxs) / 4, min(pys)), (sum(exs) / 4, min(eys)), None),
        (f"rear {rules.rear_m:g} m", (sum(pxs) / 4, max(pys)), (sum(exs) / 4, max(eys)), None),
        (f"side {rules.side_m:g} m", (min(pxs), sum(pys) / 4), (min(exs), sum(eys) / 4), None),
        (f"side {rules.side_m:g} m", (max(pxs), sum(pys) / 4), (max(exs), sum(eys) / 4), None),
    ):
        add("line", "SETBACKS", p_a, p_b)
        _text(add, "SETBACKS", label, (p_a[0] + p_b[0]) / 2 + 0.2, (p_a[1] + p_b[1]) / 2, 0.3)

    fp = concept.footprint
    add(
        "lwpolyline",
        "BUILDING_FOOTPRINT",
        [(fp.min_x, fp.min_y), (fp.max_x, fp.min_y), (fp.max_x, fp.max_y), (fp.min_x, fp.max_y)],
        close=True,
    )
    for wall in concept.walls:
        layer = "WALLS_EXTERNAL" if wall.is_external else "WALLS_INTERNAL"
        add("line", layer, wall.start, wall.end)
    walls = {w.id: w for w in concept.walls}
    for door in concept.doors:
        _opening_plan(add, walls[door.wall_id], door.position_m, door.width_m, "DOORS", door.id)
    for window in concept.windows:
        _opening_plan(
            add, walls[window.wall_id], window.position_m, window.width_m, "WINDOWS", window.id
        )
    for room in concept.rooms:
        r = room.rect
        cx, cy = (r.min_x + r.max_x) / 2, (r.min_y + r.max_y) / 2
        _text(add, "ROOM_NAMES", room.name, cx - 1.0, cy + 0.25, 0.32)
        _text(add, "ROOM_AREAS", f"{room.area_m2:.1f} m2", cx - 1.0, cy - 0.55, 0.26)

    _dimension(add, (0, 0), (20, 0), (10, -2.5), "DIMENSIONS")
    _dimension(add, (0, 0), (0, 30), (-2.5, 15), "DIMENSIONS", angle=90)
    _dimension(add, (fp.min_x, fp.min_y), (fp.max_x, fp.min_y), (10, fp.min_y - 1.2), "DIMENSIONS")

    street_mid = 10.0
    add("line", "NORTH_ARROW", (street_mid, -4.5), (street_mid, -3.2))
    _text(add, "NORTH_ARROW", "STREET REF (north unknown)", street_mid - 3.0, -5.2, 0.3)
    _text(add, "SITE_TEXT", "site & floor plan - meters - DEMO concept", 0.0, 31.5, 0.4)


def _opening_plan(add, wall, position_m, width_m, layer, source_id):
    length = wall.length_m
    ux = (wall.end[0] - wall.start[0]) / length
    uy = (wall.end[1] - wall.start[1]) / length
    a = (wall.start[0] + ux * position_m, wall.start[1] + uy * position_m)
    b = (wall.start[0] + ux * (position_m + width_m), wall.start[1] + uy * (position_m + width_m))
    entity = add("line", layer, a, b)
    entity.set_xdata(APPID, [(1000, source_id), (1000, wall.id)])


def _point_on_wall(wall, offset_m):
    ux = (wall.end[0] - wall.start[0]) / wall.length_m
    uy = (wall.end[1] - wall.start[1]) / wall.length_m
    return wall.start[0] + ux * offset_m, wall.start[1] + uy * offset_m


def _professional_wall_segments(wall, openings):
    cursor = 0.0
    result = []
    for opening in sorted(openings, key=lambda item: (item.position_m, item.id)):
        if opening.position_m > cursor + 1e-6:
            result.append((cursor, opening.position_m))
        cursor = max(cursor, opening.position_m + opening.width_m)
    if cursor < wall.length_m - 1e-6:
        result.append((cursor, wall.length_m))
    return result


def _professional_door_symbol(concept, door, wall):
    rooms = {room.id: room for room in concept.rooms}
    hinge = _point_on_wall(wall, door.position_m)
    closed = _point_on_wall(wall, door.position_m + door.width_m)
    room_id = door.to_space if door.to_space != "exterior" else door.from_space
    room = rooms.get(room_id)
    ux = (wall.end[0] - wall.start[0]) / wall.length_m
    uy = (wall.end[1] - wall.start[1]) / wall.length_m
    left = (-uy, ux)
    right = (uy, -ux)
    if room is None:
        normal = left
    else:
        center = (
            (room.rect.min_x + room.rect.max_x) / 2,
            (room.rect.min_y + room.rect.max_y) / 2,
        )
        vector = center[0] - hinge[0], center[1] - hinge[1]
        normal = left if vector[0] * left[0] + vector[1] * left[1] >= 0 else right
    opened = (
        hinge[0] + normal[0] * door.width_m,
        hinge[1] + normal[1] * door.width_m,
    )
    return hinge, closed, opened


def _box_points(box):
    min_x, min_y, max_x, max_y = box
    return ((min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y))


def _boxes_intersect(first, second, gap=0.0):
    return not (
        first[2] + gap <= second[0]
        or second[2] + gap <= first[0]
        or first[3] + gap <= second[1]
        or second[3] + gap <= first[1]
    )


def _safe_world_box(room, width, height, forbidden):
    inset = 0.27
    usable = (
        room.rect.min_x + inset,
        room.rect.min_y + inset,
        room.rect.max_x - inset,
        room.rect.max_y - inset,
    )
    if usable[2] - usable[0] < width or usable[3] - usable[1] < height:
        return None
    candidates = (
        (usable[0], usable[1], usable[0] + width, usable[1] + height),
        (usable[2] - width, usable[1], usable[2], usable[1] + height),
        (usable[0], usable[3] - height, usable[0] + width, usable[3]),
        (usable[2] - width, usable[3] - height, usable[2], usable[3]),
    )
    return next(
        (
            box
            for box in candidates
            if not any(_boxes_intersect(box, other, gap=0.12) for other in forbidden)
        ),
        None,
    )


def _professional_door_clearance(concept):
    result = {room.id: [] for room in concept.rooms}
    walls = {wall.id: wall for wall in concept.walls}
    for door in sorted(concept.doors, key=lambda item: item.id):
        hinge, closed, opened = _professional_door_symbol(concept, door, walls[door.wall_id])
        room_id = door.to_space if door.to_space != "exterior" else door.from_space
        if room_id not in result:
            continue
        result[room_id].append(
            (
                min(hinge[0], closed[0], opened[0]) - 0.12,
                min(hinge[1], closed[1], opened[1]) - 0.12,
                max(hinge[0], closed[0], opened[0]) + 0.12,
                max(hinge[1], closed[1], opened[1]) + 0.12,
            )
        )
    return result


def _add_professional_box(add, layer, box, room_id, symbol_type):
    entity = add("lwpolyline", layer, _box_points(box), close=True)
    entity.set_xdata(APPID, [(1000, room_id), (1000, symbol_type)])
    return entity


def _professional_furniture(add, concept):
    """Add only deterministic room-contained symbols that clear schematic swings."""
    clearance = _professional_door_clearance(concept)
    symbol_by_type = {
        "bedroom": "bed",
        "master_bedroom": "bed",
        "maid_room": "maid_bed",
        "family_living": "sofa",
        "majlis": "majlis_seating",
        "dining": "dining_table",
        "kitchen": "kitchen_counter",
        "guest_wc": "wc",
        "master_bath": "shower",
        "shared_bath": "wash_basin",
        "laundry": "washer",
    }
    for room in sorted(concept.rooms, key=lambda item: item.id):
        symbol_type = symbol_by_type.get(room.type)
        if symbol_type is None:
            continue
        dimensions = {
            "bed": (min(1.6, room.rect.width * 0.42), min(2.1, room.rect.height * 0.48)),
            "maid_bed": (
                min(1.45, room.rect.width * 0.42),
                min(2.0, room.rect.height * 0.48),
            ),
            "sofa": (min(2.5, room.rect.width * 0.55), 0.63),
            "majlis_seating": (min(2.5, room.rect.width * 0.55), 0.63),
            "dining_table": (
                min(1.65, room.rect.width * 0.42),
                min(1.05, room.rect.height * 0.34),
            ),
            "kitchen_counter": (min(3.4, room.rect.width * 0.70), 0.42),
            "washer": (0.66, 0.66),
            "wc": (0.72, 0.78),
            "shower": (0.72, 0.78),
            "wash_basin": (0.72, 0.78),
        }
        box = _safe_world_box(room, *dimensions[symbol_type], clearance[room.id])
        if box is None:
            continue
        layer = (
            "A-FURN"
            if symbol_type
            in {
                "bed",
                "maid_bed",
                "sofa",
                "majlis_seating",
                "dining_table",
            }
            else "A-FIXT"
        )
        _add_professional_box(add, layer, box, room.id, symbol_type)
        if symbol_type == "bed":
            wardrobe = _safe_world_box(
                room,
                min(0.57, room.rect.width * 0.20),
                min(1.5, room.rect.height * 0.42),
                (*clearance[room.id], box),
            )
            if wardrobe is not None:
                _add_professional_box(add, "A-FURN", wardrobe, room.id, "wardrobe")


def _professional_plan(add, plot, envelope, concept):
    """M6.3 presentation hierarchy derived from the same canonical objects."""
    add("lwpolyline", "A-PLOT", plot.corners, close=True)
    add("lwpolyline", "A-SETB", envelope.corners, close=True)
    footprint = concept.footprint
    add(
        "lwpolyline",
        "A-WALL-PROJ",
        (
            (footprint.min_x, footprint.min_y),
            (footprint.max_x, footprint.min_y),
            (footprint.max_x, footprint.max_y),
            (footprint.min_x, footprint.max_y),
        ),
        close=True,
    )
    by_wall = {wall.id: [] for wall in concept.walls}
    door_tags = {
        door.id: f"D{index:02d}"
        for index, door in enumerate(sorted(concept.doors, key=lambda item: item.id), start=1)
    }
    window_tags = {
        window.id: f"W{index:02d}"
        for index, window in enumerate(sorted(concept.windows, key=lambda item: item.id), start=1)
    }
    room_tags = {
        room.id: f"R{index:02d}"
        for index, room in enumerate(sorted(concept.rooms, key=lambda item: item.id), start=1)
    }
    for opening in (*concept.doors, *concept.windows):
        by_wall[opening.wall_id].append(opening)
    for wall in sorted(concept.walls, key=lambda item: item.id):
        layer = "A-WALL-CUT" if wall.is_external else "A-WALL-PROJ"
        for start, end in _professional_wall_segments(wall, by_wall[wall.id]):
            entity = add("line", layer, _point_on_wall(wall, start), _point_on_wall(wall, end))
            entity.set_xdata(APPID, [(1000, wall.id)])

    walls = {wall.id: wall for wall in concept.walls}
    for door in sorted(concept.doors, key=lambda item: item.id):
        wall = walls[door.wall_id]
        hinge, closed, opened = _professional_door_symbol(concept, door, wall)
        leaf = add("line", "A-DOOR", hinge, opened)
        leaf.set_xdata(
            APPID,
            [(1000, door.id), (1000, wall.id), (1000, "SCHEMATIC_HANDING_NOT_AUTHORED")],
        )
        start_angle = math.degrees(math.atan2(closed[1] - hinge[1], closed[0] - hinge[0])) % 360
        end_angle = math.degrees(math.atan2(opened[1] - hinge[1], opened[0] - hinge[0])) % 360
        if (end_angle - start_angle) % 360 > 180:
            start_angle, end_angle = end_angle, start_angle
        arc = add(
            "arc",
            "A-DOOR",
            center=hinge,
            radius=door.width_m,
            start_angle=start_angle,
            end_angle=end_angle,
        )
        arc.set_xdata(APPID, [(1000, door.id), (1000, "SCHEMATIC_SWING")])
        _text(
            add,
            "A-ANNO",
            door_tags[door.id],
            (hinge[0] + closed[0]) / 2,
            (hinge[1] + closed[1]) / 2,
            0.18,
        )

    for window in sorted(concept.windows, key=lambda item: item.id):
        wall = walls[window.wall_id]
        a = _point_on_wall(wall, window.position_m)
        b = _point_on_wall(wall, window.position_m + window.width_m)
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = (dx**2 + dy**2) ** 0.5
        nx, ny = -dy / length * 0.06, dx / length * 0.06
        for sign in (-1, 1):
            line = add(
                "line",
                "A-WIND",
                (a[0] + sign * nx, a[1] + sign * ny),
                (b[0] + sign * nx, b[1] + sign * ny),
            )
            line.set_xdata(APPID, [(1000, window.id), (1000, wall.id)])
        _text(
            add,
            "A-ANNO",
            window_tags[window.id],
            (a[0] + b[0]) / 2,
            (a[1] + b[1]) / 2,
            0.16,
        )

    for room in sorted(concept.rooms, key=lambda item: item.id):
        rect = room.rect
        label = f"{room_tags[room.id]} {room.name.upper()} {room.area_m2:.1f}m2"
        label_height = min(0.18, (rect.width - 0.4) / (len(label) * 0.65))
        if label_height < 0.09:
            label = room_tags[room.id]
            label_height = min(0.18, (rect.width - 0.4) / (len(label) * 0.65))
        room_label = _text(
            add,
            "A-ANNO",
            label,
            rect.min_x + 0.2,
            (rect.min_y + rect.max_y) / 2,
            label_height,
        )
        room_label.set_xdata(APPID, [(1000, room.id), (1000, room_tags[room.id])])
        if room.wet:
            hatch = add(
                "lwpolyline",
                "A-HATCH",
                (
                    (rect.min_x + 0.12, rect.min_y + 0.12),
                    (rect.max_x - 0.12, rect.min_y + 0.12),
                    (rect.max_x - 0.12, rect.max_y - 0.12),
                    (rect.min_x + 0.12, rect.max_y - 0.12),
                ),
                close=True,
            )
            hatch.set_xdata(APPID, [(1000, room.id), (1000, "WET_ROOM")])
    _professional_furniture(add, concept)

    min_x = min(point[0] for point in plot.corners)
    max_x = max(point[0] for point in plot.corners)
    min_y = min(point[1] for point in plot.corners)
    max_y = max(point[1] for point in plot.corners)
    _dimension(
        add,
        (min_x, min_y),
        (max_x, min_y),
        ((min_x + max_x) / 2, min_y - 3.3),
        "A-DIMS",
    )
    _dimension(
        add,
        (min_x, min_y),
        (min_x, max_y),
        (min_x - 3.3, (min_y + max_y) / 2),
        "A-DIMS",
        angle=90,
    )
    _dimension(
        add,
        (footprint.min_x, footprint.min_y),
        (footprint.max_x, footprint.min_y),
        ((footprint.min_x + footprint.max_x) / 2, footprint.min_y - 1.8),
        "A-DIMS",
    )
    _text(add, "A-TTLB", "M6.3 PROFESSIONAL CONCEPT DRAWING | NOT FOR CONSTRUCTION", 0, -18, 0.3)
    _text(
        add,
        "A-REVIEW",
        "REVIEW STATUS: SEE QUALITY REPORT | NOT PROFESSIONAL APPROVAL",
        0,
        -18.8,
        0.25,
    )
    _text(
        add, "A-REVIEW", "DOOR SWINGS + FURNITURE ARE SCHEMATIC PRESENTATION ONLY", 0, -19.5, 0.22
    )


def _elevation(add, msp, facade):
    wall = facade.facade_wall
    ox = ELEVATION_OFFSET_X_M

    def p(x, z):
        return (ox + x, z)

    for element in facade.facade_elements:
        layer = _ELEMENT_LAYER.get(element.element_type)
        if layer is None:
            raise SpdInputError(
                f"export failure: unsupported facade element type '{element.element_type}'"
            )
        g = element.geometry
        if g["kind"] == "rect":
            points = [
                p(g["x"], g["z"]),
                p(g["x"] + g["w"], g["z"]),
                p(g["x"] + g["w"], g["z"] + g["h"]),
                p(g["x"], g["z"] + g["h"]),
            ]
        elif g["kind"] == "polygon":
            points = [p(x, z) for x, z in g["points"]]
        else:
            raise SpdInputError(
                f"export failure: unsupported geometry kind '{g['kind']}' on '{element.id}'"
            )
        entity = add("lwpolyline", layer, points, close=True)
        entity.set_xdata(APPID, [(1000, element.id), (1000, element.source_rule_id)])

    for opening in facade.facade_openings:
        layer = "ELEVATION_DOORS" if opening.opening_type == "door" else "ELEVATION_WINDOWS"
        points = [
            p(opening.x_start_m, opening.sill_elevation_m),
            p(opening.x_start_m + opening.width_m, opening.sill_elevation_m),
            p(opening.x_start_m + opening.width_m, opening.head_elevation_m),
            p(opening.x_start_m, opening.head_elevation_m),
        ]
        entity = add("lwpolyline", layer, points, close=True)
        entity.set_xdata(
            APPID,
            [
                (1000, opening.id),
                (1000, opening.source_plan_opening_id),
                (1000, opening.source_plan_wall_id),
            ],
        )
    add("line", "ELEVATION_WALL", p(-1.5, 0.0), p(wall.length_m + 1.5, 0.0))
    _dimension(
        add, p(0, 0), p(wall.length_m, 0), p(wall.length_m / 2, -1.8), "ELEVATION_DIMENSIONS"
    )
    _dimension(
        add,
        p(0, 0),
        p(0, wall.wall_height_m),
        p(-1.8, wall.wall_height_m / 2),
        "ELEVATION_DIMENSIONS",
        angle=90,
    )
    _text(
        add, "ELEVATION_TEXT", "front elevation - meters - DEMO", ox, wall.total_height_m + 1.0, 0.4
    )
    _text(add, "ELEVATION_TEXT", "finished ground 0.00", ox - 1.5, -0.8, 0.3)


def _dimension(add, p1, p2, text_mid, layer, angle: int = 0):
    dim = add("linear_dim", layer, base=text_mid, p1=p1, p2=p2, angle=angle)
    dim.render()


def _audit_text(add, plot, concept, match, pack_ref, selection, facade, rules):
    x, y = 0.0, -8.0
    title = [
        "SAUDI PLOT DESIGN STUDIO - DEMO CONCEPT EXPORT",
        f"project {plot.plot_id} | concept {concept.concept_id}",
        f"character zone {facade.character_match_zone_id} "
        f"(dataset {match.dataset_id} v{match.dataset_version}, {match.source_status})",
        f"style {pack_ref.name_en} / {pack_ref.name_ar} "
        f"({pack_ref.style_pack_id} v{pack_ref.version}, {pack_ref.status})",
        f"setback rule set {rules.id} ({rules.provenance})",
        f"primary street {selection.selected_plot_boundary_id} | facade {facade.facade_concept_id}",
    ]
    for i, line in enumerate(title):
        _text(add, "TITLE_BLOCK", line, x, y - i * 0.7, 0.42)
    _text(add, "DISCLAIMERS", DISCLAIMER, x, y - 4.5, 0.35)
    trace = [
        f"plot fp {plot.fingerprint} | concept fp {concept.fingerprint}",
        f"source walls: {', '.join(facade.facade_wall.source_plan_wall_ids)}",
    ] + [
        f"{o.id} <- plan {o.source_plan_opening_id} @ {o.source_plan_wall_id}"
        for o in facade.facade_openings
    ]
    for i, line in enumerate(trace):
        _text(add, "TRACEABILITY", line, x, y - 6.0 - i * 0.6, 0.3)
