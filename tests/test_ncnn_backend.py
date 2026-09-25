import io
from pathlib import Path

import pytest
from PIL import Image

from lig.backends.base import Backend, EngineError, EngineUnavailable, WeightsMissing
from lig.backends.ncnn import NcnnBackend
from lig.backends.registry import get_backend
from lig.core.models import EditRequest, GenerateRequest


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    path = tmp_path / "qwenimage21"
    path.mkdir()
    (path / "weights.bin").write_bytes(b"x")
    return path


@pytest.fixture
def backend(stub_bin_dir, model_dir, tmp_path) -> NcnnBackend:
    return NcnnBackend(model_dir=model_dir, log_dir=tmp_path / "logs")


def test_satisfies_protocol_and_registered():
    assert isinstance(NcnnBackend(), Backend)
    assert isinstance(get_backend("ncnn"), NcnnBackend)


def test_generate_argv_and_png_read_back(backend, model_dir, read_stub_argv):
    request = GenerateRequest(prompt="a cat", width=768, height=512, steps=30, seed=42)
    seen: list[tuple[int, int]] = []
    result = backend.generate(request, lambda s, t: seen.append((s, t)))

    argv = read_stub_argv()[0]
    assert argv == [
        "-m", str(model_dir), "-g", "0", "-p", "a cat", "-s", "768,512",
        "-l", "30", "-r", "42", "-o", argv[-1],
    ]  # fmt: skip
    assert "-i" not in argv
    assert Image.open(io.BytesIO(result.png)).format == "PNG"
    assert result.engine == "ncnn" and result.request == request
    assert seen == []  # no per-step progress: the CLI shows a spinner instead
    assert backend.progress_indeterminate


def test_edit_passes_reference(backend, read_stub_argv, tmp_path):
    ref = tmp_path / "ref.png"
    request = EditRequest(prompt="make it red", reference_image=ref, reference_sha256="a" * 64)
    backend.edit(request, None)
    argv = read_stub_argv()[0]
    assert argv[argv.index("-i") + 1] == str(ref)


def test_available_ok(backend):
    assert backend.available().ok


def test_available_names_missing_binary_and_key(monkeypatch, model_dir):
    monkeypatch.setenv("PATH", "")
    reason = NcnnBackend(model_dir=model_dir).available().reason
    assert "qwenimage-ncnn-vulkan" in reason and "ncnn_binary" in reason


@pytest.mark.parametrize("model", [None, "missing"])
def test_available_names_missing_model_dir_and_key(stub_bin_dir, tmp_path, model):
    directory = None if model is None else tmp_path / model
    availability = NcnnBackend(model_dir=directory).available()
    assert not availability.ok
    assert "model directory" in availability.reason and "ncnn_model_dir" in availability.reason


def test_generate_raises_unavailable(monkeypatch, model_dir):
    monkeypatch.setenv("PATH", "")
    with pytest.raises(EngineUnavailable, match="ncnn_binary"):
        NcnnBackend(model_dir=model_dir).generate(GenerateRequest(prompt="x"), None)


def test_empty_model_dir_is_weights_missing(stub_bin_dir, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(WeightsMissing):
        NcnnBackend(model_dir=empty, log_dir=tmp_path / "l").generate(
            GenerateRequest(prompt="x"), None
        )


def test_engine_failure_surfaces(backend, monkeypatch):
    monkeypatch.setenv("STUB_FAIL", "1")
    with pytest.raises(EngineError, match="code 2") as info:
        backend.generate(GenerateRequest(prompt="x"), None)
    assert info.value.log_path is not None


def test_zero_exit_without_output_is_an_error(stub_bin_dir, model_dir, tmp_path):
    stub = stub_bin_dir / "qwenimage-ncnn-vulkan"
    stub.write_text("#!/bin/sh\nexit 0\n")
    backend = NcnnBackend(model_dir=model_dir, log_dir=tmp_path / "l")
    with pytest.raises(EngineError, match="no image"):
        backend.generate(GenerateRequest(prompt="x"), None)


def test_invalid_png_is_an_error(stub_bin_dir, model_dir, tmp_path):
    stub = stub_bin_dir / "qwenimage-ncnn-vulkan"
    stub.write_text('#!/bin/sh\nwhile [ "$1" != -o ]; do shift; done\necho junk > "$2"\n')
    backend = NcnnBackend(model_dir=model_dir, log_dir=tmp_path / "l")
    with pytest.raises(EngineError, match="invalid PNG"):
        backend.generate(GenerateRequest(prompt="x"), None)
