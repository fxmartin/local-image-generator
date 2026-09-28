"""In-process mlx adapter: platform gating, fake `QwenImage21` injection, quantize, warm reuse.

mflux is macOS/Apple Silicon only and is never installed in CI, so every test here injects a
fake model class; the adapter must never import the real `mflux` package during these tests.
"""

import builtins
import io
import os
import threading

import pytest
from PIL import Image

from lig.backends.base import Backend, EngineError, EngineUnavailable
from lig.backends.mlx import MlxBackend
from lig.backends.registry import get_backend
from lig.core import config as cfg
from lig.core import run
from lig.core.models import EditRequest, GenerateRequest, WeightsUsed

UNAVAILABLE_REASON = "unsupported platform: mlx requires macOS arm64"


class _FakeConfig:
    def __init__(self, num_inference_steps: int) -> None:
        self.num_inference_steps = num_inference_steps


class _FakeCallbacks:
    def __init__(self) -> None:
        self.in_loop: list[object] = []

    def register(self, callback: object) -> None:
        if hasattr(callback, "call_in_loop"):
            self.in_loop.append(callback)

    def fire(self, config: _FakeConfig) -> None:
        for step in range(config.num_inference_steps):
            for subscriber in self.in_loop:
                subscriber.call_in_loop(
                    t=step, seed=0, prompt="", latents=None, config=config, time_steps=None
                )


class _FakeGeneratedImage:
    def __init__(self, image: Image.Image) -> None:
        self.image = image


class FakeQwenImage21:
    """Stands in for mflux's real model: same constructor/`generate_image` shape, no mlx/Metal."""

    instances = 0

    def __init__(self, quantize: int | None = None) -> None:
        FakeQwenImage21.instances += 1
        self.quantize = quantize
        self.bits = quantize
        self.callbacks = _FakeCallbacks()
        self.last_kwargs: dict | None = None

    def generate_image(
        self,
        seed,
        prompt,
        num_inference_steps=40,
        width=1024,
        height=1024,
        guidance=1.0,
        image_path=None,
        image_strength=None,
        negative_prompt=None,
    ) -> _FakeGeneratedImage:
        self.last_kwargs = {
            "seed": seed,
            "prompt": prompt,
            "num_inference_steps": num_inference_steps,
            "width": width,
            "height": height,
            "guidance": guidance,
            "image_path": image_path,
            "image_strength": image_strength,
            "negative_prompt": negative_prompt,
        }
        config = _FakeConfig(num_inference_steps)
        self.callbacks.fire(config)
        image = Image.new("RGB", (width, height))
        return _FakeGeneratedImage(image)


class _FailingQwenImage21(FakeQwenImage21):
    def generate_image(self, **kwargs):
        raise RuntimeError("boom")


class FakeQwenImage21NoEdit:
    """An older/future mflux `QwenImage21` without img2img support (no `image_path` kwarg)."""

    instances = 0

    def __init__(self, quantize: int | None = None) -> None:
        FakeQwenImage21NoEdit.instances += 1
        self.callbacks = _FakeCallbacks()

    def generate_image(
        self,
        seed,
        prompt,
        num_inference_steps=40,
        width=1024,
        height=1024,
        guidance=1.0,
        negative_prompt=None,
    ) -> _FakeGeneratedImage:
        raise AssertionError("should never be called: capabilities() must gate this")


@pytest.fixture(autouse=True)
def _reset_instance_counter():
    FakeQwenImage21.instances = 0
    FakeQwenImage21NoEdit.instances = 0


@pytest.fixture
def backend(tmp_path) -> MlxBackend:
    return MlxBackend(
        models_dir=tmp_path, platform="darwin", machine="arm64", model_cls=FakeQwenImage21
    )


def test_satisfies_protocol_and_registered(tmp_path):
    assert isinstance(MlxBackend(models_dir=tmp_path), Backend)
    assert isinstance(get_backend("mlx", models_dir=tmp_path), MlxBackend)


