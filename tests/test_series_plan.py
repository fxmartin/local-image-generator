"""Story 09.2-003: `--plan-only`, `--from-plan` and `--resume`, offline with the stub gemma."""

import json

import pytest
from typer.testing import CliRunner

from lig.series.cli import app
from lig.series.plan import SeriesPlan, format_plan, read_plan
from lig.series.settings import SeriesError, SeriesSettings
from lig.series.shots import Shot
from tests.test_series_runner import GLOBAL, SCENE, _stub_replies

runner = CliRunner()


def _invoke(gemma, out, *extra, request="Create 3 photos of a woman in Paris"):
    args = [] if request is None else [request]
    return runner.invoke(
        app,
        [*args, "--engine", "fake", "--gemma", str(gemma), "--out", str(out),
         "--size", "256x256", "--steps", "1", *extra],
    )  # fmt: skip


def _plan_only(tmp_path, monkeypatch):
    gemma = _stub_replies(monkeypatch, tmp_path)
    out = tmp_path / "planned"
    result = _invoke(gemma, out, "--plan-only")
    return gemma, out, result


def test_plan_only_writes_plan_prints_and_renders_nothing(tmp_path, monkeypatch):
    _, out, result = _plan_only(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    assert list(out.glob("*.png")) == [] and not (out / "series.json").exists()
    plan = json.loads((out / "plan.json").read_text())
    assert len(plan["shots"]) == 3 and plan["settings"]["style"] == "black and white"
    lines = result.stdout.splitlines()
    assert lines[0].startswith("count:") and any(line.startswith("3. Lamp:") for line in lines)
    assert "Style: black and white" in lines[-1]


def test_from_plan_renders_without_gemma(tmp_path, monkeypatch):
    _, out, _ = _plan_only(tmp_path, monkeypatch)
    plan_file = out / "plan.json"
    data = json.loads(plan_file.read_text())
    data["shots"][0]["scene"] = "edited " + SCENE
    data["shots"][0]["prompt"] = "stale"
    plan_file.write_text(json.dumps(data))
    rendered = tmp_path / "rendered"
    result = runner.invoke(
        app,
        ["--from-plan", str(plan_file), "--gemma", str(tmp_path / "missing"), "--engine", "fake",
         "--out", str(rendered), "--size", "256x256", "--steps", "1", "--seed", "3"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert len(list(rendered.glob("*.png"))) == 3
    shot = json.loads((rendered / "series.json").read_text())["shots"][0]
    assert shot["prompt"] != "stale" and "edited" in shot["prompt"]


def test_from_plan_rejects_invalid_plan(tmp_path):
    bad = tmp_path / "plan.json"
    bad.write_text(json.dumps({"settings": GLOBAL, "shots": []}))
    result = runner.invoke(app, ["--from-plan", str(bad), "--out", str(tmp_path / "o")])
    assert result.exit_code == 2 and "invalid plan" in result.output


def test_from_plan_missing_file_exits_2(tmp_path):
    result = runner.invoke(app, ["--from-plan", str(tmp_path / "nope.json")])
    assert result.exit_code == 2


def test_resume_renders_only_missing_shots(tmp_path, monkeypatch):
    _, out, _ = _plan_only(tmp_path, monkeypatch)
    series = tmp_path / "series"
    args = ["--from-plan", str(out / "plan.json"), "--engine", "fake", "--out", str(series),
            "--size", "256x256", "--steps", "1", "--seed", "3"]  # fmt: skip
    assert runner.invoke(app, args).exit_code == 0
    pngs = sorted(series.glob("*.png"))
    assert len(pngs) == 3
    stamps = {p: p.stat().st_mtime_ns for p in (pngs[0], pngs[2])}
    pngs[1].unlink()
    result = runner.invoke(app, [*args, "--resume"])
    assert result.exit_code == 0, result.output
    assert len(sorted(series.glob("*.png"))) == 3
    assert stamps == {p: p.stat().st_mtime_ns for p in stamps}
    records = json.loads((series / "series.json").read_text())["shots"]
    assert [r["status"] for r in records] == ["done"] * 3


def test_resume_without_series_json_exits_2(tmp_path, monkeypatch):
    _, out, _ = _plan_only(tmp_path, monkeypatch)
    result = runner.invoke(
        app, ["--from-plan", str(out / "plan.json"), "--out", str(out), "--resume"]
    )
    assert result.exit_code == 2


@pytest.mark.parametrize(
    "extra",
    [["--resume"], ["--from-plan", "x", "--plan-only"], ["--from-plan", "x", "--resume"], []],
)
def test_bad_flag_combinations_exit_2(extra):
    request = [] if "--from-plan" in extra else ([] if not extra else ["req"])
    result = runner.invoke(app, [*request, *extra])
    assert result.exit_code == 2


def test_format_and_count_mismatch():
    settings = SeriesSettings.model_validate({**GLOBAL, "count": 1})
    shot = Shot(title="T", scene=SCENE, prompt="p")
    text = format_plan(SeriesPlan(settings=settings, shots=[shot]).recomposed())
    assert text.splitlines()[-1].startswith("1. T: ")
    with pytest.raises(ValueError):
        SeriesPlan(settings=settings, shots=[shot, shot])


def test_read_plan_error_is_series_error(tmp_path):
    with pytest.raises(SeriesError):
        read_plan(tmp_path / "missing.json")
