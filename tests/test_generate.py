import json
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from lig.backends.base import Availability
from lig.backends.fake import FakeBackend
from lig.cli import app as cli_app
from lig.cli.app import app
from lig.core import config as cfg
from lig.core import run
from lig.core.models import GenerateRequest

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    for key in ("LIG_ENGINE", "LIG_SIZE", "LIG_STEPS", "LIG_OUTPUT_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


def test_generate_fake_writes_png_and_sidecar(tmp_path):
    result = runner.invoke(app, ["generate", "a lighthouse at dusk", "--engine", "fake"])
    assert result.exit_code == 0, result.output
    pngs = list((tmp_path / "outputs").glob("*.png"))
    assert len(pngs) == 1
    assert pngs[0].with_suffix(".json").exists()
    assert result.stdout.strip().splitlines()[-1] == str(pngs[0].relative_to(tmp_path)) or (
        result.stdout.strip().splitlines()[-1].endswith(pngs[0].name)
    )


def test_bad_size_exits_2_with_suggestions(monkeypatch):
    monkeypatch.setattr(
        run, "make_backend", lambda *a, **k: pytest.fail("engine must not be touched")
    )
    result = runner.invoke(app, ["generate", "x", "--size", "1000x1000", "--engine", "fake"])
    assert result.exit_code == 2
    assert "992x992" in result.output and "1024x1024" in result.output


def test_unparseable_size_exits_2():
    result = runner.invoke(app, ["generate", "x", "--size", "big", "--engine", "fake"])
    assert result.exit_code == 2


def test_unknown_engine_exits_2():
    result = runner.invoke(app, ["generate", "x", "--engine", "nope"])
    assert result.exit_code == 2
    assert "known engines" in result.output


def test_unavailable_engine_exits_4_with_reason(monkeypatch):
    class Down:
        name = "fake"

        def available(self):
            return Availability(ok=False, reason="sd-cli not found on PATH")

    monkeypatch.setattr(run, "make_backend", lambda *a, **k: Down())
    result = runner.invoke(app, ["generate", "x", "--engine", "fake"])
    assert result.exit_code == 4
    assert "sd-cli not found on PATH" in result.output
    assert "lig doctor" in result.output


def test_planned_engine_exits_4():
    result = runner.invoke(app, ["generate", "x", "--engine", "remote"])
    assert result.exit_code == 4
    assert "lig doctor" in result.output


def test_same_seed_is_byte_identical(tmp_path):
    for out in ("a", "b"):
        r = runner.invoke(
            app,
            [
                "generate",
                "x",
                "--engine",
                "fake",
                "--seed",
                "42",
                "--out",
                out,
                "--size",
                "256x256",
            ],
        )
        assert r.exit_code == 0, r.output
    a = next((tmp_path / "a").glob("*.png"))
    b = next((tmp_path / "b").glob("*.png"))
    # The `lig:sidecar` tEXt chunk (spec'd in 01.x) carries the timestamped filename, so whole-file
    # bytes only match within one second; the engine output and decoded pixels are what is stable.
    assert Image.open(a).tobytes() == Image.open(b).tobytes()
    assert FakeBackend().generate(GenerateRequest(prompt="x", seed=42), None).png == (
        FakeBackend().generate(GenerateRequest(prompt="x", seed=42), None).png
    )


def test_negative_prompt_warns_at_guidance_one():
    result = runner.invoke(app, ["generate", "x", "--engine", "fake", "--negative", "blurry"])
    assert result.exit_code == 0
    assert "no effect at guidance 1" in result.output and "--guidance" in result.output


def test_negative_prompt_silent_with_guidance():
    result = runner.invoke(
        app, ["generate", "x", "--engine", "fake", "--negative", "blurry", "--guidance", "4"]
    )
    assert "no effect" not in result.output


def test_memory_refusal_exits_3(monkeypatch):
    monkeypatch.setattr(run, "estimate_memory", lambda *a, **k: (10, 1))
    result = runner.invoke(app, ["generate", "x", "--engine", "fake"])
    assert result.exit_code == 3


def test_engine_error_exits_1(monkeypatch):
    from lig.backends.fake import FakeBackend

    monkeypatch.setattr(run, "make_backend", lambda *a, **k: FakeBackend(fail=True))
    result = runner.invoke(app, ["generate", "x", "--engine", "fake"])
    assert result.exit_code == 1


def _resolved(tmp_path, toml="", env=None):
    path = tmp_path / "c.toml"
    path.write_text(toml)
    return cfg.load_settings(env=env or {}, path=path)


def test_linux_defaults(tmp_path):
    resolved = _resolved(tmp_path)
    assert run.effective_size_and_steps(resolved, None, None, "linux") == ((768, 768), 30)
    assert run.effective_size_and_steps(resolved, None, None, "darwin") == ((1024, 1024), 40)


def test_flags_and_config_override_linux_defaults(tmp_path):
    resolved = _resolved(tmp_path, 'size = "512x512"\nsteps = 20\n')
    assert run.effective_size_and_steps(resolved, None, None, "linux") == ((512, 512), 20)
    plain = _resolved(tmp_path)
    assert run.effective_size_and_steps(plain, "640x640", 10, "linux") == ((640, 640), 10)


def test_zero_steps_is_usage_error(tmp_path):
    with pytest.raises(run.UsageError):
        run.effective_size_and_steps(_resolved(tmp_path), None, 0, "linux")


def test_empty_prompt_exits_2():
    assert runner.invoke(app, ["generate", " ", "--engine", "fake"]).exit_code == 2


def test_sidecar_records_request(tmp_path):
    runner.invoke(app, ["generate", "x", "--engine", "fake", "--seed", "7", "--size", "256x256"])
    sidecar = json.loads(next((Path("outputs")).glob("*.json")).read_text())
    assert sidecar["seed"] == 7 and sidecar["size"] == [256, 256]


def test_memory_preflight_still_exported():
    assert callable(cli_app.memory_preflight)
