"""Synthetic IFC4 test fixture builder for M6A ingestion tests.

TEST DATA ONLY. This builds a tiny, obviously artificial single-storey
layout so the ingestion pipeline can be exercised. It is NOT a professional
design, NOT an approved template, and must never be presented as one.

Deterministic GlobalIds are derived from fixed UUID integers so tests can
reference objects by id.
"""

from __future__ import annotations

import uuid
from pathlib import Path

GUIDS = {}


def guid(key: str) -> str:
    """Deterministic, valid IFC GlobalId per fixture object key."""
    import ifcopenshell.guid

    if key not in GUIDS:
        GUIDS[key] = ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL, key).hex)
    return GUIDS[key]


def build_test_ifc(
    path: Path,
    *,
    schema: str = "IFC4",
    milli: bool = False,
    omit_storey: bool = False,
    duplicate_id: bool = False,
    bad_area: bool = False,
    hostless_door: bool = False,
    omit_boundaries: bool = False,
    sensitive_names: bool = False,
    no_external_pset: bool = False,
    omit_area: bool = False,
    zero_width_door: bool = False,
    placement_elevation: bool = False,
    uncontained_host_wall: bool = False,
    multi_space_wall: bool = False,
    omit_elevation: bool = False,
    external_variant: str = "EXTERNAL",
    indexed_axis: bool = False,
    second_storey: bool = False,
    gross_first_qto: bool = False,
    zero_door_attributes_with_qto: bool = False,
) -> Path:
    """Write the synthetic model to ``path`` and return it."""
    import ifcopenshell
    import ifcopenshell.api

    run = ifcopenshell.api.run
    f = 1000.0 if milli else 1.0  # file length unit factor

    model = ifcopenshell.file(schema=schema)
    if schema != "IFC4":
        # Non-IFC4 variants only exercise the schema gate - the reader must
        # reject them before looking at any content.
        model.write(str(path))
        return path
    project = run("root.create_entity", model, ifc_class="IfcProject", name="SPD TEST FIXTURE")
    project.GlobalId = guid("project")
    length_unit = run(
        "unit.add_si_unit",
        model,
        unit_type="LENGTHUNIT",
        prefix="MILLI" if milli else None,
    )
    run("unit.assign_unit", model, units=[length_unit])
    ctx = run("context.add_context", model, context_type="Model")
    axis_ctx = run(
        "context.add_context",
        model,
        context_type="Model",
        context_identifier="Axis",
        target_view="GRAPH_VIEW",
        parent=ctx,
    )

    site = run("root.create_entity", model, ifc_class="IfcSite", name="TEST SITE")
    site.GlobalId = guid("site")
    building = run(
        "root.create_entity", model, ifc_class="IfcBuilding", name="test residential fixture"
    )
    building.GlobalId = guid("building")
    run("aggregate.assign_object", model, products=[site], relating_object=project)
    run("aggregate.assign_object", model, products=[building], relating_object=site)
    if omit_storey:
        model.write(str(path))
        return path
    storey = run(
        "root.create_entity",
        model,
        ifc_class="IfcBuildingStorey",
        name="Client Fulan Ground Floor" if sensitive_names else "Ground Floor",
    )
    storey.GlobalId = guid("storey")
    run("aggregate.assign_object", model, products=[storey], relating_object=building)
    if placement_elevation:
        import numpy

        matrix = numpy.eye(4)
        matrix[2][3] = 3.2 * f
        run("geometry.edit_object_placement", model, product=storey, matrix=matrix)
        storey.Elevation = None  # elevation only available via placement
    elif omit_elevation:
        storey.Elevation = None  # neither attribute nor placement
    else:
        storey.Elevation = 0.0

    def make_space(key: str, name: str, area_m2: float, long_name: str | None = None):
        space = run("root.create_entity", model, ifc_class="IfcSpace", name=name)
        space.GlobalId = guid(key)
        if long_name:
            space.LongName = long_name
        run("aggregate.assign_object", model, products=[space], relating_object=storey)
        if gross_first_qto and key == "sp_mystery":
            # A non-standard set with a Gross value listed BEFORE the
            # standard set carrying the preferred Net value.
            rogue_qto = run("pset.add_qto", model, product=space, name="AAA_CustomQuantities")
            run(
                "pset.edit_qto",
                model,
                qto=rogue_qto,
                properties={"GrossFloorArea": 99.0 * f * f},
            )
        if not (omit_area and key == "sp_mystery"):
            qto = run("pset.add_qto", model, product=space, name="Qto_SpaceBaseQuantities")
            run(
                "pset.edit_qto",
                model,
                qto=qto,
                properties={"NetFloorArea": area_m2 * f * f, "Height": 3.0 * f},
            )
        return space

    spaces = {
        "majlis": make_space("sp_majlis", "Majlis", 24.0, "مجلس الرجال"),
        "corridor": make_space("sp_corridor", "Entry Hall", 12.0),
        "living": make_space("sp_living", "Living Room", 28.0, "صالة معيشة"),
        "kitchen": make_space("sp_kitchen", "Kitchen", 14.0, "مطبخ"),
        "bathroom": make_space("sp_bathroom", "WC", 5.0, "حمام"),
        "bedroom": make_space("sp_bedroom", "Master Bedroom", -3.0 if bad_area else 18.0),
        "mystery": make_space(
            "sp_mystery",
            # Sensitive variant: private details in IFC text fields that the
            # anonymizer must scrub from every artifact.
            "Owner Mr Fulan Suite 0551234567" if sensitive_names else "Rm-07",
            9.0,
            long_name="villa client fulan@example.com" if sensitive_names else None,
        ),  # stays unknown on purpose
    }

    def make_wall(key, name, start, end, external, bounds, container=None):
        wall = run("root.create_entity", model, ifc_class="IfcWall", name=name)
        wall.GlobalId = guid(key)
        run(
            "spatial.assign_container",
            model,
            products=[wall],
            relating_structure=container or storey,
        )
        run("geometry.edit_object_placement", model, product=wall)
        if indexed_axis:
            point_list = model.create_entity(
                "IfcCartesianPointList2D",
                CoordList=[(start[0] * f, start[1] * f), (end[0] * f, end[1] * f)],
            )
            curve = model.create_entity("IfcIndexedPolyCurve", Points=point_list)
        else:
            points = [
                model.create_entity("IfcCartesianPoint", Coordinates=(x * f, y * f))
                for x, y in (start, end)
            ]
            curve = model.create_entity("IfcPolyline", Points=points)
        rep = model.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=axis_ctx,
            RepresentationIdentifier="Axis",
            RepresentationType="Curve2D",
            Items=[curve],
        )
        wall.Representation = model.create_entity(
            "IfcProductDefinitionShape", Representations=[rep]
        )
        pset = run("pset.add_pset", model, product=wall, name="Pset_WallCommon")
        run(
            "pset.edit_pset",
            model,
            pset=pset,
            properties={"IsExternal": external and not no_external_pset},
        )
        qto = run("pset.add_qto", model, product=wall, name="Qto_WallBaseQuantities")
        run(
            "pset.edit_qto",
            model,
            qto=qto,
            properties={"Width": 0.2 * f, "Height": 3.0 * f},
        )
        if not omit_boundaries:
            for space_key in bounds:
                model.create_entity(
                    "IfcRelSpaceBoundary",
                    GlobalId=guid(f"bnd_{key}_{space_key}"),
                    RelatingSpace=spaces[space_key],
                    RelatedBuildingElement=wall,
                    PhysicalOrVirtualBoundary="PHYSICAL",
                    InternalOrExternalBoundary=external_variant if external else "INTERNAL",
                )
        return wall

    walls = {
        "front": make_wall("w_front", "Front Wall", (0, 0), (14, 0), True, ["corridor"]),
        "majlis_ext": make_wall(
            "w_majlis_ext", "Majlis Front Wall", (0, 0), (0, 6), True, ["majlis"]
        ),
        "cor_liv": make_wall(
            "w_cor_liv", "Corridor-Living Wall", (4, 0), (4, 6), False, ["corridor", "living"]
        ),
        "cor_bed": make_wall(
            "w_cor_bed", "Corridor-Bedroom Wall", (0, 6), (4, 6), False, ["corridor", "bedroom"]
        ),
        "cor_bath": make_wall(
            "w_cor_bath", "Corridor-WC Wall", (2, 0), (2, 6), False, ["corridor", "bathroom"]
        ),
        "liv_kit": make_wall(
            "w_liv_kit", "Living-Kitchen Wall", (8, 0), (8, 6), False, ["living", "kitchen"]
        ),
        "kit_bath": make_wall(
            "w_kit_bath", "Kitchen-WC Wall", (2, 6), (8, 6), False, ["kitchen", "bathroom"]
        ),
        "maj_cor": make_wall(
            "w_maj_cor", "Majlis-Corridor Wall", (0, 3), (4, 3), False, ["majlis", "corridor"]
        ),
    }

    if multi_space_wall:
        # One long wall bounding three spaces: adjacency via it is ambiguous
        # without boundary-segment geometry.
        make_wall(
            "w_multi",
            "Long Shared Wall",
            (0, 12),
            (14, 12),
            False,
            ["bedroom", "kitchen", "living"],
        )

    def make_opening(key, name, ifc_class, host_key, width_m, height_m):
        entity = run("root.create_entity", model, ifc_class=ifc_class, name=name)
        entity.GlobalId = guid(key)
        run("spatial.assign_container", model, products=[entity], relating_structure=storey)
        entity.OverallWidth = width_m * f
        entity.OverallHeight = height_m * f
        if host_key is not None:
            opening = run(
                "root.create_entity", model, ifc_class="IfcOpeningElement", name=f"{name} opening"
            )
            opening.GlobalId = guid(f"op_{key}")
            run("feature.add_feature", model, feature=opening, element=walls[host_key])
            run("feature.add_filling", model, opening=opening, element=entity)
        return entity

    make_opening("d_main", "Main Entrance Door", "IfcDoor", "front", 1.0, 2.2)
    make_opening("d_majlis", "Majlis Guest Door", "IfcDoor", "majlis_ext", 1.0, 2.2)
    make_opening("d_cor_liv", "Living Door", "IfcDoor", "cor_liv", 0.9, 2.1)
    make_opening("d_cor_bed", "Bedroom Door", "IfcDoor", "cor_bed", 0.9, 2.1)
    make_opening("d_cor_bath", "WC Door", "IfcDoor", "cor_bath", 0.8, 2.1)
    make_opening("d_liv_kit", "Kitchen Door", "IfcDoor", "liv_kit", 0.9, 2.1)
    loose_door = make_opening(
        "d_hostless",
        "Loose Door",
        "IfcDoor",
        None if hostless_door else "cor_liv",
        0.0 if zero_width_door else 0.9,
        2.1,
    )
    if zero_door_attributes_with_qto:
        # Sanitized regression for a curtain-panel export pattern: the
        # occurrence attributes are zero while occurrence base quantities
        # contain the real source dimensions.
        loose_door.OverallWidth = 0.0
        loose_door.OverallHeight = 0.0
        qto = run("pset.add_qto", model, product=loose_door, name="Qto_DoorBaseQuantities")
        run(
            "pset.edit_qto",
            model,
            qto=qto,
            properties={"Width": 1.1225 * f, "Height": 2.38 * f},
        )
    make_opening("win_front", "Front Window", "IfcWindow", "front", 1.5, 1.2)
    make_opening("win_majlis", "Majlis Window", "IfcWindow", "majlis_ext", 1.5, 1.2)

    slab = run("root.create_entity", model, ifc_class="IfcSlab", name="Ground Slab")
    slab.GlobalId = guid("slab")
    run("spatial.assign_container", model, products=[slab], relating_structure=storey)

    if second_storey:
        storey2 = run(
            "root.create_entity", model, ifc_class="IfcBuildingStorey", name="First Floor"
        )
        storey2.GlobalId = guid("storey2")
        storey2.Elevation = 3.5 * f
        run("aggregate.assign_object", model, products=[storey2], relating_object=building)
        make_wall("w_upper", "Upper Wall", (0, 0), (10, 0), False, [], container=storey2)

    if duplicate_id:
        rogue = run("root.create_entity", model, ifc_class="IfcWall", name="Rogue Wall")
        rogue.GlobalId = guid("w_front")  # collides with the front wall
        run("spatial.assign_container", model, products=[rogue], relating_structure=storey)

    if uncontained_host_wall:
        # A door whose IFC host wall lacks storey containment: the wall is
        # skipped by extraction, so the door's host reference dangles.
        loose_wall = run("root.create_entity", model, ifc_class="IfcWall", name="Uncontained Wall")
        loose_wall.GlobalId = guid("w_uncontained")
        orphan = run("root.create_entity", model, ifc_class="IfcDoor", name="Orphan Host Door")
        orphan.GlobalId = guid("d_orphanhost")
        run("spatial.assign_container", model, products=[orphan], relating_structure=storey)
        orphan.OverallWidth = 0.9 * f
        orphan.OverallHeight = 2.1 * f
        opening = run(
            "root.create_entity", model, ifc_class="IfcOpeningElement", name="orphan opening"
        )
        opening.GlobalId = guid("op_orphan")
        run("feature.add_feature", model, feature=opening, element=loose_wall)
        run("feature.add_filling", model, opening=opening, element=orphan)
        # A boundary to the skipped wall: it must be dropped, not dangle.
        model.create_entity(
            "IfcRelSpaceBoundary",
            GlobalId=guid("bnd_uncontained_corridor"),
            RelatingSpace=spaces["corridor"],
            RelatedBuildingElement=loose_wall,
            PhysicalOrVirtualBoundary="PHYSICAL",
            InternalOrExternalBoundary="INTERNAL",
        )

    model.write(str(path))
    return path


def write_metadata(source_dir: Path, **overrides) -> Path:
    import json

    metadata = {
        "case_id": "case_001",
        "project_type": "residential_villa",
        "case_role": "residential_villa_template_candidate",
        "country": "SA",
        "city": "Riyadh",
        "district": "Test District",
        "architectural_character": "najdi",
        "source_format": "ifc4",
        "authoring_software": "test-fixture-builder",
        "number_of_floors": 1,
        "approval_status": "approved_for_testing_only",
        "approved_by": "Test Reviewer",
        "usage_rights_confirmed": True,
        "confidential": False,
        "anonymization_required": False,
        "quality_rating": "test_fixture",
        "notes": "Synthetic test fixture - not a professional design.",
    }
    metadata.update(overrides)
    path = source_dir / "case_metadata.json"
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_case_dir(tmp_path: Path, *, ifc_kwargs: dict | None = None, **meta_overrides) -> Path:
    source = tmp_path / "case_001"
    source.mkdir(parents=True, exist_ok=True)
    build_test_ifc(source / "model.ifc", **(ifc_kwargs or {}))
    write_metadata(source, **meta_overrides)
    return source
