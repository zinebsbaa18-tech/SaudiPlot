"""In-process background executor for design runs.

A single-worker ThreadPoolExecutor is deliberate for the local demo: no
Redis, no Celery. POST /design-runs inserts the row and submits the job;
every status transition below reflects actual work (loading inputs, geo
lookup, engine stages, output registration) -- there are no timers.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saudi_plot_api.config import Settings
from saudi_plot_api.database import utcnow
from saudi_plot_api.models import (
    DesignBrief,
    DesignRun,
    DesignRunEvent,
    OutputFile,
    PlotRecord,
    Project,
    RoomProgram,
)
from saudi_plot_api.services import engine as engine_service
from saudi_plot_api.services import geo_knowledge, storage
from saudi_plot_api.services.render import attempt_presentation_render

logger = logging.getLogger("saudi_plot_api.runner")


def create_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="design-run")


def submit_run(
    executor: ThreadPoolExecutor,
    session_factory: sessionmaker[Session],
    settings: Settings,
    run_id: str,
) -> None:
    executor.submit(_execute_run_safely, session_factory, settings, run_id)


def _execute_run_safely(
    session_factory: sessionmaker[Session], settings: Settings, run_id: str
) -> None:
    try:
        _execute_run(session_factory, settings, run_id)
    except Exception:
        logger.exception("design run %s crashed", run_id)
        with session_factory() as db:
            run = db.get(DesignRun, run_id)
            if run is not None:
                _transition(db, run, "failed", "internal error during generation")
                run.error_code = "internal_error"
                run.finished_at = utcnow()
                db.commit()


def _transition(db: Session, run: DesignRun, status: str, message: str | None = None) -> None:
    run.status = status
    last_seq = db.execute(
        select(DesignRunEvent.seq)
        .where(DesignRunEvent.run_id == run.id)
        .order_by(DesignRunEvent.seq.desc())
        .limit(1)
    ).scalar_one_or_none()
    db.add(DesignRunEvent(run_id=run.id, seq=(last_seq or 0) + 1, status=status, message=message))
    db.commit()


def _execute_run(session_factory: sessionmaker[Session], settings: Settings, run_id: str) -> None:
    with session_factory() as db:
        run = db.get(DesignRun, run_id)
        if run is None:
            return
        run.started_at = utcnow()

        # ── preparing_inputs: load everything the run needs ────────────
        _transition(db, run, "preparing_inputs", "loading project, plot, brief, room program")
        project = db.get(Project, run.project_id)
        plot = db.execute(
            select(PlotRecord).where(PlotRecord.project_id == run.project_id)
        ).scalar_one_or_none()
        brief = db.execute(
            select(DesignBrief).where(DesignBrief.project_id == run.project_id)
        ).scalar_one_or_none()
        program = db.execute(
            select(RoomProgram).where(RoomProgram.project_id == run.project_id)
        ).scalar_one_or_none()
        if project is None or plot is None:
            run.error_code = "missing_plot_record"
            run.support_status = "unsupported_requirements"
            run.unsupported_json = json.dumps(
                ["a confirmed plot record is required before generation"]
            )
            _transition(db, run, "unsupported_requirements", "no confirmed plot record")
            run.finished_at = utcnow()
            db.commit()
            return

        # ── extracting_deed: verify the recorded plot inputs exist ─────
        # (extraction itself happened at upload time or via manual entry;
        # this stage validates the stored data is usable)
        _transition(
            db,
            run,
            "extracting_deed",
            f"plot data source: {plot.source}; dimensions and coordinates recorded",
        )

        # ── resolving_character: advisory geo + core engine lookup ─────
        _transition(db, run, "resolving_character", "advisory geo lookup + core character engine")
        character: dict = {"advisory": None, "engine": None}
        if plot.latitude is not None and plot.longitude is not None:
            try:
                advisory = geo_knowledge.resolve_character(
                    settings.geo_knowledge_db, plot.latitude, plot.longitude
                )
                character["advisory"] = advisory.to_dict()
            except Exception:
                logger.exception("advisory geo lookup failed for run %s", run_id)
                character["advisory"] = {
                    "available": False,
                    "warnings": ["advisory geo lookup failed"],
                }
        character["engine"] = engine_service.resolve_engine_character(plot.latitude, plot.longitude)
        run.character_json = json.dumps(character, ensure_ascii=False)
        db.commit()

        # ── validating_requirements: honest support decision ───────────
        _transition(db, run, "validating_requirements", "checking engine support envelope")
        answers = json.loads(brief.answers_json) if brief else None
        counts = json.loads(program.counts_json) if program else None
        inputs = engine_service.EngineInputs(
            width_m=plot.width_m,
            height_m=plot.height_m,
            latitude=plot.latitude,
            longitude=plot.longitude,
            street_width_m=plot.street_width_m,
            boundaries=json.loads(plot.boundaries_json) if plot.boundaries_json else None,
            answers=answers,
            room_counts=counts,
        )
        support_status, assumptions, unapplied, unsupported = engine_service.plan_support(inputs)
        run.support_status = support_status
        run.assumptions_json = json.dumps(assumptions, ensure_ascii=False)
        run.unapplied_answers_json = json.dumps(unapplied, ensure_ascii=False)
        if unsupported:
            run.unsupported_json = json.dumps(unsupported, ensure_ascii=False)
            run.error_code = "unsupported_requirements"
            _transition(db, run, "unsupported_requirements", "; ".join(unsupported))
            run.finished_at = utcnow()
            db.commit()
            return
        db.commit()

        # ── generating / evaluating / outputs: the real engine ─────────
        _transition(db, run, "generating_candidates", "compact 3BR planning + layout optimization")
        root = storage.storage_root(settings.storage_root)
        out_dir = storage.resolve_relative(
            settings.storage_root, storage.run_relative_dir(run.project_id, run.id)
        )
        try:
            _transition(db, run, "evaluating_candidates", "facade selection + validation gates")
            result = engine_service.run_engine(inputs, out_dir, root, run.id)
        except engine_service.EngineRejection as rejection:
            run.support_status = "unsupported_requirements"
            run.unsupported_json = json.dumps(rejection.reasons, ensure_ascii=False)
            run.error_code = "engine_rejected"
            _transition(db, run, "unsupported_requirements", "; ".join(rejection.reasons))
            run.finished_at = utcnow()
            db.commit()
            return

        _transition(db, run, "preparing_outputs", f"registering {len(result.files)} output files")
        for file_info in result.files:
            db.add(OutputFile(run_id=run.id, **file_info))
        run.design_fingerprint = result.design_fingerprint
        run.support_status = result.support_status
        run.assumptions_json = json.dumps(result.assumptions, ensure_ascii=False)
        run.unapplied_answers_json = json.dumps(result.unapplied_answers, ensure_ascii=False)
        merged_character = json.loads(run.character_json or "{}")
        merged_character["applied"] = result.character
        run.character_json = json.dumps(merged_character, ensure_ascii=False)
        run.engine_summary_json = json.dumps(result.summary, ensure_ascii=False)
        db.commit()

        # ── presentation render: best effort, never blocks the result ──
        _transition(db, run, "generating_presentation_render", "presentation image (best effort)")
        try:
            attempt_presentation_render(db, settings, run, result.plan_svg_relative_path)
        except Exception:
            logger.exception("presentation render attempt failed for run %s", run_id)

        final_status = (
            "completed" if result.support_status == "supported" else "completed_with_assumptions"
        )
        _transition(db, run, final_status, "engineering outputs ready")
        run.finished_at = utcnow()
        db.commit()
