"""HTTP request/response models and the stable error envelope."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from pydantic import Field as PydanticField

from saudi_plot_api.models import FROZEN_FRONTEND_STEPS, PROJECT_STATUSES


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorEnvelope(BaseModel):
    """The stable error shape: no stack traces, SQL, file paths, or secrets."""

    error: ErrorBody
    request_id: str | None = None


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    status: str


def _validate_current_step(value: str | None) -> str | None:
    if value is not None and value not in FROZEN_FRONTEND_STEPS:
        allowed = ", ".join(FROZEN_FRONTEND_STEPS)
        raise ValueError(f"current_step must be one of the frozen frontend steps: {allowed}")
    return value


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_step: str | None = None

    _check_step = field_validator("current_step")(_validate_current_step)


class ProjectPatch(BaseModel):
    """Partial update. Omitted fields stay untouched; an explicit
    ``"current_step": null`` clears the step. ``status`` is never nullable."""

    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    current_step: str | None = None

    _check_step = field_validator("current_step")(_validate_current_step)

    @field_validator("status")
    @classmethod
    def _check_status(cls, value: str | None) -> str | None:
        if value is not None and value not in PROJECT_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(PROJECT_STATUSES)}")
        return value

    @model_validator(mode="after")
    def _status_not_explicit_null(self) -> ProjectPatch:
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status cannot be null")
        return self

    def updates(self) -> dict[str, Any]:
        """Only the fields the client actually sent."""
        return self.model_dump(exclude_unset=True)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    current_step: str | None
    schema_version: int


# ── Demo journey (W2) ───────────────────────────────────────────────────────


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    kind: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    status: str
    extraction_error_code: str | None
    created_at: datetime


class ExtractionResponse(BaseModel):
    document_id: str
    status: str
    extraction: dict[str, Any] | None
    error_code: str | None


class PlotUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width_m: float = PydanticField(gt=0, lt=10_000)
    height_m: float = PydanticField(gt=0, lt=10_000)
    latitude: float | None = PydanticField(default=None, ge=-90, le=90)
    longitude: float | None = PydanticField(default=None, ge=-180, le=180)
    rotation_deg: float = 0.0
    street_width_m: float | None = PydanticField(default=None, gt=0, le=100)
    boundaries: dict[str, str | None] | None = None
    source: str = "manual"
    corrections: dict[str, Any] | None = None

    @field_validator("source")
    @classmethod
    def _known_source(cls, value: str) -> str:
        if value not in ("manual", "deed_extraction", "map"):
            raise ValueError("source must be manual, deed_extraction, or map")
        return value

    @model_validator(mode="after")
    def _coordinates_come_in_pairs(self) -> PlotUpsert:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together or not at all")
        return self


class PlotResponse(BaseModel):
    id: str
    project_id: str
    width_m: float
    height_m: float
    latitude: float | None
    longitude: float | None
    rotation_deg: float
    street_width_m: float | None
    boundaries: dict[str, Any] | None
    source: str
    corrections: dict[str, Any] | None
    updated_at: datetime


class BriefUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: dict[str, Any]
    schema_version: int = 1


class BriefResponse(BaseModel):
    id: str
    project_id: str
    answers: dict[str, Any]
    character: dict[str, Any] | None
    schema_version: int
    updated_at: datetime


ROOM_PROGRAM_IDS = (
    "master",
    "bedroom",
    "bathroom",
    "closet",
    "living",
    "kitchen",
    "prepKitchen",
    "majlis",
    "dining",
    "guestBath",
    "driver",
    "laundry",
    "storage",
)


class RoomProgramUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counts: dict[str, int]

    @field_validator("counts")
    @classmethod
    def _known_rooms(cls, value: dict[str, int]) -> dict[str, int]:
        unknown = sorted(set(value) - set(ROOM_PROGRAM_IDS))
        if unknown:
            raise ValueError(f"unknown room ids: {', '.join(unknown)}")
        negative = sorted(k for k, v in value.items() if v < 0 or v > 20)
        if negative:
            raise ValueError(f"room counts must be between 0 and 20: {', '.join(negative)}")
        return value


class RoomProgramResponse(BaseModel):
    id: str
    project_id: str
    counts: dict[str, int]
    validation: dict[str, Any] | None
    updated_at: datetime


class DesignRunResponse(BaseModel):
    id: str
    project_id: str
    status: str
    support_status: str | None
    design_fingerprint: str | None
    error_code: str | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    events: list[dict[str, Any]]


class OutputFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    filename: str
    content_type: str
    sha256: str
    size_bytes: int
    shareable: bool


class DesignRunResult(BaseModel):
    id: str
    project_id: str
    status: str
    support_status: str | None
    design_fingerprint: str | None
    assumptions: list[str]
    unapplied_answers: list[dict[str, Any]]
    unsupported_requirements: list[str]
    character: dict[str, Any] | None
    engine_summary: dict[str, Any] | None
    files: list[OutputFileResponse]
    presentation_render_url: str | None = None
    render_pending: bool = False


class RenderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    status: str
    provider: str
    model: str | None
    design_fingerprint: str | None
    content_type: str | None
    sha256: str | None
    size_bytes: int | None
    error_code: str | None
    updated_at: datetime


class ShareResponse(BaseModel):
    share_token: str
    expires_at: datetime
    url_path: str


class PricingResponse(BaseModel):
    label: str
    currency: str
    amount: float
