from pathlib import Path

import pytest

from lig.backends.base import EngineError, WeightsMissing
from lig.backends.sdcpp import SdcppBackend
from lig.core.config import load_settings
from lig.core.models import EditRequest, GenerateRequest
from lig.models.registry import load_registry

REGISTRY = load_registry()


def _install(models_dir: Path, *roles: str) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    for artifact in REGISTRY.set_for("sdcpp", "linux"):
        if artifact.role in roles:
            (models_dir / artifact.filename).write_bytes(b"x")


@pytest.fixture
def models_dir(tmp_path):
    path = tmp_path / "models"
    _install(path, "transformer", "text_encoder", "vae", "mmproj")
    return path


@pytest.fixture
def backend(models_dir, tmp_path, stub_bin_dir):
    return SdcppBackend(models_dir=models_dir, log_dir=tmp_path / "logs", platform="linux")


def _paths(models_dir: Path) -> dict[str, str]:
    return {a.role: str(models_dir / a.filename) for a in REGISTRY.set_for("sdcpp", "linux")}


def _flag(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def _generate_argv(read_stub_argv) -> list[str]:
    return [a for a in read_stub_argv() if a != ["--version"]][-1]


def test_generate_maps_request_and_registry_paths(backend, models_dir, read_stub_argv):
    request = GenerateRequest(prompt="a fox", width=768, height=512, steps=30, seed=7)
    result = backend.generate(request, None)
    argv = _generate_argv(read_stub_argv)
    paths = _paths(models_dir)
    assert _flag(argv, "--diffusion-model") == paths["transformer"]
    assert _flag(argv, "--vae") == paths["vae"]
    assert _flag(argv, "--llm") == paths["text_encoder"]
    assert _flag(argv, "-p") == "a fox"
    assert (_flag(argv, "-W"), _flag(argv, "-H")) == ("768", "512")
    assert _flag(argv, "--steps") == "30"
    assert _flag(argv, "-s") == "7"
    assert _flag(argv, "--cfg-scale") == "1.0"
    assert _flag(argv, "--sampling-method") == "euler"
    assert _flag(argv, "-o").endswith(".png")
    assert "--llm_vision" not in argv and "-r" not in argv
    assert result.png.startswith(b"\x89PNG")
    assert result.engine == "sdcpp"
    assert [w.name for w in result.weights]


def test_explicit_guidance_replaces_default(backend, read_stub_argv):
    backend.generate(GenerateRequest(prompt="x", guidance=4.5), None)
    assert _flag(_generate_argv(read_stub_argv), "--cfg-scale") == "4.5"


def test_negative_prompt_passed(backend, read_stub_argv):
    backend.generate(GenerateRequest(prompt="x", negative_prompt="blurry"), None)
    assert _flag(_generate_argv(read_stub_argv), "-n") == "blurry"


def test_edit_adds_mmproj_and_reference(backend, models_dir, tmp_path, read_stub_argv):
    reference = tmp_path / "ref.png"
    reference.write_bytes(b"png")
    request = EditRequest(prompt="x", reference_image=reference, reference_sha256="a" * 64)
    backend.edit(request, None)
    argv = _generate_argv(read_stub_argv)
    assert _flag(argv, "--llm_vision") == _paths(models_dir)["mmproj"]
    assert _flag(argv, "-r") == str(reference)


def test_edit_without_mmproj_raises(models_dir, tmp_path, stub_bin_dir):
    (models_dir / "mmproj-Qwen3VL-8B-Instruct-F16.gguf").unlink()
    backend = SdcppBackend(models_dir=models_dir, log_dir=tmp_path / "l", platform="linux")
    request = EditRequest(prompt="x", reference_image=tmp_path, reference_sha256="a" * 64)
    with pytest.raises(WeightsMissing, match="mmproj"):
        backend.edit(request, None)


def test_extra_args_appended_verbatim(models_dir, tmp_path, stub_bin_dir, read_stub_argv):
    extra = ["--model-args", "qwen_image_2_1_prefix_cache=false"]
    backend = SdcppBackend(
        models_dir=models_dir, log_dir=tmp_path / "l", platform="linux", extra_args=extra
    )
    backend.generate(GenerateRequest(prompt="x"), None)
    assert _generate_argv(read_stub_argv)[-2:] == extra


def test_available_ok(backend):
    result = backend.available()
    assert result.ok and result.reason == ""
    assert backend.capabilities().supports_edit


def test_available_reports_missing_mmproj_but_still_ok(models_dir, tmp_path, stub_bin_dir):
    (models_dir / "mmproj-Qwen3VL-8B-Instruct-F16.gguf").unlink()
    backend = SdcppBackend(models_dir=models_dir, log_dir=tmp_path, platform="linux")
    result = backend.available()
    assert result.ok and result.reason == "edit unsupported: mmproj missing"
    assert not backend.capabilities().supports_edit


def test_available_platform_first(models_dir, tmp_path, stub_bin_dir):
    backend = SdcppBackend(models_dir=models_dir, log_dir=tmp_path, platform="win32")
    result = backend.available()
    assert not result.ok and "platform" in result.reason


def test_available_binary_missing(models_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    backend = SdcppBackend(models_dir=models_dir, log_dir=tmp_path, platform="linux")
    result = backend.available()
    assert not result.ok and "sd-cli" in result.reason


def test_available_explicit_binary_path(models_dir, tmp_path, stub_bin_dir):
    backend = SdcppBackend(
        models_dir=models_dir, log_dir=tmp_path, platform="linux", binary=stub_bin_dir / "sd-cli"
    )
    assert backend.available().ok


def test_available_names_first_missing_weight(models_dir, tmp_path, stub_bin_dir):
    (models_dir / "qwen_image_2.1_vae_bf16.safetensors").unlink()
    (models_dir / "Qwen3VL-8B-Instruct-Q4_K_M.gguf").unlink()
    backend = SdcppBackend(models_dir=models_dir, log_dir=tmp_path, platform="linux")
    result = backend.available()
    assert not result.ok
    assert "qwen-image-2.1-text-encoder" in result.reason
    assert "vae" not in result.reason


def test_partial_download_is_not_available(models_dir, tmp_path, stub_bin_dir):
    (models_dir / "qwen_image_2.1_vae_bf16.safetensors.part").write_bytes(b"x")
    backend = SdcppBackend(models_dir=models_dir, log_dir=tmp_path, platform="linux")
    assert not backend.available().ok


def test_generate_without_weights_raises(tmp_path, stub_bin_dir):
    backend = SdcppBackend(models_dir=tmp_path / "empty", log_dir=tmp_path, platform="linux")
    with pytest.raises(WeightsMissing):
        backend.generate(GenerateRequest(prompt="x"), None)


@pytest.mark.parametrize(
    ("banner", "expected"),
    [
        ("stable-diffusion.cpp version master-abc1234, commit abc1234", "abc1234"),
        ("stable-diffusion.cpp version master-12-deadbeef", "master-12-deadbeef"),
        ("who knows", "unknown"),
        ("", "unknown"),
    ],
)
def test_version_parsing(backend, monkeypatch, banner, expected):
    monkeypatch.setenv("STUB_VERSION", banner)
    assert backend.generate(GenerateRequest(prompt="x"), None).engine_version == expected


def test_version_probe_failure_is_unknown(models_dir, tmp_path):
    fake = tmp_path / "sd-cli"
    fake.write_text("#!/bin/sh\nexit 3\n")
    fake.chmod(0o755)
    backend = SdcppBackend(
        models_dir=models_dir, log_dir=tmp_path / "l", platform="linux", binary=fake
    )
    assert backend.version() == "unknown"


def test_engine_failure_propagates(backend, monkeypatch):
    monkeypatch.setenv("STUB_FAIL", "1")
    with pytest.raises(EngineError, match="code 2"):
        backend.generate(GenerateRequest(prompt="x"), None)


def test_progress_forwarded(backend):
    seen = []
    backend.generate(GenerateRequest(prompt="x"), lambda s, t: seen.append((s, t)))
    assert sorted(seen) == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_load_time_is_time_to_first_sampling_step(backend, monkeypatch):
    # The stub sleeps before printing its first progress line, like sd-cli loading weights.
    monkeypatch.setenv("STUB_SLEEP", "0.5")
    timings = backend.generate(GenerateRequest(prompt="x", steps=4), None).timings
    assert timings.load_s >= 0.5
    assert timings.total_s >= timings.load_s
    assert timings.per_step_s == pytest.approx((timings.total_s - timings.load_s) / 4)


def test_registered_and_config_key(tmp_path):
    from lig.backends.registry import BACKENDS

    assert BACKENDS["sdcpp"] is SdcppBackend
    toml = tmp_path / "c.toml"
    toml.write_text('engines.sdcpp.extra_args = ["--a", "b"]\n')
    assert load_settings(path=toml, env={}).settings.engines.sdcpp.extra_args == ["--a", "b"]
    env = {"LIG_ENGINES__SDCPP__EXTRA_ARGS": "--x 'y z'"}
    assert load_settings(path=tmp_path / "none", env=env).settings.engines.sdcpp.extra_args == [
        "--x",
        "y z",
    ]