def test_construction_never_checks_the_real_platform(tmp_path):
    # Whatever platform the test happens to run on, building the backend must not raise:
    # `available()` is where platform gating happens, not `__init__`.
    backend = MlxBackend(models_dir=tmp_path)
    assert backend.name == "mlx"


def test_available_reports_unsupported_platform_without_importing_mflux(tmp_path, monkeypatch):
    backend = MlxBackend(models_dir=tmp_path, platform="linux", machine="x86_64")
    monkeypatch.setattr(backend, "_import_model_cls", lambda: pytest.fail("must not import mflux"))
    availability = backend.available()
    assert not availability.ok
    assert availability.reason == UNAVAILABLE_REASON


@pytest.mark.parametrize("platform, machine", [("darwin", "x86_64"), ("linux", "arm64")])
def test_available_unsupported_on_non_arm64_mac_and_non_darwin_arm(tmp_path, platform, machine):
    backend = MlxBackend(models_dir=tmp_path, platform=platform, machine=machine)
    assert backend.available().reason == UNAVAILABLE_REASON


def test_available_ok_when_platform_matches_and_model_is_injected(backend):
    assert backend.available().ok


def test_available_reports_missing_mflux_extra(tmp_path, monkeypatch):
    monkeypatch.delenv("MFLUX_CACHE_DIR", raising=False)
    backend = MlxBackend(models_dir=tmp_path, platform="darwin", machine="arm64")
    availability = backend.available()
    assert not availability.ok
    assert "mflux" in availability.reason


