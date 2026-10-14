"""Design brief, room program, and character resolution endpoints.

Every questionnaire answer is persisted verbatim. Whether the current planner
applies an answer geometrically is reported honestly by the design run
(``unapplied_answers``) -- nothing here claims otherwise.
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from sqlalchemy import select

from saudi_plot_api.database import utcnow
from saudi_plot_api.dependencies import (
    CurrentSessionDep,
    DbDep,
    SettingsDep,
    TrustedOriginDep,
    owned_project,
)
from saudi_plot_api.errors import ApiError
from saudi_plot_api.models import DesignBrief, PlotRecord, RoomProgram
from saudi_plot_api.schemas import (
    ROOM_PROGRAM_IDS,
    BriefResponse,
    BriefUpsert,
    RoomProgramResponse,
    RoomProgramUpsert,
)
from saudi_plot_api.services import engine as engine_service
from saudi_plot_api.services import geo_knowledge

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["brief"])


def _brief_response(brief: DesignBrief) -> BriefResponse:
    return BriefResponse(
        id=brief.id,
        project_id=brief.project_id,
        answers=json.loads(brief.answers_json),
        character=json.loads(brief.character_json) if brief.character_json else None,
        schema_version=brief.schema_version,
        updated_at=brief.updated_at,
    )


@router.put("/design-brief", response_model=BriefResponse, dependencies=[TrustedOriginDep])
def upsert_brief(
    project_id: str, payload: BriefUpsert, session: CurrentSessionDep, db: DbDep
) -> BriefResponse:
    owned_project(db, session, project_id)
    brief = db.execute(
        select(DesignBrief).where(DesignBrief.project_id == project_id)
    ).scalar_one_or_none()
    if brief is None:
        brief = DesignBrief(project_id=project_id, answers_json="{}")
        db.add(brief)
    brief.answers_json = json.dumps(payload.answers, ensure_ascii=False)
    brief.schema_version = payload.schema_version
    brief.updated_at = utcnow()
    db.commit()
    return _brief_response(brief)


@router.get("/design-brief", response_model=BriefResponse)
def read_brief(project_id: str, session: CurrentSessionDep, db: DbDep) -> BriefResponse:
    owned_project(db, session, project_id)
    brief = db.execute(
        select(DesignBrief).where(DesignBrief.project_id == project_id)
    ).scalar_one_or_none()
    if brief is None:
        raise ApiError(
            404, "design_brief_not_found", "No design brief exists for this project yet."
        )
    return _brief_response(brief)


def _program_response(program: RoomProgram) -> RoomProgramResponse:
    return RoomProgramResponse(
        id=program.id,
        project_id=program.project_id,
        counts=json.loads(program.counts_json),
        validation=json.loads(program.validation_json) if program.validation_json else None,
        updated_at=program.updated_at,
    )


def _validate_counts(counts: dict[str, int]) -> dict:
    """Structural validation plus the honest engine statement: the program is
    persisted, but the current planner generates the Compact 3BR skeleton."""
    issues = []
    if counts.get("master", 0) < 1:
        issues.append("at least one master bedroom is required")
    if counts.get("bathroom", 0) + counts.get("guestBath", 0) < 1:
        issues.append("at least one bathroom is required")
    if counts.get("living", 0) < 1:
        issues.append("at least one living space is required")
    total = sum(counts.values())
    if total > 40:
        issues.append("the total room count is implausibly large for a single villa")
    return {
        "valid": not issues,
        "issues": issues,
        "total_rooms": total,
        "engine_note": (
            "The room program is persisted and validated structurally. The current "
            "engine generates the authored Compact 3BR skeleton; it does not yet "
            "derive a layout from these counts."
        ),
    }


@router.put("/room-program", response_model=RoomProgramResponse, dependencies=[TrustedOriginDep])
def upsert_program(
    project_id: str, payload: RoomProgramUpsert, session: CurrentSessionDep, db: DbDep
) -> RoomProgramResponse:
    owned_project(db, session, project_id)
    program = db.execute(
        select(RoomProgram).where(RoomProgram.project_id == project_id)
    ).scalar_one_or_none()
    if program is None:
        program = RoomProgram(project_id=project_id, counts_json="{}")
        db.add(program)
    program.counts_json = json.dumps(payload.counts)
    program.validation_json = json.dumps(_validate_counts(payload.counts), ensure_ascii=False)
    program.updated_at = utcnow()
    db.commit()
    return _program_response(program)


@router.get("/room-program", response_model=RoomProgramResponse)
def read_program(project_id: str, session: CurrentSessionDep, db: DbDep) -> RoomProgramResponse:
    owned_project(db, session, project_id)
    program = db.execute(
        select(RoomProgram).where(RoomProgram.project_id == project_id)
    ).scalar_one_or_none()
    if program is None:
        raise ApiError(
            404, "room_program_not_found", "No room program exists for this project yet."
        )
    return _program_response(program)


@router.post("/room-program/validate", dependencies=[TrustedOriginDep])
def validate_program(
    project_id: str, payload: RoomProgramUpsert, session: CurrentSessionDep, db: DbDep
) -> dict:
    owned_project(db, session, project_id)
    missing = sorted(set(ROOM_PROGRAM_IDS) - set(payload.counts))
    result = _validate_counts(payload.counts)
    if missing:
        result["missing_ids"] = missing
    return result


@router.post("/resolve-character", dependencies=[TrustedOriginDep])
def resolve_character(
    project_id: str, session: CurrentSessionDep, db: DbDep, settings: SettingsDep
) -> dict:
    """Advisory character resolution for the project's stored coordinates.

    Combines the sbc_geo_knowledge advisory lookup with the core engine's own
    demo-zone recommendation; the result is stored on the design brief and
    always requires user confirmation. No legal/zoning claim is made.
    """
    owned_project(db, session, project_id)
    plot = db.execute(
        select(PlotRecord).where(PlotRecord.project_id == project_id)
    ).scalar_one_or_none()
    if plot is None or plot.latitude is None or plot.longitude is None:
        raise ApiError(
            422,
            "coordinates_required",
            "Plot coordinates must be saved before character resolution.",
        )

    advisory = geo_knowledge.resolve_character(
        settings.geo_knowledge_db, plot.latitude, plot.longitude
    ).to_dict()
    engine_view = engine_service.resolve_engine_character(plot.latitude, plot.longitude)
    result = {
        "advisory": advisory,
        "engine": engine_view,
        "installed_style_packs": ["najdi_demo_v1"],
        "generation_note": (
            "Only the najdi_demo_v1 pilot style pack is installed; generation applies "
            "it (with a recorded override reason when the location is outside its "
            "demo zone). Advisory knowledge is architectural-character guidance only."
        ),
        "requires_confirmation": True,
    }

    brief = db.execute(
        select(DesignBrief).where(DesignBrief.project_id == project_id)
    ).scalar_one_or_none()
    if brief is None:
        brief = DesignBrief(project_id=project_id, answers_json="{}")
        db.add(brief)
    brief.character_json = json.dumps(result, ensure_ascii=False)
    brief.updated_at = utcnow()
    db.commit()
    return result
