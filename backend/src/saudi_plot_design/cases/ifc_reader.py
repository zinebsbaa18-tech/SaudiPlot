"""IFC4 architectural extraction (M6A) - semantic data only.

Reads exactly the architectural entities the case library needs (project,
site, building, storeys, spaces, walls, slabs, doors, windows, openings,
space boundaries, materials). No geometry tessellation, no structural or MEP
ingestion. Missing source data produces explicit warnings - never fabricated
values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from saudi_plot_design.model import SpdInputError

SUPPORTED_SCHEMA_PREFIX = "IFC4"


@dataclass
class RawSpace:
    global_id: str
    name: str
    long_name: str | None
    level_id: str
    area_m2: float | None
    height_m: float | None
    external: bool = False


@dataclass
class RawWall:
    global_id: str
    name: str
    level_id: str
    start: tuple[float, float] | None
    end: tuple[float, float] | None
    length_m: float | None
    thickness_m: float | None
    height_m: float | None
    is_external: bool
    material: str | None


@dataclass
class RawSlab:
    global_id: str
    name: str
    level_id: str
    thickness_m: float | None
    area_m2: float | None


@dataclass
class RawOpening:
    global_id: str
    name: str
    kind: str  # door | window
    level_id: str
    host_wall_id: str | None
    width_m: float | None
    height_m: float | None
    sill_height_m: float | None


@dataclass
class RawLevel:
    global_id: str
    name: str
    elevation_m: float | None  # None + warning when the source has neither
    # an Elevation attribute nor a placement


@dataclass
class IfcExtraction:
    schema: str
    unit_scale_to_m: float
    levels: list[RawLevel] = field(default_factory=list)
    spaces: list[RawSpace] = field(default_factory=list)
    walls: list[RawWall] = field(default_factory=list)
    slabs: list[RawSlab] = field(default_factory=list)
    openings: list[RawOpening] = field(default_factory=list)
    wall_to_spaces: dict[str, list[str]] = field(default_factory=dict)
    space_external_flags: dict[str, bool] = field(default_factory=dict)
    site_note: str | None = None
    building_type: str = "unknown"
    warnings: list[str] = field(default_factory=list)


def read_ifc_case(path: str | Path) -> IfcExtraction:
    try:
        import ifcopenshell
        import ifcopenshell.util.element as element_util
        import ifcopenshell.util.placement as placement_util
        import ifcopenshell.util.unit as unit_util
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SpdInputError(
            "IfcOpenShell is required for case ingestion (pip install ifcopenshell)"
        ) from exc

    path = Path(path)
    if not path.is_file():
        raise SpdInputError(f"IFC model not found: {path}")
    model = ifcopenshell.open(str(path))
    schema = model.schema
    if not schema.upper().startswith(SUPPORTED_SCHEMA_PREFIX):
        raise SpdInputError(
            f"unsupported IFC schema '{schema}' - only IFC4-family models are "
            f"supported in M6A (export the project as IFC4)"
        )
    try:
        scale = float(unit_util.calculate_unit_scale(model))
    except Exception as exc:
        raise SpdInputError(f"could not resolve the IFC length unit: {exc}") from None
    if not math.isfinite(scale) or scale <= 0:
        raise SpdInputError(f"IFC length unit scale is not usable: {scale}")

    extraction = IfcExtraction(schema=schema, unit_scale_to_m=scale)
    seen_ids: set[str] = set()

    def register(global_id: str, what: str) -> None:
        if global_id in seen_ids:
            raise SpdInputError(f"duplicate IFC GlobalId '{global_id}' ({what})")
        seen_ids.add(global_id)

    projects = model.by_type("IfcProject")
    if not projects:
        raise SpdInputError("IFC model has no IfcProject - spatial hierarchy missing")
    storeys = sorted(model.by_type("IfcBuildingStorey"), key=lambda s: s.GlobalId)
    if not storeys:
        raise SpdInputError("IFC model has no IfcBuildingStorey - spatial hierarchy missing")
    buildings = model.by_type("IfcBuilding")
    if not buildings:
        extraction.warnings.append("no IfcBuilding found; hierarchy is incomplete")
    sites = model.by_type("IfcSite")
    if sites and getattr(sites[0], "Name", None):
        extraction.site_note = f"IfcSite '{sites[0].Name}'"

    for storey in storeys:
        register(storey.GlobalId, "IfcBuildingStorey")
        elevation_attr = getattr(storey, "Elevation", None)
        if elevation_attr is not None:
            elevation = round(float(elevation_attr) * scale, 6)
        elif storey.ObjectPlacement is not None:
            # The Elevation attribute is optional; the placement still carries
            # the real height. 0.0 must not be assumed silently.
            matrix = placement_util.get_local_placement(storey.ObjectPlacement)
            elevation = round(float(matrix[2][3]) * scale, 6)
            extraction.warnings.append(
                f"storey '{storey.Name or storey.GlobalId}' has no Elevation "
                f"attribute; {elevation} m derived from its placement"
            )
        else:
            # Neither attribute nor placement: the elevation is unknown and
            # must not be fabricated as 0.0.
            elevation = None
            extraction.warnings.append(
                f"storey '{storey.Name or storey.GlobalId}' has neither an "
                f"Elevation attribute nor a placement; elevation unavailable"
            )
        extraction.levels.append(
            RawLevel(storey.GlobalId, storey.Name or "unnamed level", elevation)
        )

    def storey_of(entity) -> str | None:
        container = element_util.get_container(entity)
        while container is not None and not container.is_a("IfcBuildingStorey"):
            container = element_util.get_container(container)
        return container.GlobalId if container is not None else None

    def quantity(entity, names: tuple[str, ...], *, should_inherit: bool = True) -> float | None:
        # Preferred names win across ALL quantity sets: a Gross value in an
        # earlier set must not shadow a Net value in a later one.
        qsets = list(
            element_util.get_psets(entity, qtos_only=True, should_inherit=should_inherit).values()
        )
        for name in names:
            for qset in qsets:
                if name in qset and isinstance(qset[name], (int, float)):
                    return float(qset[name])
        return None

    def pset_bool(entity, pset_name: str, prop: str) -> bool | None:
        psets = element_util.get_psets(entity, psets_only=True)
        if pset_name in psets and prop in psets[pset_name]:
            return bool(psets[pset_name][prop])
        return None

    for space in sorted(model.by_type("IfcSpace"), key=lambda s: s.GlobalId):
        register(space.GlobalId, "IfcSpace")
        level_id = _space_storey(space)
        if level_id is None:
            extraction.warnings.append(f"space '{space.GlobalId}' has no storey containment")
            continue
        area = quantity(space, ("NetFloorArea", "GrossFloorArea"))
        height = quantity(space, ("Height", "FinishCeilingHeight"))
        if area is None:
            extraction.warnings.append(
                f"space '{space.Name or space.GlobalId}' has no floor-area quantity "
                f"(export base quantities from the authoring tool)"
            )
        extraction.spaces.append(
            RawSpace(
                global_id=space.GlobalId,
                name=space.Name or "unnamed space",
                long_name=getattr(space, "LongName", None),
                level_id=level_id,
                area_m2=round(area * scale * scale, 6) if area is not None else None,
                height_m=round(height * scale, 6) if height is not None else None,
            )
        )

    # Dedupe by entity id: IfcWallStandardCase instances appear in both
    # by_type lists as the same entity. GlobalId collisions between distinct
    # entities must still be rejected, so dedupe must NOT use GlobalId.
    unique_walls = {
        wall.id(): wall
        for wall in list(model.by_type("IfcWall")) + list(model.by_type("IfcWallStandardCase"))
    }
    for wall in sorted(unique_walls.values(), key=lambda w: (w.GlobalId, w.id())):
        register(wall.GlobalId, "IfcWall")
        level_id = storey_of(wall)
        if level_id is None:
            extraction.warnings.append(f"wall '{wall.GlobalId}' has no storey containment")
            continue
        axis = _wall_axis(wall, placement_util, scale)
        if axis is None:
            extraction.warnings.append(
                f"wall '{wall.Name or wall.GlobalId}' has no axis representation"
            )
        thickness = quantity(wall, ("Width",))
        height = quantity(wall, ("Height",))
        length = quantity(wall, ("Length",))
        if thickness is None:
            thickness = _layer_thickness(wall, element_util)
        material = _material_name(wall, element_util)
        is_external = pset_bool(wall, "Pset_WallCommon", "IsExternal") or False
        start, end = axis if axis else (None, None)
        computed_length = math.dist(start, end) if start is not None and end is not None else None
        extraction.walls.append(
            RawWall(
                global_id=wall.GlobalId,
                name=wall.Name or "unnamed wall",
                level_id=level_id,
                start=start,
                end=end,
                length_m=round(length * scale, 6)
                if length is not None
                else (round(computed_length, 6) if computed_length else None),
                thickness_m=round(thickness * scale, 6) if thickness is not None else None,
                height_m=round(height * scale, 6) if height is not None else None,
                is_external=is_external,
                material=material,
            )
        )

    for slab in sorted(model.by_type("IfcSlab"), key=lambda s: s.GlobalId):
        register(slab.GlobalId, "IfcSlab")
        level_id = storey_of(slab)
        if level_id is None:
            extraction.warnings.append(f"slab '{slab.GlobalId}' has no storey containment")
            continue
        thickness = quantity(slab, ("Width", "Depth", "Thickness"))
        area = quantity(slab, ("NetArea", "GrossArea"))
        if thickness is None or area is None:
            missing = [
                label
                for label, value in (("thickness", thickness), ("area", area))
                if value is None
            ]
            extraction.warnings.append(
                f"slab '{slab.Name or slab.GlobalId}' has no {' or '.join(missing)} "
                f"quantity (export base quantities from the authoring tool)"
            )
        extraction.slabs.append(
            RawSlab(
                global_id=slab.GlobalId,
                name=slab.Name or "unnamed slab",
                level_id=level_id,
                thickness_m=round(thickness * scale, 6) if thickness is not None else None,
                area_m2=round(area * scale * scale, 6) if area is not None else None,
            )
        )

    wall_level_by_id = {wall.global_id: wall.level_id for wall in extraction.walls}
    lowest_level_id = min(
        extraction.levels,
        # Unknown elevations sort last so the fallback prefers a level whose
        # elevation is actually known.
        key=lambda level: (level.elevation_m is None, level.elevation_m or 0.0, level.global_id),
    ).global_id
    for kind, ifc_type in (("door", "IfcDoor"), ("window", "IfcWindow")):
        for entity in sorted(model.by_type(ifc_type), key=lambda e: e.GlobalId):
            register(entity.GlobalId, ifc_type)
            host = _host_wall(entity)
            if host is None:
                extraction.warnings.append(
                    f"{kind} '{entity.Name or entity.GlobalId}' has no host wall relationship"
                )
            level_id = storey_of(entity)
            if level_id is None:
                if host is not None and host in wall_level_by_id:
                    level_id = wall_level_by_id[host]
                    extraction.warnings.append(
                        f"{kind} '{entity.Name or entity.GlobalId}' has no storey "
                        f"containment; recorded on its host wall's storey"
                    )
                else:
                    level_id = lowest_level_id
                    extraction.warnings.append(
                        f"{kind} '{entity.Name or entity.GlobalId}' has no storey "
                        f"containment; recorded on the lowest storey for review"
                    )
            width = _opening_dimension(
                entity, kind, "OverallWidth", "Width", quantity, extraction.warnings
            )
            height = _opening_dimension(
                entity, kind, "OverallHeight", "Height", quantity, extraction.warnings
            )
            extraction.openings.append(
                RawOpening(
                    global_id=entity.GlobalId,
                    name=entity.Name or f"unnamed {kind}",
                    kind=kind,
                    level_id=level_id,
                    host_wall_id=host,
                    # Zero is preserved so validation can report the invalid
                    # source dimension instead of hiding it.
                    width_m=round(float(width) * scale, 6) if width is not None else None,
                    height_m=round(float(height) * scale, 6) if height is not None else None,
                    sill_height_m=None,
                )
            )

    extracted_space_ids = {space.global_id for space in extraction.spaces}
    extracted_wall_ids = {wall.global_id for wall in extraction.walls}
    dropped_boundary_refs: set[str] = set()
    externally_bounded_walls: set[str] = set()
    for boundary in model.by_type("IfcRelSpaceBoundary"):
        space = boundary.RelatingSpace
        element = boundary.RelatedBuildingElement
        if space is None or element is None or not space.is_a("IfcSpace"):
            continue
        is_wall = element.is_a("IfcWall") or element.is_a("IfcWallStandardCase")
        # Boundaries to entities that were skipped (e.g. missing storey
        # containment) would create dangling relationship references.
        if space.GlobalId not in extracted_space_ids or (
            is_wall and element.GlobalId not in extracted_wall_ids
        ):
            dropped = (
                space.GlobalId if space.GlobalId not in extracted_space_ids else element.GlobalId
            )
            if dropped not in dropped_boundary_refs:
                dropped_boundary_refs.add(dropped)
                extraction.warnings.append(
                    f"space boundary references '{dropped}' which was not "
                    f"extracted; boundary dropped"
                )
            continue
        if is_wall:
            extraction.wall_to_spaces.setdefault(element.GlobalId, [])
            if space.GlobalId not in extraction.wall_to_spaces[element.GlobalId]:
                extraction.wall_to_spaces[element.GlobalId].append(space.GlobalId)
        flag = getattr(boundary, "InternalOrExternalBoundary", None)
        # IFC4 defines EXTERNAL, EXTERNAL_EARTH, EXTERNAL_WATER, and
        # EXTERNAL_FIRE - all mark the boundary as external.
        if flag is not None and str(flag).startswith("EXTERNAL"):
            extraction.space_external_flags[space.GlobalId] = True
            if is_wall:
                externally_bounded_walls.add(element.GlobalId)
    # An EXTERNAL space boundary marks its wall as external even when the
    # exporter omitted the optional Pset_WallCommon.IsExternal property -
    # otherwise facade openings and entrances on that wall would be lost.
    for wall in extraction.walls:
        if not wall.is_external and wall.global_id in externally_bounded_walls:
            wall.is_external = True
    for spaces in extraction.wall_to_spaces.values():
        spaces.sort()
    if not extraction.wall_to_spaces:
        extraction.warnings.append(
            "no IfcRelSpaceBoundary relationships found - adjacency and circulation "
            "graphs will be empty (re-export with space boundaries enabled)"
        )

    if buildings and getattr(buildings[0], "Name", None):
        extraction.building_type = str(buildings[0].Name)
    return extraction


def _space_storey(space) -> str | None:
    for rel in getattr(space, "Decomposes", []) or []:
        parent = rel.RelatingObject
        if parent is not None and parent.is_a("IfcBuildingStorey"):
            return parent.GlobalId
    return None


def _opening_dimension(entity, kind, attribute, quantity_name, quantity, warnings):
    """Prefer the IFC occurrence attribute, with an explicit source-QTO fallback.

    Some exporters write zero into the optional OverallWidth/OverallHeight
    attributes while also exporting valid occurrence base quantities. A
    positive source quantity is usable evidence; geometry is never guessed or
    tessellated here. The warning keeps the substitution visible to reviewers.
    """
    value = getattr(entity, attribute, None)
    if value is not None and math.isfinite(float(value)) and float(value) > 0:
        return float(value)
    qto_value = quantity(entity, (quantity_name,), should_inherit=False)
    if qto_value is not None and math.isfinite(qto_value) and qto_value > 0:
        warnings.append(
            f"{kind} '{entity.Name or entity.GlobalId}' has unusable {attribute} "
            f"value {value!r}; used positive IFC occurrence quantity "
            f"'{quantity_name}' instead"
        )
        return qto_value
    return value


def _host_wall(entity) -> str | None:
    for rel in getattr(entity, "FillsVoids", []) or []:
        opening = rel.RelatingOpeningElement
        for void_rel in getattr(opening, "VoidsElements", []) or []:
            host = void_rel.RelatingBuildingElement
            if host is not None and (host.is_a("IfcWall") or host.is_a("IfcWallStandardCase")):
                return host.GlobalId
    return None


def _wall_axis(wall, placement_util, scale: float):
    representation = getattr(wall, "Representation", None)
    if representation is None:
        return None
    for rep in representation.Representations or []:
        if rep.RepresentationIdentifier != "Axis":
            continue
        for item in rep.Items or []:
            ends = _curve_endpoints(item)
            if ends is None:
                continue
            matrix = placement_util.get_local_placement(wall.ObjectPlacement)
            points = []
            for x, y in ends:
                wx = matrix[0][0] * x + matrix[0][1] * y + matrix[0][3]
                wy = matrix[1][0] * x + matrix[1][1] * y + matrix[1][3]
                points.append((round(wx * scale, 6), round(wy * scale, 6)))
            return points[0], points[1]
    return None


def _curve_endpoints(item) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """First and last 2D point of a legacy IfcPolyline or IFC4
    IfcIndexedPolyCurve axis item."""
    if item.is_a("IfcPolyline") and len(item.Points) >= 2:
        first, last = item.Points[0], item.Points[-1]
        return (
            (float(first.Coordinates[0]), float(first.Coordinates[1])),
            (float(last.Coordinates[0]), float(last.Coordinates[1])),
        )
    if item.is_a("IfcIndexedPolyCurve"):
        point_list = getattr(item, "Points", None)
        coords = list(getattr(point_list, "CoordList", []) or []) if point_list else []
        if len(coords) >= 2:
            first, last = coords[0], coords[-1]
            return (
                (float(first[0]), float(first[1])),
                (float(last[0]), float(last[1])),
            )
    return None


def _layer_thickness(wall, element_util) -> float | None:
    material = element_util.get_material(wall)
    if material is None:
        return None
    layer_set = None
    if material.is_a("IfcMaterialLayerSetUsage"):
        layer_set = material.ForLayerSet
    elif material.is_a("IfcMaterialLayerSet"):
        layer_set = material
    if layer_set is None:
        return None
    return float(sum(layer.LayerThickness for layer in layer_set.MaterialLayers))


def _material_name(wall, element_util) -> str | None:
    material = element_util.get_material(wall)
    if material is None:
        return None
    if material.is_a("IfcMaterialLayerSetUsage"):
        layers = material.ForLayerSet.MaterialLayers
        if layers and layers[0].Material is not None:
            return layers[0].Material.Name
    if material.is_a("IfcMaterial"):
        return material.Name
    return None
