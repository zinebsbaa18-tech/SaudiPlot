"""Presentation renders: an AI-generated illustration of the engineering plan.

The render is a PRESENTATION ARTIFACT ONLY -- the SVG/PDF/DXF and structured
geometry remain the engineering source of truth, and a failed render never
invalidates a successful engineering result.

Input sanitization: the provider receives exactly the canonical plan SVG
produced by the deterministic engine (which contains geometry and generic
labels only -- no owner, deed, session, or location data) plus controlled
character/style instructions authored here. Nothing else is sent.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from saudi_plot_api.config import Settings
from saudi_plot_api.database import utcnow
from saudi_plot_api.models import DesignRun, PresentationRender
from saudi_plot_api.services import gemini, storage

logger = logging.getLogger("saudi_plot_api.render")


def _rasterize_svg(svg_path) -> bytes:
    """Plan SVG -> PNG bytes (cairosvg, no subprocess)."""
    import cairosvg

    return cairosvg.svg2png(url=str(svg_path))


# Controlled instruction text -- never user-supplied.
_STYLE_INSTRUCTIONS = (
    "Create a single photorealistic exterior visualization of a small Saudi villa "
    "based on this ground-floor plan drawing. Use a Najdi-inspired architectural "
    "character: warm sand-colored plaster walls, restrained rectangular openings, "
    "simple parapet details, soft late-afternoon light. Present it as a concept "
    "illustration; do not add text, labels, people, or logos."
)


def attempt_presentation_render(
    db: Session, settings: Settings, run: DesignRun, plan_svg_relative_path: str | None
) -> PresentationRender:
    """Create (or refresh) the render row for a run and try the provider."""
    render = PresentationRender(
        run_id=run.id,
        provider="gemini",
        model=settings.gemini_render_model,
        design_fingerprint=run.design_fingerprint,
    )
    db.add(render)

    if not settings.gemini_api_key:
        render.status = "unconfigured"
        render.error_code = "render_provider_unconfigured"
        db.commit()
        return render
    if plan_svg_relative_path is None:
        render.status = "failed"
        render.error_code = "plan_image_missing"
        db.commit()
        return render

    try:
        plan_path = storage.resolve_relative(settings.storage_root, plan_svg_relative_path)
        # Image providers accept raster input only -- rasterize the canonical
        # SVG to PNG before the call.
        plan_png = _rasterize_svg(plan_path)
        image_bytes, content_type = gemini.generate_presentation_render(
            settings, plan_png, "image/png", _STYLE_INSTRUCTIONS
        )
        extension = ".png" if "png" in content_type else ".jpg"
        stored_name = uuid.uuid4().hex + extension
        relative = storage.render_relative_path(run.project_id, run.id, stored_name)
        digest, size = storage.write_bytes(settings.storage_root, relative, image_bytes)
    except gemini.GeminiUnavailable:
        render.status = "unconfigured"
        render.error_code = "render_provider_unconfigured"
        db.commit()
        return render
    except gemini.GeminiError as error:
        # Quota exhaustion is not a hard failure: the engineering outputs
        # (PDF/DXF/SVG) are still valid. Treat it like "no key configured"
        # so the run reaches `completed_with_assumptions` instead of `failed`.
        if error.code == "quota_exceeded":
            render.status = "unconfigured"
            render.error_code = error.code
        else:
            render.status = "failed"
            render.error_code = error.code
        db.commit()
        return render
    except storage.StorageError:
        render.status = "failed"
        render.error_code = "plan_image_missing"
        db.commit()
        return render
    except Exception:
        # Any unexpected I/O or provider-client failure must still land the
        # row in a terminal state -- a render must never stay 'pending'.
        logger.exception("presentation render failed for run %s", run.id)
        render.status = "failed"
        render.error_code = "render_internal_error"
        db.commit()
        return render

    render.status = "completed"
    render.relative_path = relative
    render.content_type = content_type
    render.sha256 = digest
    render.size_bytes = size
    render.updated_at = utcnow()
    db.commit()
    return render
