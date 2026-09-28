"""Story 09.2-003: `--plan-only`, `--from-plan` and `--resume`, offline with the stub gemma."""

import json
from pathlib import Path

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


def _logging_gemma(tmp_path, gemma):
    """Wrap the stub gemma so every call appends `global` or `shot` to a log file."""
    log = tmp_path / "gemma-calls.log"
    script = tmp_path / "gemma-logged"
    script.write_text(
        "#!/bin/sh\n"
        f'case "$*" in *"plan a series"*) kind=global ;; *) kind=shot ;; esac\n'
        f'echo "$kind" >> "{log}"\n'
        f'exec "{gemma}" "$@"\n'
    )
    script.chmod(0o755)
    return script, log


def _interrupt_live_series(tmp_path, monkeypatch):
    """A live 3-shot series stopped on shot 2 like a dropped server: 2 failed, 3 skipped."""
    gemma = _stub_replies(monkeypatch, tmp_path)
    series = tmp_path / "live"
    assert _invoke(gemma, series, "--seed", "4", "--no-sheet").exit_code == 0
    manifest = json.loads((series / "series.json").read_text())
    first, second, third = manifest["shots"]
    for record in (second, third):
        Path(record["png"]).unlink()
    second.update(status="failed", png=None, sidecar=None, exit_code=1,
                  scene="kept " + " ".join(["scene"] * 24))  # fmt: skip
    manifest["shots"][2] = {"index": 3, "status": "skipped"}
    (series / "series.json").write_text(json.dumps(manifest))
    return gemma, series, first


def test_resume_live_series_replans_only_unplanned_shots(tmp_path, monkeypatch):
    gemma, series, first = _interrupt_live_series(tmp_path, monkeypatch)
    first_png = Path(first["png"])
    stamp = first_png.stat().st_mtime_ns
    logged, log = _logging_gemma(tmp_path, gemma)
    result = runner.invoke(
        app,
        ["--resume", "--out", str(series), "--gemma", str(logged), "--engine", "fake",
         "--size", "256x256", "--steps", "1"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert log.read_text().split() == ["shot"]  # no global call; shot 2 keeps its scene
    assert first_png.stat().st_mtime_ns == stamp
    manifest = json.loads((series / "series.json").read_text())
    assert manifest["seed"] == 4
    records = manifest["shots"]
    assert [r["status"] for r in records] == ["done"] * 3
    assert "kept" in records[1]["prompt"] and records[2]["title"] == "Lamp"
    assert all(Path(r["png"]).exists() for r in records)


def test_resume_live_series_without_series_json_exits_2(tmp_path):
    result = runner.invoke(app, ["--resume", "--out", str(tmp_path / "none")])
    assert result.exit_code == 2 and "series.json" in result.output


def test_resume_live_series_rejects_a_request(tmp_path):
    result = runner.invoke(app, ["req", "--resume", "--out", str(tmp_path)])
    assert result.exit_code == 2
