"""Pricing endpoint: the configured demo price for the frozen price element."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from saudi_plot_api.dependencies import DbDep
from saudi_plot_api.errors import ApiError
from saudi_plot_api.models import PricingConfiguration
from saudi_plot_api.schemas import PricingResponse

router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])


@router.get("/current", response_model=PricingResponse)
def current_pricing(db: DbDep) -> PricingResponse:
    config = (
        db.execute(
            select(PricingConfiguration)
            .where(PricingConfiguration.active.is_(True))
            .order_by(PricingConfiguration.updated_at.desc())
        )
        .scalars()
        .first()
    )
    if config is None:
        raise ApiError(404, "pricing_not_configured", "No active pricing configuration exists.")
    return PricingResponse(label=config.label, currency=config.currency, amount=config.amount)
