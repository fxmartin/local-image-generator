import json

import pytest
from PIL import Image
from typer.testing import CliRunner

from lig.cli.app import app
from lig.core.sheet import SHEET_TILE_PX, grid_shape

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
        ["seeds", "a fox", "--seed-start", "7", "--engine", "fake", "--size", "1024x768",
         "--steps", "1", *extra],
    )  # fmt: skip


@pytest.mark.parametrize(
    ("count", "shape"), [(1, (1, 1)), (2, (1, 2)), (4, (2, 2)), (5, (2, 3)), (8, (3, 3))]
)
def test_grid_shape_is_near_square(count, shape):
    assert grid_shape(count) == shape


def _mean(img):
    return [
        sum(ch) / len(ch) for ch in zip(*img.convert("RGB").resize((8, 8)).getdata(), strict=True)
    ]


def test_sheet_dimensions_and_tile_colours(tmp_path):
    result = _run("--count", "4")
    assert result.exit_code == 0, result.output
    out = tmp_path / "outputs"
    sheets = list(out.glob("*_sheet.png"))
    assert len(sheets) == 1
    sheet = Image.open(sheets[0]).convert("RGB")
    tile_w, tile_h = SHEET_TILE_PX, SHEET_TILE_PX * 768 // 1024
    assert sheet.size == (2 * tile_w, 2 * tile_h)

    sidecar = json.loads(sheets[0].with_suffix(".json").read_text())
    assert [m["seed"] for m in sidecar["members"]] == [7, 8, 9, 10]
    for i, member in enumerate(sidecar["members"]):
        render = Image.open(out / member["file"]).convert("RGB")
        x, y = (i % 2) * tile_w, (i // 2) * tile_h
        # compare a label-free strip (bottom half) of tile vs render
        tile = sheet.crop((x, y + tile_h // 2, x + tile_w, y + tile_h))
        ref = render.crop((0, render.height // 2, render.width, render.height))
        assert all(abs(a - b) < 8 for a, b in zip(_mean(tile), _mean(ref), strict=True))


def test_sheet_paths_are_printed_and_not_a_member(tmp_path):
    result = _run("--count", "3")
    assert "_sheet.png" in result.output
    assert len(list((tmp_path / "outputs").glob("*.png"))) == 4


def test_eight_tiles_leave_an_empty_cell(tmp_path):
    assert _run("--count", "8").exit_code == 0
    sheet = Image.open(next((tmp_path / "outputs").glob("*_sheet.png")))
    assert sheet.size[0] == 3 * SHEET_TILE_PX


def test_no_sheet_flag(tmp_path):
    assert _run("--count", "2", "--no-sheet").exit_code == 0
    assert not list((tmp_path / "outputs").glob("*_sheet*"))
