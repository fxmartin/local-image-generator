"""Backend protocol and the error vocabulary every adapter shares."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from lig.core.models import EditRequest, GenerateRequest, ImageResult

# Called as (step, total_steps) after each completed sampling step.
ProgressCallback = Callable[[int, int], None]

STDERR_EXCERPT_CHARS = 2000


class EngineError(Exception):
    """An engine failed; `stderr` holds the tail of its output, `log_path` the full log."""

    def __init__(self, message: str, stderr: str = "", log_path: Path | None = None) -> None:
        self.log_path = log_path
        self.stderr = stderr[-STDERR_EXCERPT_CHARS:]
        super().__init__(f"{message}\n{self.stderr}" if self.stderr else message)


class WeightsMissing(EngineError):
    """The model weights the engine needs are not in the cache."""


class EngineUnavailable(EngineError):
    """The engine cannot run here (binary, driver, platform or host missing)."""


class Availability(BaseModel):
    ok: bool
    reason: str = ""


class Capabilities(BaseModel):
    supports_edit: bool
    supports_transparent: bool
    platforms: list[str]  # sys.platform values, e.g. "linux", "darwin"


@runtime_checkable
class Backend(Protocol):
    name: str

    def available(self) -> Availability: ...

    def capabilities(self) -> Capabilities: ...

    def generate(
        self, request: GenerateRequest, on_progress: ProgressCallback | None
    ) -> ImageResult: ...

    def edit(self, request: EditRequest, on_progress: ProgressCallback | None) -> ImageResult: ...

    # Optional, in-process engines only (MLX, Epic-07): `supports_warm: bool`, `loaded: bool` and
    # `unload()`. `lig serve` probes them with getattr; subprocess engines simply omit them.
