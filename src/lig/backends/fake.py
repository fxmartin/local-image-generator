"""Weight-free backend that draws a seeded gradient, for tests and contact sheets."""

import io
import platform
import random
import time

from PIL import Image, ImageDraw

from lig.backends.base import Availability, Capabilities, EngineError, ProgressCallback
from lig.core.models import EditRequest, GenerateRequest, ImageResult, Timings, WeightsUsed

FAKE_VERSION = "0"
FAKE_WEIGHTS = WeightsUsed(name="fake-weights", sha256="0" * 64)


class FakeBackend:
    name = "fake"

    def __init__(self, fail: bool = False, stderr: str = "fake engine failure") -> None:
        self._fail = fail
        self._stderr = stderr

    def available(self) -> Availability:
        return Availability(ok=True)

    def capabilities(self) -> Capabilities:
        return Capabilities(
            supports_edit=True,
            supports_transparent=True,
            platforms=["linux", "darwin", "win32"],
        )

    def generate(
        self, request: GenerateRequest, on_progress: ProgressCallback | None
    ) -> ImageResult:
        return self._run(request, on_progress)

    def edit(self, request: EditRequest, on_progress: ProgressCallback | None) -> ImageResult:
        return self._run(request, on_progress)

    def _run(self, request: GenerateRequest, on_progress: ProgressCallback | None) -> ImageResult:
        started = time.perf_counter()
        if self._fail:
            raise EngineError("fake engine failed", self._stderr)
        for step in range(1, request.steps + 1):
            if on_progress:
                on_progress(step, request.steps)
        png = _draw(request)
        total = time.perf_counter() - started
        return ImageResult(
            png=png,
            request=request,
            engine=self.name,
            engine_version=FAKE_VERSION,
            weights=[FAKE_WEIGHTS],
            timings=Timings(load_s=0.0, per_step_s=total / request.steps, total_s=total),
            host=platform.node() or "localhost",
        )


def _draw(request: GenerateRequest) -> bytes:
    rng = random.Random(request.seed)
    start = tuple(rng.randrange(256) for _ in range(3))
    end = tuple(rng.randrange(256) for _ in range(3))
    width, height = request.width, request.height
    # Vertical gradient built from a 1px-wide column: cheap even at 4096².
    column = Image.new("RGB", (1, height))
    column.putdata(
        [
            tuple(
                round(s + (e - s) * y / max(height - 1, 1)) for s, e in zip(start, end, strict=True)
            )
            for y in range(height)
        ]
    )
    image = column.resize((width, height))
    if request.transparent:
        image = image.convert("RGBA")
        image.putalpha(Image.linear_gradient("L").resize((width, height)))
    ImageDraw.Draw(image).text((width // 16, height // 16), f"seed {request.seed}", fill="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
