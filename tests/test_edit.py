import hashlib
import json

import pytest
from PIL import Image
from typer.testing import CliRunner

from lig.backends.base import Availability, Capabilities
from lig.backends.fake import FakeBackend
from lig.cli.app import app
from lig.core import run

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    for key in ("LIG_ENGINE", "LIG_SIZE", "LIG_STEPS", "LIG_OUTPUT_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "teapot.png"
    Image.new("RGB", (1000, 700), "red").save(path)
    return path


def test_edit_writes_png_and_sidecar_with_source(tmp_path, source):
    result = runner.invoke(app, ["edit", str(source), "make it blue", "--engine", "fake"])
    assert result.exit_code == 0, result.output
    pngs = list((tmp_path / "outputs").glob("*.png"))
    assert len(pngs) == 1
    sidecar = json.loads(pngs[0].with_suffix(".json").read_text())
    assert sidecar["source_path"] == str(source)
    assert sidecar["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_default_size_rounds_source_down_and_says_so(tmp_path, source):
    result = runner.invoke(app, ["edit", str(source), "make it blue", "--engine", "fake"])
    assert result.exit_code == 0, result.output
    assert "992x672" in result.output
    png = next((tmp_path / "outputs").glob("*.png"))
    with Image.open(png) as img:
        assert img.size == (992, 672)


def test_explicit_size_and_strength(tmp_path, source):
    result = runner.invoke(
        app,
        ["edit", str(source), "x", "--engine", "fake", "--size", "512x512", "--strength", "0.5"],
    )
    assert result.exit_code == 0, result.output
    with Image.open(next((tmp_path / "outputs").glob("*.png"))) as img:
        assert img.size == (512, 512)


def test_strength_out_of_range_exits_2(source):
    result = runner.invoke(app, ["edit", str(source), "x", "--engine", "fake", "--strength", "2"])
    assert result.exit_code == 2


def test_unreadable_image_exits_2(tmp_path):
    bogus = tmp_path / "bogus.png"
    bogus.write_text("not an image")
    result = runner.invoke(app, ["edit", str(bogus), "x", "--engine", "fake"])
    assert result.exit_code == 2
    assert "not a readable image" in result.output


def test_missing_image_exits_2(tmp_path):
    result = runner.invoke(app, ["edit", str(tmp_path / "nope.png"), "x", "--engine", "fake"])
    assert result.exit_code == 2
    assert "not a readable image" in result.output


def test_empty_prompt_exits_2(source):
    result = runner.invoke(app, ["edit", str(source), " ", "--engine", "fake"])
    assert result.exit_code == 2


def test_engine_without_edit_exits_4_with_reason(monkeypatch, source):
    class NoEdit(FakeBackend):
        def capabilities(self):
            return Capabilities(supports_edit=False, supports_transparent=False, platforms=[])

        def available(self):
            return Availability(ok=True, reason="edit unsupported: mmproj missing")

    monkeypatch.setattr(run, "make_backend", lambda *a, **k: NoEdit())
    result = runner.invoke(app, ["edit", str(source), "x", "--engine", "fake"])
    assert result.exit_code == 4
    assert "mmproj missing" in result.output


def test_unavailable_engine_exits_4(monkeypatch, source):
    class Down(FakeBackend):
        def available(self):
            return Availability(ok=False, reason="sd-cli not found on PATH")

    monkeypatch.setattr(run, "make_backend", lambda *a, **k: Down())
    result = runner.invoke(app, ["edit", str(source), "x", "--engine", "fake"])
    assert result.exit_code == 4
    assert "sd-cli not found" in result.output


def test_default_edit_size_clamps_to_minimum(tmp_path):
    tiny = tmp_path / "tiny.png"
    Image.new("RGB", (100, 3000), "red").save(tiny)
    assert run.default_edit_size(tiny) == (256, 2976)
