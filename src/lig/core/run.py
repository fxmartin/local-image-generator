"""Generation orchestration shared by `generate`, and later `edit`, `seeds` and the daemon."""

import hashlib
import re
import sys
from collections.abc import Callable
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from lig.backends.base import Availability, Backend, EngineUnavailable, ProgressCallback
from lig.backends.registry import BACKENDS, get_backend
from lig.core import config as cfg
from lig.core import memory
from lig.core.doctor import probe_memory
from lig.core.models import (
    MAX_SIZE,
    MIN_SIZE,
    SIZE_STEP,
    EditRequest,
    GenerateRequest,
    ImageResult,
)
from lig.core.output import write_result
from lig.models.registry import Registry, RegistryError

# Story 02.1-004: what the XPS can render in reasonable time; only applied when nothing else says.
LINUX_LOCAL_SIZE = "768x768"
LINUX_LOCAL_STEPS = 30
# Engines the config accepts that this build cannot run yet.
PLANNED_ENGINES = ("mlx", "remote")


class UsageError(ValueError):
    """A flag or config value is invalid; nothing has been run."""


def _neighbours(value: int) -> tuple[int, int]:
    lower = max(MIN_SIZE, min(MAX_SIZE, value // SIZE_STEP * SIZE_STEP))
    upper = max(MIN_SIZE, min(MAX_SIZE, -(-value // SIZE_STEP) * SIZE_STEP))
    return lower, upper


def parse_size(text: str) -> tuple[int, int]:
    """Parse `WxH`; on an invalid size raise UsageError suggesting the nearest valid ones."""
    match = re.fullmatch(r"(\d+)[xX](\d+)", text.strip())
    if not match:
        raise UsageError(f"invalid size '{text}': expected WIDTHxHEIGHT, e.g. 1024x1024")
    width, height = int(match.group(1)), int(match.group(2))
    if all(d % SIZE_STEP == 0 and MIN_SIZE <= d <= MAX_SIZE for d in (width, height)):
        return width, height
    (w_low, w_high), (h_low, h_high) = _neighbours(width), _neighbours(height)
    suggestions = dict.fromkeys([f"{w_low}x{h_low}", f"{w_high}x{h_high}"])
    raise UsageError(
        f"invalid size {width}x{height}: both sides must be multiples of {SIZE_STEP} "
        f"between {MIN_SIZE} and {MAX_SIZE}; nearest valid sizes: {', '.join(suggestions)}"
    )


def effective_size_and_steps(
    resolved: cfg.ResolvedConfig,
    size: str | None,
    steps: int | None,
    platform: str = sys.platform,
) -> tuple[tuple[int, int], int]:
    """Flag > config/env > Linux local fallback > global default."""
    settings, provenance = resolved.settings, resolved.provenance
    linux_fallback = platform.startswith("linux")
    if size is None:
        size = (
            LINUX_LOCAL_SIZE
            if linux_fallback and provenance.get("size") == "default"
            else settings.size
        )
    if steps is None:
        steps = (
            LINUX_LOCAL_STEPS
            if linux_fallback and provenance.get("steps") == "default"
            else settings.steps
        )
    if steps < 1:
        raise UsageError(f"invalid steps {steps}: must be at least 1")
    return parse_size(size), steps


def build_request(
    prompt: str,
    resolved: cfg.ResolvedConfig,
    *,
    size: str | None = None,
    steps: int | None = None,
    seed: int | None = None,
    negative: str | None = None,
    guidance: float | None = None,
) -> GenerateRequest:
    if not prompt.strip():
        raise UsageError("the prompt must not be empty")
    (width, height), steps = effective_size_and_steps(resolved, size, steps)
    fields: dict[str, object] = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "negative_prompt": negative,
        "guidance": guidance,
    }
    if seed is not None:
        fields["seed"] = seed
    try:
        return GenerateRequest(**fields)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc


def default_edit_size(image: Path) -> tuple[int, int]:
    """The source size rounded down to multiples of 32, clamped to the supported range."""
    try:
        with Image.open(image) as img:
            width, height = img.size
    except (OSError, UnidentifiedImageError) as exc:
        raise UsageError(f"{image} is not a readable image: {exc}") from exc
    return tuple(max(MIN_SIZE, min(MAX_SIZE, d // SIZE_STEP * SIZE_STEP)) for d in (width, height))  # type: ignore[return-value]


def build_edit_request(
    prompt: str,
    image: Path,
    resolved: cfg.ResolvedConfig,
    *,
    size: str | None = None,
    steps: int | None = None,
    seed: int | None = None,
    strength: float | None = None,
) -> EditRequest:
    if not prompt.strip():
        raise UsageError("the prompt must not be empty")
    if size is None:
        width, height = default_edit_size(image)
        size = f"{width}x{height}"
    (width, height), steps = effective_size_and_steps(resolved, size, steps)
    try:
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
    except OSError as exc:
        raise UsageError(f"{image} is not a readable image: {exc}") from exc
    fields: dict[str, object] = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "reference_image": image,
        "reference_sha256": digest,
        "strength": strength,
    }
    if seed is not None:
        fields["seed"] = seed
    try:
        return EditRequest(**fields)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc


def negative_prompt_warning(request: GenerateRequest) -> str | None:
    """Engines run guidance-free (1.0) unless told otherwise, and then ignore the negative."""
    if request.negative_prompt and (request.guidance is None or request.guidance <= 1.0):
        return (
            "the negative prompt has no effect at guidance 1; "
            "pass --guidance (e.g. --guidance 4) to use it"
        )
    return None


def resolve_engine_name(settings: cfg.Settings) -> str:
    """`auto` picks the local stable-diffusion.cpp engine until remote/MLX land."""
    return "sdcpp" if settings.engine == "auto" else settings.engine


def make_backend(name: str, settings: cfg.Settings, *, verbose: bool = False) -> Backend:
    """Instantiate the named engine; unknown or not-yet-built engines raise."""
    if name in PLANNED_ENGINES:
        raise EngineUnavailable(f"engine '{name}' is not available in this build yet")
    if name not in BACKENDS:
        raise UsageError(f"unknown engine '{name}'; known engines: {', '.join(sorted(BACKENDS))}")
    if name == "sdcpp":
        return get_backend(
            name,
            models_dir=settings.models_dir,
            extra_args=settings.engines.sdcpp.extra_args,
            verbose=verbose,
        )
    if name == "ncnn":
        return get_backend(
            name, binary=settings.ncnn_binary, model_dir=settings.ncnn_model_dir, verbose=verbose
        )
    return get_backend(name)


def unavailable_message(engine: str, availability: Availability) -> str:
    return f"engine '{engine}' is unavailable: {availability.reason}\nrun `lig doctor` for details"


def estimate_memory(
    registry: Registry, engine: str, request: GenerateRequest, platform: str = sys.platform
) -> tuple[int, int | None] | None:
    """(estimate, available) for engines with memory constants, else None (e.g. fake)."""
    if engine not in registry.engine_memory:
        return None
    try:
        estimate = memory.estimate_peak_bytes(
            registry, engine, platform, request.width, request.height
        )
    except RegistryError:
        return None
    return estimate, probe_memory()[1]


def run_generate(
    backend: Backend,
    request: GenerateRequest,
    out_dir: Path,
    on_progress: ProgressCallback | None = None,
    writer: Callable[[ImageResult, Path], Path] = write_result,
) -> Path:
    """Generate and persist PNG + sidecar; return the PNG path. Engine errors propagate."""
    return writer(backend.generate(request, on_progress), out_dir)


def run_edit(
    backend: Backend,
    request: EditRequest,
    out_dir: Path,
    on_progress: ProgressCallback | None = None,
    writer: Callable[[ImageResult, Path], Path] = write_result,
) -> Path:
    """Edit and persist PNG + sidecar (with source path and hash); return the PNG path."""
    return writer(backend.edit(request, on_progress), out_dir)
