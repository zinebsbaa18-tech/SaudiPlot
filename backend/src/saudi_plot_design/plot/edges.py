"""Manual edge classification and street-width input (PRD.md FR-2).

Classification is manual only - no automatic detection of any kind
(NOT_NOW.md). Classes: street, neighbor, path, unknown. The MVP slice
requires exactly one street edge.
"""

from __future__ import annotations

from saudi_plot_design.model import EdgeClass, EdgeRole, SpdInputError

MIN_STREET_WIDTH_M = 3.0
MAX_STREET_WIDTH_M = 60.0

_VALID_CLASSES = ", ".join(c.value for c in EdgeClass)


def parse_edge_classes(spec: str, expected_count: int) -> tuple[EdgeClass, ...]:
    """Parse a comma-separated classification like 'street,neighbor,neighbor,neighbor'.

    Item i classifies the edge from corner i+1 to corner i+2 (wrapping).
    """
    parts = [p.strip().lower() for p in spec.split(",")]
    if len(parts) != expected_count:
        raise SpdInputError(
            f"expected {expected_count} edge classes (one per boundary edge), got {len(parts)}"
        )
    classes = []
    for i, part in enumerate(parts):
        try:
            classes.append(EdgeClass(part))
        except ValueError:
            raise SpdInputError(
                f"edge {i + 1}: unknown class '{part}' (valid: {_VALID_CLASSES})"
            ) from None
    return tuple(classes)


def require_single_street(edges: tuple[EdgeClass, ...]) -> int:
    """The MVP slice requires exactly one street edge; return its index."""
    street_indexes = [i for i, e in enumerate(edges) if e is EdgeClass.STREET]
    if len(street_indexes) != 1:
        raise SpdInputError(
            f"exactly one edge must be classified 'street' in this MVP, got {len(street_indexes)}"
        )
    return street_indexes[0]


def validate_street_width(width_m: float) -> float:
    """Manual street width, plausibility-checked (demo bounds, not a regulation)."""
    try:
        width = float(width_m)
    except (TypeError, ValueError):
        raise SpdInputError(f"street width must be a number in meters, got {width_m!r}") from None
    if not (MIN_STREET_WIDTH_M <= width <= MAX_STREET_WIDTH_M):
        raise SpdInputError(
            f"street width {width:g} m is outside the plausible range "
            f"{MIN_STREET_WIDTH_M:g}-{MAX_STREET_WIDTH_M:g} m"
        )
    return width


def edge_roles(edges: tuple[EdgeClass, ...]) -> tuple[EdgeRole, ...]:
    """Setback roles for the 4-edge rectangular plot: street=front, opposite=rear."""
    if len(edges) != 4:
        raise SpdInputError(
            f"setback roles are defined for the 4-edge rectangular reference plot, "
            f"got {len(edges)} edges"
        )
    street = require_single_street(edges)
    roles = [EdgeRole.SIDE] * 4
    roles[street] = EdgeRole.FRONT
    roles[(street + 2) % 4] = EdgeRole.REAR
    return tuple(roles)
