"""Adapter for `qwenimage-ncnn-vulkan`, the full-precision Vulkan engine.

Flag table (pinned release 20260924, see docs/bench/xps13.md):

| Request field     | Flag         | Notes                                              |
|-------------------|--------------|----------------------------------------------------|
| model directory   | `-m <dir>`   | the `qwenimage21/` folder                          |
| GPU index         | `-g <n>`     |                                                    |
| prompt            | `-p <text>`  |                                                    |
| width, height     | `-s W,H`     |                                                    |
| steps             | `-l <n>`     |                                                    |
| seed              | `-r <n>`     |                                                    |
| reference (edit)  | `-i <path>`  |                                                    |
| output            | `-o <path>`  |                                                    |

Guidance is not passed: the engine runs guidance-free (scale 1), which is also
lig's default. Negative prompts and transparency have no flag and are ignored.
The engine prints no per-step progress, so `on_progress` is never called and
callers should show an indeterminate spinner (`progress_indeterminate`).
"""

import io
import platform
import shutil
import tempfile
import time
from pathlib import Path

from PIL import Image

from lig.backends.base import (
    Availability,
    Capabilities,
    EngineError,
    EngineUnavailable,
    ProgressCallback,
    WeightsMissing,
)
from lig.backends.runner import run_engine
from lig.core.logs import EngineLog
from lig.core.models import EditRequest, GenerateRequest, ImageResult, Timings, WeightsUsed

BINARY_NAME = "qwenimage-ncnn-vulkan"
PINNED_RELEASE = "20260924"
MODEL_DIR_NAME = "qwenimage21"
BINARY_KEY = "ncnn_binary"
MODEL_DIR_KEY = "ncnn_model_dir"
# The model folder has no per-file registry entry yet, so its hash is not recorded.
UNHASHED = "0" * 64


class NcnnBackend:
    name = "ncnn"
    progress_indeterminate = True

    def __init__(
        self,
        binary: Path | str | None = None,
        model_dir: Path | None = None,
        *,
        gpu: int = 0,
        verbose: bool = False,
        log_dir: Path | None = None,
        timeout: float | None = None,
    ) -> None:
        self._binary = binary
        self._model_dir = model_dir
        self._gpu = gpu
        self._verbose = verbose
        self._log_dir = log_dir
        self._timeout = timeout

    def _resolve_binary(self) -> str | None:
        return shutil.which(str(self._binary or BINARY_NAME))

    def version(self) -> str:
        return PINNED_RELEASE

    def available(self) -> Availability:
        if self._resolve_binary() is None:
            return Availability(
                ok=False,
                reason=(
                    f"{BINARY_NAME} not found; install it or set `{BINARY_KEY}` "
                    f"(LIG_{BINARY_KEY.upper()}) to its path"
                ),
            )
        if self._model_dir is None or not self._model_dir.is_dir():
            return Availability(
                ok=False,
                reason=(
                    f"{BINARY_NAME} model directory {self._model_dir or '(unset)'} not found; "
                    f"set `{MODEL_DIR_KEY}` (LIG_{MODEL_DIR_KEY.upper()}) to the "
                    f"{MODEL_DIR_NAME}/ folder"
                ),
            )
        return Availability(ok=True)

    def capabilities(self) -> Capabilities:
        return Capabilities(supports_edit=True, supports_transparent=False, platforms=["linux"])

    def build_argv(
        self, binary: str, model_dir: Path, request: GenerateRequest, output: Path
    ) -> list[str]:
        argv = [
            binary,
            "-m", str(model_dir),
            "-g", str(self._gpu),
            "-p", request.prompt,
            "-s", f"{request.width},{request.height}",
            "-l", str(request.steps),
            "-r", str(request.seed),
        ]  # fmt: skip
        if isinstance(request, EditRequest):
            argv += ["-i", str(request.reference_image)]
        return [*argv, "-o", str(output)]

    def generate(
        self, request: GenerateRequest, on_progress: ProgressCallback | None
    ) -> ImageResult:
        return self._run(request, on_progress)

    def edit(self, request: EditRequest, on_progress: ProgressCallback | None) -> ImageResult:
        return self._run(request, on_progress)

    def _run(self, request: GenerateRequest, on_progress: ProgressCallback | None) -> ImageResult:
        status = self.available()
        binary = self._resolve_binary()
        if not status.ok or binary is None or self._model_dir is None:
            raise EngineUnavailable(status.reason)
        model_dir = self._model_dir
        if not any(model_dir.iterdir()):
            raise WeightsMissing(f"{model_dir} is empty; download the {MODEL_DIR_NAME} model files")

        started = time.perf_counter()
        with (
            tempfile.TemporaryDirectory(prefix="lig-ncnn-") as scratch,
            EngineLog(self.name, verbose=self._verbose, log_dir=self._log_dir) as log,
        ):
            output = Path(scratch) / "out.png"
            run_engine(
                self.build_argv(binary, model_dir, request, output),
                log=log,
                on_progress=on_progress,
                timeout=self._timeout,
                output_path=output,
            )
            if not output.is_file():
                raise EngineError("engine exited 0 but wrote no image", log_path=log.path)
            png = output.read_bytes()
        try:
            Image.open(io.BytesIO(png)).verify()
        except Exception as error:  # noqa: BLE001 - any decode failure means a bad engine output
            raise EngineError(f"engine wrote an invalid PNG: {error}") from error

        total = time.perf_counter() - started
        return ImageResult(
            png=png,
            request=request,
            engine=self.name,
            engine_version=PINNED_RELEASE,
            weights=[WeightsUsed(name=MODEL_DIR_NAME, sha256=UNHASHED)],
            timings=Timings(load_s=0.0, per_step_s=total / request.steps, total_s=total),
            host=platform.node() or "localhost",
        )
