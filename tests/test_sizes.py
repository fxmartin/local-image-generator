import json

import pytest
from PIL import Image
from typer.testing import CliRunner

from lig.backends.base import EngineError
from lig.backends.fake import FakeBackend
from lig.cli import app as cli_app
from lig.cli import scripting
from lig.cli.app import app
from lig.core import run
from lig.core.sheet import SHEET_TILE_PX, build_sheet
from lig.models.registry import RegistryError

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    for key in ("LIG_ENGINE", "LIG_SIZE", "LIG_STEPS", "LIG_OUTPUT_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


def _run(*extra):
    return runner.invoke(
        app,
        ["sizes", "a fox", "--seed", "7", "--engine", "fake", "--steps", "1", *extra],
    )  # fmt: skip


def _renders(tmp_path):
    return sorted(p for p in (tmp_path / "outputs").glob("*.png") if "_sheet" not in p.name)


def test_each_size_renders_with_same_seed_and_batch(tmp_path):
    result = _run("--sizes", "256x256,512x256,256x512")
    assert result.exit_code == 0, result.output
    sidecars = [json.loads(p.with_suffix(".json").read_text()) for p in _renders(tmp_path)]
    assert sorted(tuple(s["size"]) for s in sidecars) == [
        (256, 256), (256, 512), (512, 256),
    ]  # fmt: skip
    assert {s["seed"] for s in sidecars} == {7}
    assert len({s["batch_id"] for s in sidecars}) == 1


def test_sheet_is_labelled_by_size(tmp_path):
    result = _run("--sizes", "256x256,512x256")
    assert result.exit_code == 0, result.output
    (sheet_path,) = (tmp_path / "outputs").glob("*_sheet.png")
    assert sheet_path.name in result.output
    sidecar = json.loads(sheet_path.with_suffix(".json").read_text())
    assert [m["label"] for m in sidecar["members"]] == ["256x256", "512x256"]
    assert [m["seed"] for m in sidecar["members"]] == [7, 7]
    # 1x2 grid of 512x256 cells: tiles at or under the tile cap are not enlarged
    assert Image.open(sheet_path).size == (2 * SHEET_TILE_PX, 256)


def test_invalid_size_exits_2_before_rendering(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "make_backend", lambda *a, **k: pytest.fail("no engine"))
    result = _run("--sizes", "256x256,100x100")
    assert result.exit_code == 2
    assert "100x100" in result.output
    assert not (tmp_path / "outputs").exists()


@pytest.mark.parametrize("sizes", ["", "256x256,", "256x256,256x256", "banana"])
def test_bad_sizes_list_exits_2(sizes):
    assert _run("--sizes", sizes).exit_code == 2


def test_too_many_sizes_exits_2():
    assert _run("--sizes", ",".join(["256x256"] * 9)).exit_code == 2


def test_no_sheet_writes_only_renders(tmp_path):
    result = _run("--sizes", "256x256,512x256", "--no-sheet")
    assert result.exit_code == 0, result.output
    assert not list((tmp_path / "outputs").glob("*_sheet*"))
    assert len(_renders(tmp_path)) == 2


def test_json_document(tmp_path):
    result = _run("--sizes", "256x256,512x256", "--json")
    assert result.exit_code == 0, result.output
    doc = json.loads(result.stdout)
    assert doc["seed"] == 7
    assert [tuple(i["size"]) for i in doc["images"]] == [(256, 256), (512, 256)]
    assert doc["sheet"].endswith("_sheet.png")


def test_random_seed_is_printed_and_shared(tmp_path):
    result = runner.invoke(
        app, ["sizes", "x", "--sizes", "256x256,512x256", "--engine", "fake", "--steps", "1"]
    )
    assert result.exit_code == 0, result.output
    seeds = {json.loads(p.with_suffix(".json").read_text())["seed"] for p in _renders(tmp_path)}
    assert len(seeds) == 1
    assert f"seed: {seeds.pop()}" in result.output


def test_help_says_tiles_are_not_upscales():
    result = runner.invoke(app, ["sizes", "--help"])
    assert result.exit_code == 0
    text = " ".join(result.output.split())
    assert "not upscales" in text


def test_build_sheet_uses_label_callback(tmp_path):
    for name in ("a", "b"):
        Image.new("RGB", (64, 64), "red").save(tmp_path / f"{name}.png")
    sheet = build_sheet(
        [(tmp_path / "a.png", 1), (tmp_path / "b.png", 2)],
        tmp_path,
        "batch",
        label=lambda path, seed: f"{path.stem}-{seed}",
    )
    members = json.loads(sheet.with_suffix(".json").read_text())["members"]
    assert [m["label"] for m in members] == ["a-1", "b-2"]


def test_seed_out_of_range_exits_2():
    result = runner.invoke(
        app, ["sizes", "x", "--sizes", "256x256", "--seed", "-1", "--engine", "fake"]
    )
    assert result.exit_code == 2


def test_bad_config_exits_2(tmp_path):
    cfg_dir = tmp_path / "cfg" / "lig"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.toml").write_text("this is [not toml")
    assert _run("--sizes", "256x256").exit_code == 2


def test_negative_prompt_warning_at_default_guidance():
    result = _run("--sizes", "256x256", "--negative", "blurry")
    assert result.exit_code == 0, result.output
    assert "negative prompt has no effect" in result.output


def test_failure_on_second_size_keeps_first(tmp_path, monkeypatch):
    real = FakeBackend()

    class Flaky(FakeBackend):
        def generate(self, request, on_progress):
            if request.width == 512:
                raise EngineError("boom", "engine stderr")
            return real.generate(request, on_progress)

    monkeypatch.setattr(run, "make_backend", lambda *a, **k: Flaky())
    result = _run("--sizes", "256x256,512x256")
    assert result.exit_code == 1
    assert "size 512x256 failed; kept 1 of 2" in result.output
    assert len(_renders(tmp_path)) == 1


def test_registry_error_during_memory_estimate_exits_1(monkeypatch):
    def boom(*a, **k):
        raise RegistryError("no such model")

    monkeypatch.setattr(run, "estimate_memory", boom)
    result = _run("--sizes", "256x256")
    assert result.exit_code == 1
    assert "no such model" in result.output


def test_memory_preflight_uses_largest_tile(monkeypatch):
    seen = []
    monkeypatch.setattr(
        run,
        "estimate_memory",
        lambda reg, eng, req: seen.append((req.width, req.height)) or (10, 1),
    )
    calls = []
    monkeypatch.setattr(cli_app, "memory_preflight", lambda *a: calls.append(a))
    result = _run("--sizes", "256x256,512x256", "--force")
    assert result.exit_code == 0, result.output
    assert seen == [(512, 256)]
    assert calls == [(10, 1, True)]


def test_open_launches_viewer_on_sheet(monkeypatch):
    launched = []
    monkeypatch.setattr(scripting, "_popen", lambda argv, **_: launched.append(argv))
    assert _run("--sizes", "256x256,512x256", "--open").exit_code == 0
    assert len(launched) == 1 and "_sheet" in launched[0][-1]


def test_open_without_sheet_launches_each_render(monkeypatch):
    launched = []
    monkeypatch.setattr(scripting, "_popen", lambda argv, **_: launched.append(argv))
    assert _run("--sizes", "256x256,512x256", "--no-sheet", "--open").exit_code == 0
    assert len(launched) == 2
