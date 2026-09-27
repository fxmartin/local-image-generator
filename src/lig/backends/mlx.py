"""In-process adapter for mflux's `QwenImage21` (macOS Apple Silicon only).

mflux is mlx/Metal-only and is never installed in CI, so it is imported lazily: every other
platform gets `unsupported platform` from `available()` without ever importing it, and tests
inject a fake `model_cls` to exercise the rest of the adapter.

Verified at the pinned mflux 0.20.0 (`mflux/models/qwen21/README.md`): Qwen 2.1 exposes plain
img2img on the same `QwenImage21.generate_image()` used for txt2img (`image_path`,
`image_strength` kwargs) but not the instruction-editing variant sd.cpp's `mmproj` path drives
-- that needs the Qwen3-VL vision tower, which upstream mflux does not support yet. `edit()`
checks the installed `generate_image` signature for both kwargs so a future mflux that drops or
never gained them degrades to `supports_edit=False` instead of a crash mid-generation.
"""

import importlib.metadata
import inspect
import io
import os
import platform as platform_module
import sys
import time
from pathlib import Path
from typing import Any

from lig.backends.base import (
    Availability,
    Capabilities,
    EngineError,
    EngineUnavailable,
    ProgressCallback,
)
from lig.core.models import EditRequest, GenerateRequest, ImageResult, Timings, WeightsUsed

ENGINE = "mlx"
PLATFORM = "darwin"
ARCHS = ("arm64", "aarch64")
DEFAULT_QUANTIZE = "8"
# Qwen-Image-2.1 is guidance-free; matches the sdcpp adapter's default.
DEFAULT_GUIDANCE = 1.0
# mflux's own img2img default is None (no denoising skip); lig picks a starting point instead.
DEFAULT_IMAGE_STRENGTH = 0.6
EDIT_UNSUPPORTED_REASON = (
    "mflux's QwenImage21.generate_image has no image_path/image_strength parameters at this version"
)
# mflux downloads Qwen/Qwen-Image-2.1 itself (docs/reference.md); keep it inside lig's cache.
CACHE_SUBDIR = "mflux"
CACHE_DIR_ENV = "MFLUX_CACHE_DIR"
# HF-managed weights, not sha256-pinned in the registry (see docs/reference.md).
UNHASHED = "0" * 64
UNAVAILABLE_REASON = f"unsupported platform: {ENGINE} requires macOS arm64"


def _quantize_arg(quantize: str) -> int | None:
    return None if quantize == "none" else int(quantize)


def _weights_name(quantize: str) -> str:
    return "qwen-image-2.1-bf16" if quantize == "none" else f"qwen-image-2.1-q{quantize}"


def _supports_image_edit(model_cls: type) -> bool:
    try:
        params = inspect.signature(model_cls.generate_image).parameters
    except (TypeError, ValueError):
        return False
    return "image_path" in params and "image_strength" in params


class _ProgressBridge:
    """Registered once with `model.callbacks`; `on_progress` is set for the running job only."""

    def __init__(self) -> None:
        self.on_progress: ProgressCallback | None = None

    def call_in_loop(self, t: int, config: Any, **_: Any) -> None:
        if self.on_progress is not None:
            self.on_progress(t + 1, config.num_inference_steps)


