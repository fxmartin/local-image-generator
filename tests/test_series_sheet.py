"""Story 09.2-004: series contact sheet."""

from pathlib import Path

from PIL import Image
from typer.testing import CliRunner

from lig.series.cli import app
from lig.series.runner import LigFlags, run_series
from lig.series.settings import SeriesSettings
from lig.series.sheet import LABEL_H, TILE_PX, build_sheet, grid_shape
from tests.test_series_runner import GLOBAL, FakePlanner

runner = CliRunner()


def _png(path: Path, size=(64, 48)) -> Path:
    Image.new("RGB", size, "red").save(path)
    return path


class PngLig:
    """Renders a real PNG per call; codes maps call index -> exit code."""

    def __init__(self, out: Path, codes: dict[int, int] | None = None) -> None:
        self.out, self.codes, self.n = out, codes or {}, 0

    def __call__(self, argv, label):
        self.n += 1
        code = self.codes.get(self.n, 0)
        return code, str(_png(self.out / f"{self.n}.png")) if code == 0 else ""


def _run(tmp_path, count=3, **kwargs):
    settings = SeriesSettings.model_validate({**GLOBAL, "count": count})
    return run_series(
        settings, FakePlanner([]), out_dir=tmp_path, seed=1, flags=LigFlags(),
        render=PngLig(tmp_path, kwargs.pop("codes", None)), **kwargs,
    )  # fmt: skip


def test_grid_shape_is_near_square():
    assert grid_shape(10) == (3, 4)
    assert grid_shape(2) == (1, 2)
    assert grid_shape(9) == (3, 3)


def test_ten_shots_make_a_4x3_grid_of_384_tiles(tmp_path):
    shots = [(i, f"T{i}", _png(tmp_path / f"{i}.png")) for i in range(1, 11)]
    with Image.open(build_sheet(shots, tmp_path)) as sheet:
        assert sheet.size == (4 * TILE_PX, 3 * (TILE_PX + LABEL_H))


def test_labels_are_drawn_under_each_tile(tmp_path):
    shots = [(1, "One", _png(tmp_path / "a.png")), (2, "Two", _png(tmp_path / "b.png"))]
    with Image.open(build_sheet(shots, tmp_path)) as sheet:
        label = sheet.crop((0, TILE_PX, TILE_PX, TILE_PX + LABEL_H))
        assert label.getextrema() != ((0, 0), (0, 0), (0, 0))  # white text on black


def test_finished_series_writes_sheet(tmp_path):
    _run(tmp_path)
    assert (tmp_path / "sheet.png").is_file()


def test_no_sheet_skips_it(tmp_path):
    _run(tmp_path, sheet=False)
    assert not (tmp_path / "sheet.png").exists()


def test_single_shot_gets_no_sheet(tmp_path):
    _run(tmp_path, count=1)
    assert not (tmp_path / "sheet.png").exists()


def test_failed_shots_are_left_out(tmp_path):
    _run(tmp_path, count=4, codes={2: 4}, keep_going=True)
    with Image.open(tmp_path / "sheet.png") as sheet:
        assert sheet.size == (2 * TILE_PX, 2 * (TILE_PX + LABEL_H))  # 3 rendered -> 2x2


def test_one_survivor_means_no_sheet(tmp_path):
    _run(tmp_path, count=3, codes={1: 4, 3: 4}, keep_going=True)
    assert not (tmp_path / "sheet.png").exists()


def test_unreadable_image_only_warns(tmp_path, capsys):
    settings = SeriesSettings.model_validate({**GLOBAL, "count": 2})
    result = run_series(
        settings, FakePlanner([]), out_dir=tmp_path, seed=1, flags=LigFlags(),
        render=lambda argv, label: (0, str(tmp_path / "missing.png")),
    )  # fmt: skip
    assert result.exit_code == 0
    assert "contact sheet not written" in capsys.readouterr().err


def test_cli_advertises_no_sheet():
    assert "--no-sheet" in runner.invoke(app, ["--help"]).output


def test_tiles_carry_each_shots_number_and_title_even_after_a_failure(tmp_path, monkeypatch):
    # Issue #76: tiles read "Shot N" and were numbered by position among rendered images.
    from lig.series import runner as series_runner

    seen = []
    monkeypatch.setattr(
        series_runner.contact_sheet, "build_sheet", lambda shots, out: seen.extend(shots) or out
    )
    _run(tmp_path, count=4, codes={2: 4}, keep_going=True)
    assert [(number, title) for number, title, _ in seen] == [
        (1, "Title 1"),
        (3, "Title 3"),
        (4, "Title 4"),
    ]
