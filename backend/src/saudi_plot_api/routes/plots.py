"""Plot record endpoints: the user-confirmed plot data for a project."""

from __future__ import annotations

import json

from fastapi import APIRouter
from sqlalchemy import select

from saudi_plot_api.database import utcnow
from saudi_plot_api.dependencies import (
    CurrentSessionDep,
    DbDep,
    TrustedOriginDep,
    owned_project,
)
from saudi_plot_api.errors import ApiError
from saudi_plot_api.models import PlotRecord
from saudi_plot_api.schemas import PlotResponse, PlotUpsert

router = APIRouter(prefix="/api/v1/projects/{project_id}/plot", tags=["plot"])


def _response(plot: PlotRecord) -> PlotResponse:
    return PlotResponse(
        id=plot.id,
        project_id=plot.project_id,
        width_m=plot.width_m,
        height_m=plot.height_m,
        latitude=plot.latitude,
        longitude=plot.longitude,
        rotation_deg=plot.rotation_deg,
        street_width_m=plot.street_width_m,
        boundaries=json.loads(plot.boundaries_json) if plot.boundaries_json else None,
        source=plot.source,
        corrections=json.loads(plot.corrections_json) if plot.corrections_json else None,
        updated_at=plot.updated_at,
    )


@router.put("", response_model=PlotResponse, dependencies=[TrustedOriginDep])
def upsert_plot(
    project_id: str, payload: PlotUpsert, session: CurrentSessionDep, db: DbDep
) -> PlotResponse:
    owned_project(db, session, project_id)
    plot = db.execute(
        select(PlotRecord).where(PlotRecord.project_id == project_id)
    ).scalar_one_or_none()
    if plot is None:
        plot = PlotRecord(project_id=project_id, width_m=payload.width_m, height_m=payload.height_m)
        db.add(plot)
    plot.width_m = payload.width_m
    plot.height_m = payload.height_m
    plot.latitude = payload.latitude
    plot.longitude = payload.longitude
    plot.rotation_deg = payload.rotation_deg
    plot.street_width_m = payload.street_width_m
    plot.boundaries_json = (
        json.dumps(payload.boundaries, ensure_ascii=False) if payload.boundaries else None
    )
    plot.source = payload.source
    plot.corrections_json = (
        json.dumps(payload.corrections, ensure_ascii=False) if payload.corrections else None
    )
    plot.updated_at = utcnow()
    db.commit()
    return _response(plot)


@router.get("", response_model=PlotResponse)
def read_plot(project_id: str, session: CurrentSessionDep, db: DbDep) -> PlotResponse:
    owned_project(db, session, project_id)
    plot = db.execute(
        select(PlotRecord).where(PlotRecord.project_id == project_id)
    ).scalar_one_or_none()
    if plot is None:
        raise ApiError(404, "plot_not_found", "No plot record exists for this project yet.")
    return _response(plot)