def _record_cache_dir_on_mflux_import(monkeypatch) -> list[str | None]:
    """Fail every `mflux` import, noting the MFLUX_CACHE_DIR it would have seen."""
    seen: list[str | None] = []
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("mflux"):
            seen.append(os.environ.get("MFLUX_CACHE_DIR"))
            raise ImportError("no mflux here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    return seen


def test_cache_dir_is_set_before_the_first_mflux_import(tmp_path, monkeypatch):
    # `lig generate` calls `available()` before `_load()`; mflux reads the cache dir at import
    # time, so the very first import (from `available()`) must already see it.
    monkeypatch.delenv("MFLUX_CACHE_DIR", raising=False)
    seen = _record_cache_dir_on_mflux_import(monkeypatch)
    backend = MlxBackend(models_dir=tmp_path, platform="darwin", machine="arm64")
    assert not backend.available().ok
    assert seen == [str(tmp_path / "mflux")]


def test_cache_dir_keeps_the_users_own_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("MFLUX_CACHE_DIR", "/elsewhere")
    seen = _record_cache_dir_on_mflux_import(monkeypatch)
    MlxBackend(models_dir=tmp_path, platform="darwin", machine="arm64").available()
    assert seen == ["/elsewhere"]


def test_capabilities_support_edit_when_generate_image_has_img2img_kwargs(backend):
    caps = backend.capabilities()
    assert caps.supports_edit is True
    assert caps.supports_transparent is False
    assert caps.platforms == ["darwin"]


def test_capabilities_deny_edit_when_engine_lacks_img2img_kwargs(tmp_path):
    backend = MlxBackend(
        models_dir=tmp_path, platform="darwin", machine="arm64", model_cls=FakeQwenImage21NoEdit
    )
    caps = backend.capabilities()
    assert caps.supports_edit is False
    assert caps.supports_transparent is False


def test_available_reports_edit_unsupported_reason_when_engine_lacks_img2img_kwargs(tmp_path):
    backend = MlxBackend(
        models_dir=tmp_path, platform="darwin", machine="arm64", model_cls=FakeQwenImage21NoEdit
    )
    availability = backend.available()
    assert availability.ok is True
    assert availability.reason.startswith("edit unsupported:")


def test_generate_produces_png_with_engine_version_and_weights(backend, monkeypatch):
    monkeypatch.setattr("lig.backends.mlx.importlib.metadata.version", lambda name: "0.20.0")
    request = GenerateRequest(prompt="a cat", width=256, height=288, steps=3, seed=1)
    seen: list[tuple[int, int]] = []
    result = backend.generate(request, lambda s, t: seen.append((s, t)))

    assert Image.open(io.BytesIO(result.png)).format == "PNG"
    assert result.engine == "mlx"
    assert result.engine_version == "0.20.0"
    assert result.weights == [WeightsUsed(name="qwen-image-2.1-q8", sha256="0" * 64)]
    assert seen == [(1, 3), (2, 3), (3, 3)]
    assert result.timings.total_s >= 0
    assert result.timings.per_step_s >= 0


@pytest.mark.parametrize(
    "quantize, expected_arg, expected_name",
    [
        ("8", 8, "qwen-image-2.1-q8"),
        ("4", 4, "qwen-image-2.1-q4"),
        ("none", None, "qwen-image-2.1-bf16"),
    ],
)
def test_quantize_option_maps_to_mflux_arg_and_sidecar_name(
    tmp_path, quantize, expected_arg, expected_name
):
    backend = MlxBackend(
        models_dir=tmp_path,
        platform="darwin",
        machine="arm64",
        model_cls=FakeQwenImage21,
        quantize=quantize,
    )
    result = backend.generate(GenerateRequest(prompt="x", steps=1), None)
    assert backend._model.quantize == expected_arg  # only seam for the mflux quantize arg
    assert result.weights[0].name == expected_name


def test_generate_raises_unavailable_on_the_wrong_platform(tmp_path):
    backend = MlxBackend(models_dir=tmp_path, platform="linux", machine="x86_64")
    with pytest.raises(EngineUnavailable, match=UNAVAILABLE_REASON):
        backend.generate(GenerateRequest(prompt="x"), None)


def test_engine_failure_wraps_in_engine_error(tmp_path):
    backend = MlxBackend(
        models_dir=tmp_path, platform="darwin", machine="arm64", model_cls=_FailingQwenImage21
    )
    with pytest.raises(EngineError, match="boom"):
        backend.generate(GenerateRequest(prompt="x", steps=1), None)


def test_second_generate_reuses_the_loaded_model(backend):
    backend.generate(GenerateRequest(prompt="a", steps=1), None)
    first_model = backend._model
    backend.generate(GenerateRequest(prompt="b", steps=1), None)
    assert backend._model is first_model
    assert FakeQwenImage21.instances == 1
    assert backend.loaded is True


def test_unload_releases_the_model(backend):
    backend.generate(GenerateRequest(prompt="a", steps=1), None)
    assert backend.loaded is True
    backend.unload()
    assert backend.loaded is False
    assert backend._model is None


class _ThreadRecordingQwenImage21(FakeQwenImage21):
    """Records which thread loads and runs it: mlx streams are thread-local."""

    threads: list[str] = []

    def __init__(self, quantize: int | None = None) -> None:
        super().__init__(quantize)
        _ThreadRecordingQwenImage21.threads.append(f"load:{threading.get_ident()}")

    def generate_image(self, **kwargs) -> _FakeGeneratedImage:
        _ThreadRecordingQwenImage21.threads.append(f"run:{threading.get_ident()}")
        return super().generate_image(**kwargs)


def test_warm_model_runs_on_the_thread_that_loaded_it_whatever_the_caller(tmp_path):
    # `lig serve` calls each job from a different thread; mlx then fails with
    # "There is no Stream(cpu, 0) in current thread" unless every call is pinned to one thread.
    _ThreadRecordingQwenImage21.threads = []
    backend = MlxBackend(
        models_dir=tmp_path,
        platform="darwin",
        machine="arm64",
        model_cls=_ThreadRecordingQwenImage21,
    )

    def job(prompt: str) -> None:
        backend.generate(GenerateRequest(prompt=prompt, steps=1), None)

    for prompt in ("a", "b"):
        caller = threading.Thread(target=job, args=(prompt,))
        caller.start()
        caller.join()
    job("c")

    recorded = _ThreadRecordingQwenImage21.threads
    assert [entry.split(":")[0] for entry in recorded] == ["load", "run", "run", "run"]
    assert len({entry.split(":")[1] for entry in recorded}) == 1


def test_errors_and_progress_cross_back_to_the_caller(tmp_path):
    backend = MlxBackend(
        models_dir=tmp_path, platform="darwin", machine="arm64", model_cls=_FailingQwenImage21
    )
    with pytest.raises(EngineError, match="boom"):
        backend.generate(GenerateRequest(prompt="x", steps=1), None)

    steps: list[tuple[int, int]] = []
    ok = MlxBackend(
        models_dir=tmp_path, platform="darwin", machine="arm64", model_cls=FakeQwenImage21
    )
    ok.generate(GenerateRequest(prompt="x", steps=2), lambda s, t: steps.append((s, t)))
    assert steps == [(1, 2), (2, 2)]


def test_edit_carries_reference_image_path_and_default_strength(backend, tmp_path):
    reference = tmp_path / "ref.png"
    request = EditRequest(
        prompt="make it orange", reference_image=reference, reference_sha256="a" * 64, steps=2
    )
    backend.edit(request, None)
    assert backend._model.last_kwargs["image_path"] == str(reference)
    assert backend._model.last_kwargs["image_strength"] == 0.6


def test_edit_uses_the_requests_strength_when_given(tmp_path):
    reference = tmp_path / "ref.png"
    backend = MlxBackend(
        models_dir=tmp_path,
        platform="darwin",
        machine="arm64",
        model_cls=FakeQwenImage21,
        image_strength=0.6,
    )
    request = EditRequest(
        prompt="x", reference_image=reference, reference_sha256="a" * 64, steps=1, strength=0.85
    )
    backend.edit(request, None)
    assert backend._model.last_kwargs["image_strength"] == 0.85


def test_edit_uses_the_configured_default_strength(tmp_path):
    reference = tmp_path / "ref.png"
    backend = MlxBackend(
        models_dir=tmp_path,
        platform="darwin",
        machine="arm64",
        model_cls=FakeQwenImage21,
        image_strength=0.4,
    )
    request = EditRequest(prompt="x", reference_image=reference, reference_sha256="a" * 64, steps=1)
    backend.edit(request, None)
    assert backend._model.last_kwargs["image_strength"] == 0.4


def test_edit_raises_engine_unavailable_when_engine_lacks_img2img_support(tmp_path):
    reference = tmp_path / "ref.png"
    backend = MlxBackend(
        models_dir=tmp_path, platform="darwin", machine="arm64", model_cls=FakeQwenImage21NoEdit
    )
    request = EditRequest(prompt="x", reference_image=reference, reference_sha256="a" * 64)
    with pytest.raises(EngineUnavailable, match="edit unsupported"):
        backend.edit(request, None)


def test_edit_raises_engine_unavailable_on_the_wrong_platform(tmp_path):
    backend = MlxBackend(models_dir=tmp_path, platform="linux", machine="x86_64")
    reference = tmp_path / "ref.png"
    request = EditRequest(prompt="x", reference_image=reference, reference_sha256="a" * 64)
    with pytest.raises(EngineUnavailable, match=UNAVAILABLE_REASON):
        backend.edit(request, None)


def test_make_backend_wires_models_dir_and_quantize(tmp_path):
    settings = cfg.Settings(models_dir=tmp_path, engines={"mlx": {"quantize": "4"}})
    built = run.make_backend("mlx", settings)
    assert isinstance(built, MlxBackend)
    assert built._models_dir == tmp_path
    assert built._quantize == "4"


def test_make_backend_wires_image_strength(tmp_path):
    settings = cfg.Settings(models_dir=tmp_path, engines={"mlx": {"image_strength": 0.75}})
    built = run.make_backend("mlx", settings)
    assert isinstance(built, MlxBackend)
    assert built._image_strength == 0.75
