import json

import pytest
from typer.testing import CliRunner

from lig.backends.base import EngineError
from lig.backends.fake import FakeBackend
from lig.cli import app as cli_app
from lig.cli.app import app
from lig.core import run
from lig.models.registry import RegistryError

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    for key in ("LIG_ENGINE", "LIG_SIZE", "LIG_STEPS", "LIG_OUTPUT_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


def _sidecars(tmp_path):
    return [
        json.loads(p.read_text())
        for p in sorted((tmp_path / "outputs").glob("*.json"))
        if "_sheet" not in p.name
    ]


def test_consecutive_seeds_share_batch_id(tmp_path):
    result = runner.invoke(
        app,
        ["seeds", "a fox", "--count", "4", "--seed-start", "100", "--engine", "fake",
         "--size", "256x256", "--steps", "1"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert len(list((tmp_path / "outputs").glob("*.png"))) == 4 + 1  # renders + sheet
    sidecars = _sidecars(tmp_path)
    assert sorted(s["seed"] for s in sidecars) == [100, 101, 102, 103]
    assert len({s["batch_id"] for s in sidecars}) == 1 and sidecars[0]["batch_id"]


@pytest.mark.parametrize("count", ["9", "0"])
def test_count_out_of_range_exits_2(count, monkeypatch):
    monkeypatch.setattr(run, "make_backend", lambda *a, **k: pytest.fail("no engine"))
    result = runner.invoke(app, ["seeds", "x", "--count", count, "--engine", "fake"])
    assert result.exit_code == 2
    assert "max 8" in result.output


def test_seed_range_overflow_exits_2():
    result = runner.invoke(
        app, ["seeds", "x", "--count", "2", "--seed-start", str(2**32 - 1), "--engine", "fake"]
    )
    assert result.exit_code == 2


def test_random_start_is_printed(tmp_path):
    result = runner.invoke(
        app, ["seeds", "x", "--count", "2", "--engine", "fake", "--size", "256x256", "--steps", "1"]
    )
    assert result.exit_code == 0, result.output
    seeds = sorted(s["seed"] for s in _sidecars(tmp_path))
    assert seeds[1] == seeds[0] + 1
    assert f"seed start: {seeds[0]}" in result.output


def test_failure_on_third_seed_keeps_first_two(tmp_path, monkeypatch):
    real = FakeBackend()

    class Flaky(FakeBackend):
        def generate(self, request, on_progress):
            if request.seed == 12:
                raise EngineError("boom", "engine stderr")
            return real.generate(request, on_progress)

    monkeypatch.setattr(run, "make_backend", lambda *a, **k: Flaky())
    result = runner.invoke(
        app,
        ["seeds", "x", "--count", "4", "--seed-start", "10", "--engine", "fake",
         "--size", "256x256", "--steps", "1"],
    )  # fmt: skip
    assert result.exit_code == 1
    assert "seed 12" in result.output
    assert sorted(s["seed"] for s in _sidecars(tmp_path)) == [10, 11]


def test_invalid_size_exits_2(tmp_path):
    result = runner.invoke(app, ["seeds", "x", "--engine", "fake", "--size", "100x100"])
    assert result.exit_code == 2
    assert not (tmp_path / "outputs").exists()


def test_negative_prompt_warning_at_default_guidance(tmp_path):
    result = runner.invoke(
        app,
        ["seeds", "x", "--count", "2", "--engine", "fake", "--size", "256x256", "--steps", "1",
         "--negative", "blurry"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "negative prompt has no effect" in result.output


def test_registry_error_during_memory_estimate_exits_1(monkeypatch):
    def boom(*a, **k):
        raise RegistryError("no such model")

    monkeypatch.setattr(run, "estimate_memory", boom)
    result = runner.invoke(
        app, ["seeds", "x", "--engine", "fake", "--size", "256x256", "--steps", "1"]
    )
    assert result.exit_code == 1
    assert "no such model" in result.output


def test_memory_preflight_receives_figures_and_force(monkeypatch):
    calls = []
    monkeypatch.setattr(run, "estimate_memory", lambda *a, **k: (10, 1))
    monkeypatch.setattr(cli_app, "memory_preflight", lambda *a: calls.append(a))
    result = runner.invoke(
        app, ["seeds", "x", "--engine", "fake", "--size", "256x256", "--steps", "1", "--force"]
    )
    assert result.exit_code == 0, result.output
    assert calls == [(10, 1, True)]


def test_no_sheet_writes_only_renders(tmp_path):
    result = runner.invoke(
        app,
        ["seeds", "x", "--count", "2", "--engine", "fake", "--size", "256x256", "--steps", "1",
         "--no-sheet"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert not list((tmp_path / "outputs").glob("*_sheet*"))
