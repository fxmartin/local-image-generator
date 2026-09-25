"""stable-diffusion.cpp adapter: maps requests onto `sd-cli` flags and runs it as a subprocess."""

import platform as platform_module
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

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
from lig.models.cache import artifact_status
from lig.models.registry import Artifact, Registry, RegistryError, load_registry

ENGINE = "sdcpp"
DEFAULT_BINARY = "sd-cli"
PLATFORMS = ["linux", "darwin"]
# Qwen-Image-2.1 is guidance-free; sd.cpp's docs suggest 6.0 but that doubles XPS time.
DEFAULT_GUIDANCE = 1.0
DEFAULT_SAMPLER = "euler"
UNKNOWN_VERSION = "unknown"
VERSION_TIMEOUT_S = 10

# The one place sd-cli flag names live (docs/qwen_image_2.1.md at the pinned sd.cpp commit),
# so an upstream rename is a one-line fix.
FLAGS = {
    "diffusion_model": "--diffusion-model",
    "vae": "--vae",
    "llm": "--llm",
    "llm_vision": "--llm_vision",
    "prompt": "-p",
    "negative_prompt": "-n",
    "width": "-W",
    "height": "-H",
    "steps": "--steps",
    "seed": "-s",
    "guidance": "--cfg-scale",
    "sampler": "--sampling-method",
    "output": "-o",
    "reference": "-r",
    "strength": "--strength",
    "offload": "--offload-to-cpu",
    "version": "--version",
}

_COMMIT = re.compile(r"\bcommit[:\s]+([0-9a-f]{7,40})\b")
_VERSION = re.compile(r"\bversion[:\s]+([^\s,]+)")


def parse_version(banner: str) -> str:
    """Commit hash if the banner has one, else its version token, else `unknown`."""
    for pattern in (_COMMIT, _VERSION):
        match = pattern.search(banner)
        if match:
            return match[1]
    return UNKNOWN_VERSION


