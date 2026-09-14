from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


Prompt = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=2000,
    ),
]
FiveSeconds = Annotated[int, Field(strict=True, ge=5, le=5)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ImageAsset(Contract):
    asset_id: UUID
    mime_type: Literal["image/jpeg"] = "image/jpeg"
    width: Literal[1280] = 1280
    height: Literal[720] = 720
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class GenerationPlan(Contract):
    asset_id: UUID
    prompt: Prompt
    model: Literal["ltx-2-5-fast"] = "ltx-2-5-fast"
    duration: FiveSeconds = 5
    aspect_ratio: Literal["16:9"] = "16:9"
    audio: Literal["silent"] = "silent"

    @field_validator("duration", mode="before")
    @classmethod
    def validate_duration_type(cls, value: object) -> int:
        if type(value) is not int or value != 5:
            raise ValueError("duration must be the integer 5.")
        return value


class VideoEstimate(Contract):
    currency: Literal["USD"] = "USD"
    estimated_cost: float = 0.54
    generated_seconds: Literal[6] = 6
    delivered_seconds: Literal[5] = 5
    basis: str = "LTX direct API, 720p; excludes taxes."


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class VideoJob(Contract):
    job_id: UUID
    plan: GenerationPlan
    status: JobStatus
    comfy_id: str | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    message: str = ""
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class VideoResult(Contract):
    job_id: UUID
    status: Literal["completed"] = "completed"
    duration: FiveSeconds = 5
    aspect_ratio: Literal["16:9"] = "16:9"
    video_path: str
    video_url: str | None = None