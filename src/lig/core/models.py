"""Request/result vocabulary shared by every backend and command."""

import secrets
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

MIN_SIZE = 256
MAX_SIZE = 4096
SIZE_STEP = 32
SEED_BITS = 32


def _nearest_valid_size(value: int) -> int:
    rounded = round(value / SIZE_STEP) * SIZE_STEP
    return max(MIN_SIZE, min(MAX_SIZE, rounded))


def _random_seed() -> int:
    return secrets.randbits(SEED_BITS)


class GenerateRequest(BaseModel):
    """Engine-agnostic text-to-image request; adapters map engine-specific knobs."""

    prompt: str = Field(min_length=1)
    width: int = 1024
    height: int = 1024
    steps: int = Field(default=40, ge=1)
    # Assigned when omitted so every result records a reproducible seed.
    seed: int = Field(default_factory=_random_seed, ge=0, lt=2**SEED_BITS)
    guidance: float | None = None  # None: the adapter picks its engine default
    negative_prompt: str | None = None
    transparent: bool = False

    @field_validator("width", "height")
    @classmethod
    def _check_size(cls, value: int, info) -> int:
        if value % SIZE_STEP or not MIN_SIZE <= value <= MAX_SIZE:
            raise ValueError(
                f"{info.field_name} {value} must be a multiple of {SIZE_STEP} "
                f"between {MIN_SIZE} and {MAX_SIZE}; "
                f"nearest valid size is {_nearest_valid_size(value)}"
            )
        return value


class EditRequest(GenerateRequest):
    """Image edit request: a generate request plus a reference image."""

    reference_image: Path
    reference_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    strength: float | None = Field(default=None, ge=0.0, le=1.0)


class WeightsUsed(BaseModel):
    name: str
    sha256: str


class Timings(BaseModel):
    load_s: float
    per_step_s: float
    total_s: float


class ImageResult(BaseModel):
    png: bytes
    request: GenerateRequest
    engine: str
    engine_version: str
    weights: list[WeightsUsed]
    timings: Timings
    host: str
    remote_host: str | None = None  # the configured name of the `lig serve` that ran the job