class MlxBackend:
    name = ENGINE
    supports_warm = True

    def __init__(
        self,
        models_dir: Path,
        *,
        quantize: str = DEFAULT_QUANTIZE,
        image_strength: float = DEFAULT_IMAGE_STRENGTH,
        platform: str = sys.platform,
        machine: str = platform_module.machine(),
        model_cls: type | None = None,
    ) -> None:
        self._models_dir = models_dir
        self._quantize = quantize
        self._image_strength = image_strength
        self._platform = platform
        self._machine = machine
        self._model_cls = model_cls
        self._model: Any | None = None
        self._progress = _ProgressBridge()
        self.loaded = False

    def unload(self) -> None:
        if self.loaded:
            self._model = None
            self.loaded = False

    def _platform_ok(self) -> bool:
        return self._platform == PLATFORM and self._machine in ARCHS

    def _import_model_cls(self) -> type:
        # mflux reads this once at import time, so it must be set before the first import
        # (`available()` runs before `_load()`); only set it if the user hasn't.
        os.environ.setdefault(CACHE_DIR_ENV, str(self._models_dir / CACHE_SUBDIR))
        try:
            from mflux.models.qwen21.variants.txt2img.qwen_image_21 import QwenImage21
        except ImportError as error:
            raise EngineUnavailable(
                f"mflux not installed: {error}; install the 'mlx' extra"
            ) from error
        return QwenImage21

    def available(self) -> Availability:
        if not self._platform_ok():
            return Availability(ok=False, reason=UNAVAILABLE_REASON)
        try:
            model_cls = self._model_cls or self._import_model_cls()
        except EngineUnavailable as error:
            return Availability(ok=False, reason=str(error))
        if not _supports_image_edit(model_cls):
            return Availability(ok=True, reason=f"edit unsupported: {EDIT_UNSUPPORTED_REASON}")
        return Availability(ok=True)

    def capabilities(self) -> Capabilities:
        availability = self.available()
        return Capabilities(
            supports_edit=availability.ok and not availability.reason,
            supports_transparent=False,
            platforms=[PLATFORM],
        )

    def version(self) -> str:
        try:
            return importlib.metadata.version("mflux")
        except importlib.metadata.PackageNotFoundError:
            return "unknown"

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        model_cls = self._model_cls or self._import_model_cls()
        self._model = model_cls(quantize=_quantize_arg(self._quantize))
        self._model.callbacks.register(self._progress)
        self.loaded = True
        return self._model

    def generate(
        self, request: GenerateRequest, on_progress: ProgressCallback | None
    ) -> ImageResult:
        return self._run(request, on_progress)

    def edit(self, request: EditRequest, on_progress: ProgressCallback | None) -> ImageResult:
        availability = self.available()
        if not availability.ok or availability.reason:
            raise EngineUnavailable(availability.reason)
        return self._run(request, on_progress)

    def _run(self, request: GenerateRequest, on_progress: ProgressCallback | None) -> ImageResult:
        if not self._platform_ok():
            raise EngineUnavailable(UNAVAILABLE_REASON)
        started = time.perf_counter()
        was_loaded = self._model is not None
        model = self._load()
        load_s = 0.0 if was_loaded else time.perf_counter() - started
        self._progress.on_progress = on_progress
        kwargs: dict[str, Any] = dict(
            seed=request.seed,
            prompt=request.prompt,
            num_inference_steps=request.steps,
            width=request.width,
            height=request.height,
            guidance=DEFAULT_GUIDANCE if request.guidance is None else request.guidance,
            negative_prompt=request.negative_prompt,
        )
        if isinstance(request, EditRequest):
            kwargs["image_path"] = str(request.reference_image)
            kwargs["image_strength"] = (
                self._image_strength if request.strength is None else request.strength
            )
        try:
            generated = model.generate_image(**kwargs)
        except Exception as error:  # noqa: BLE001 - mflux's own exceptions aren't ours to enumerate
            raise EngineError(f"mlx generation failed: {error}") from error
        finally:
            self._progress.on_progress = None
        total = time.perf_counter() - started
        buffer = io.BytesIO()
        generated.image.save(buffer, format="PNG")
        return ImageResult(
            png=buffer.getvalue(),
            request=request,
            engine=ENGINE,
            engine_version=self.version(),
            weights=[WeightsUsed(name=_weights_name(self._quantize), sha256=UNHASHED)],
            timings=Timings(
                load_s=load_s, per_step_s=(total - load_s) / request.steps, total_s=total
            ),
            host=platform_module.node() or "localhost",
        )