class SdcppBackend:
    name = ENGINE

    def __init__(
        self,
        models_dir: Path,
        *,
        binary: str | Path = DEFAULT_BINARY,
        registry: Registry | None = None,
        extra_args: Sequence[str] = (),
        log_dir: Path | None = None,
        verbose: bool = False,
        timeout: float | None = None,
        platform: str = sys.platform,
        offload: bool = False,
    ) -> None:
        self._models_dir = models_dir
        self._binary = str(binary)
        self._registry = registry
        self._extra_args = list(extra_args)
        self._log_dir = log_dir
        self._verbose = verbose
        self._timeout = timeout
        self._platform = platform
        self._offload = offload
        self._version: str | None = None

    # -- availability -------------------------------------------------------------------

    def _resolve_binary(self) -> str | None:
        return shutil.which(self._binary)

    def _artifacts(self) -> dict[str, Artifact]:
        registry = self._registry or load_registry()
        return {a.role: a for a in registry.set_for(ENGINE, self._platform)}

    def _missing(self, artifact: Artifact) -> bool:
        return artifact_status(self._models_dir, artifact) not in ("installed", "unverified")

    def available(self) -> Availability:
        """First failure wins: platform, binary, then weights. A missing mmproj only costs edit."""
        if self._platform not in PLATFORMS:
            return Availability(ok=False, reason=f"platform {self._platform} unsupported by sdcpp")
        if self._resolve_binary() is None:
            return Availability(ok=False, reason=f"{self._binary} not found on PATH")
        try:
            artifacts = self._artifacts()
        except RegistryError as error:
            return Availability(ok=False, reason=str(error))
        for role in ("transformer", "text_encoder", "vae"):
            if role not in artifacts:
                return Availability(ok=False, reason=f"registry has no {role} for sdcpp")
            if self._missing(artifacts[role]):
                return Availability(ok=False, reason=f"{artifacts[role].name} not installed")
        if "mmproj" not in artifacts or self._missing(artifacts["mmproj"]):
            return Availability(ok=True, reason="edit unsupported: mmproj missing")
        return Availability(ok=True)

    def capabilities(self) -> Capabilities:
        available = self.available()
        return Capabilities(
            supports_edit=available.ok and available.reason == "",
            supports_transparent=False,  # Epic-07
            platforms=PLATFORMS,
        )

    # -- version ------------------------------------------------------------------------

    def version(self) -> str:
        if self._version is None:
            self._version = self._probe_version()
        return self._version

    def _probe_version(self) -> str:
        binary = self._resolve_binary()
        if binary is None:
            return UNKNOWN_VERSION
        try:
            done = subprocess.run(
                [binary, FLAGS["version"]],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=VERSION_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return UNKNOWN_VERSION
        if done.returncode != 0:
            return UNKNOWN_VERSION
        return parse_version(done.stdout + "\n" + done.stderr)

    # -- generation ---------------------------------------------------------------------

    def generate(
        self, request: GenerateRequest, on_progress: ProgressCallback | None
    ) -> ImageResult:
        return self._run(request, on_progress, edit=False)

    def edit(self, request: EditRequest, on_progress: ProgressCallback | None) -> ImageResult:
        return self._run(request, on_progress, edit=True)

    def _weights(self, edit: bool) -> dict[str, Artifact]:
        try:
            artifacts = self._artifacts()
        except RegistryError as error:
            raise EngineUnavailable(str(error)) from error
        needed = ["transformer", "text_encoder", "vae"] + (["mmproj"] if edit else [])
        for role in needed:
            artifact = artifacts.get(role)
            if artifact is None or self._missing(artifact):
                name = artifact.name if artifact else role
                raise WeightsMissing(f"{name} not installed; run `lig models pull`")
        return {role: artifacts[role] for role in needed}

    def _argv(
        self,
        binary: str,
        request: GenerateRequest,
        weights: dict[str, Artifact],
        output: Path,
    ) -> list[str]:
        def path(role: str) -> str:
            return str(self._models_dir / weights[role].filename)

        guidance = DEFAULT_GUIDANCE if request.guidance is None else request.guidance
        argv = [
            binary,
            FLAGS["diffusion_model"], path("transformer"),
            FLAGS["vae"], path("vae"),
            FLAGS["llm"], path("text_encoder"),
            FLAGS["prompt"], request.prompt,
            FLAGS["width"], str(request.width),
            FLAGS["height"], str(request.height),
            FLAGS["steps"], str(request.steps),
            FLAGS["seed"], str(request.seed),
            FLAGS["guidance"], str(guidance),
            FLAGS["sampler"], DEFAULT_SAMPLER,
            FLAGS["output"], str(output),
        ]  # fmt: skip
        if request.negative_prompt:
            argv += [FLAGS["negative_prompt"], request.negative_prompt]
        if isinstance(request, EditRequest):
            argv += [FLAGS["llm_vision"], path("mmproj"), FLAGS["reference"]]
            argv.append(str(request.reference_image))
            if request.strength is not None:
                argv += [FLAGS["strength"], str(request.strength)]
        if self._offload:
            argv.append(FLAGS["offload"])
        return argv + self._extra_args

    def _run(
        self, request: GenerateRequest, on_progress: ProgressCallback | None, *, edit: bool
    ) -> ImageResult:
        weights = self._weights(edit)
        binary = self._resolve_binary()
        if binary is None:
            raise EngineUnavailable(f"{self._binary} not found on PATH")
        started = time.perf_counter()
        with (
            tempfile.TemporaryDirectory(prefix="lig-sdcpp-") as tmp,
            EngineLog(ENGINE, verbose=self._verbose, log_dir=self._log_dir) as log,
        ):
            output = Path(tmp) / "out.png"
            run_engine(
                self._argv(binary, request, weights, output),
                log=log,
                on_progress=on_progress,
                timeout=self._timeout,
                output_path=output,
            )
            if not output.is_file():
                raise EngineError("sd-cli exited 0 but wrote no image", log_path=log.path)
            png = output.read_bytes()
        total = time.perf_counter() - started
        return ImageResult(
            png=png,
            request=request,
            engine=ENGINE,
            engine_version=self.version(),
            weights=[WeightsUsed(name=a.name, sha256=a.sha256) for a in weights.values()],
            # sd-cli does not report load time separately; per-step is a whole-run average.
            timings=Timings(load_s=0.0, per_step_s=total / request.steps, total_s=total),
            host=platform_module.node() or "localhost",
        )
