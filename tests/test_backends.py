import io
import sys

import pytest
from PIL import Image

from lig.backends.base import (
    Availability,
    Backend,
    Capabilities,
    EngineError,
    EngineUnavailable,
    WeightsMissing,
)
from lig.backends.fake import FakeBackend
from lig.backends.registry import BACKENDS, get_backend
from lig.core.models import EditRequest, GenerateRequest, ImageResult


def _png(result: ImageResult) -> Image.Image:
    return Image.open(io.BytesIO(result.png))


def test_fake_satisfies_protocol():
    assert isinstance(FakeBackend(), Backend)
    assert FakeBackend().name == "fake"


def test_availability_and_capabilities():
    backend = FakeBackend()
    assert backend.available() == Availability(ok=True, reason="")
    caps = backend.capabilities()
    assert isinstance(caps, Capabilities)
    assert caps.supports_edit and caps.supports_transparent
    assert caps.platforms


def test_generate_is_deterministic_and_sized():
    req = GenerateRequest(prompt="a cat", width=256, height=320, steps=3, seed=7)
    a = FakeBackend().generate(req, lambda *_: None)
    b = FakeBackend().generate(req, lambda *_: None)
    assert a.png == b.png
    img = _png(a)
    assert img.format == "PNG" and img.size == (256, 320)


def test_pixels_depend_on_seed():
    def make(seed):
        return FakeBackend().generate(
            GenerateRequest(prompt="x", width=256, height=256, steps=1, seed=seed), None
        )

    assert make(1).png != make(2).png


def test_progress_once_per_step():
    calls = []
    req = GenerateRequest(prompt="x", width=256, height=256, steps=4, seed=1)
    FakeBackend().generate(req, lambda step, total: calls.append((step, total)))
    assert calls == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_result_fields_filled():
    req = GenerateRequest(prompt="x", width=256, height=256, steps=2, seed=1)
    res = FakeBackend().generate(req, None)
    assert res.request == req
    assert res.engine == "fake" and res.engine_version and res.host
    assert res.weights and res.weights[0].name
    assert res.timings.total_s >= 0


def test_transparent_yields_alpha():
    req = GenerateRequest(prompt="x", width=256, height=256, steps=1, seed=1, transparent=True)
    assert _png(FakeBackend().generate(req, None)).mode == "RGBA"


def test_edit():
    req = EditRequest(
        prompt="x", width=256, height=256, steps=2, seed=1,
        reference_image="ref.png", reference_sha256="0" * 64,
    )  # fmt: skip
    calls = []
    res = FakeBackend().edit(req, lambda s, t: calls.append(s))
    assert calls == [1, 2] and _png(res).size == (256, 256)


def test_failure_raises_engine_error_with_stderr_excerpt():
    long_stderr = "noise\n" * 500 + "CUDA exploded"
    backend = FakeBackend(fail=True, stderr=long_stderr)
    req = GenerateRequest(prompt="x", width=256, height=256, steps=1)
    with pytest.raises(EngineError) as exc:
        backend.generate(req, None)
    assert exc.value.stderr.endswith("CUDA exploded")
    assert len(exc.value.stderr) < len(long_stderr)
    assert "CUDA exploded" in str(exc.value)


def test_failure_on_edit():
    req = EditRequest(
        prompt="x", reference_image="r.png", reference_sha256="0" * 64, width=256, height=256
    )
    with pytest.raises(EngineError):
        FakeBackend(fail=True).edit(req, None)


def test_exception_hierarchy():
    assert issubclass(WeightsMissing, EngineError)
    assert issubclass(EngineUnavailable, EngineError)


def test_registry_resolves_fake():
    assert BACKENDS["fake"] is FakeBackend
    assert isinstance(get_backend("fake"), FakeBackend)
    assert get_backend("fake", fail=True).available().ok


def test_registry_unknown_engine():
    with pytest.raises(EngineUnavailable, match="nope.*fake"):
        get_backend("nope")


def test_platforms_are_known():
    assert set(FakeBackend().capabilities().platforms) <= {"linux", "darwin", "win32", sys.platform}
