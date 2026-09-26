"""Story 09.2-001: the series runner drives the real `lig` (fake engine) and the stub `gemma`."""

import json
import re
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lig.series.cli import app
from lig.series.runner import LIG_ARGV, LigFlags, run_series
from lig.series.settings import SeriesError, SeriesSettings

runner = CliRunner()
LOOK = " ".join(["woman"] + ["word"] * 29)
SCENE = " ".join(["scene"] * 25)
GLOBAL = {
    "count": 3,
    "character": {"name": "Camille", "look": LOOK},
    "style": "black and white",
    "setting": "Paris",
    "arc": "Morning to midnight.",
}


def _settings(count: int = 3) -> SeriesSettings:
    return SeriesSettings.model_validate({**GLOBAL, "count": count})


class FakePlanner:
    """Yields shots lazily and records what has happened so far, to prove the interleaving."""

    def __init__(self, events: list[str], fail_at: int | None = None) -> None:
        self.events = events
        self.fail_at = fail_at

    def __call__(self, settings):
        from lig.series.shots import Shot

        for index in range(1, settings.count + 1):
            if index == self.fail_at:
                raise SeriesError("gemma broke", 1)
            self.events.append(f"plan{index}")
            yield Shot(title=f"Title {index}", scene=SCENE, prompt=f"prompt {index}")


class RecordingLig:
    def __init__(self, events: list[str], codes: dict[int, int] | None = None) -> None:
        self.events = events
        self.codes = codes or {}
        self.calls: list[list[str]] = []

    def __call__(self, argv, label):
        self.calls.append(argv)
        index = len(self.calls)
        self.events.append(f"render{index}")
        code = self.codes.get(index, 0)
        return code, (f"/out/{index}.png" if code == 0 else "")


def test_loop_interleaves_plan_and_render_and_passes_flags(tmp_path):
    events: list[str] = []
    lig = RecordingLig(events)
    flags = LigFlags(size="768x768", steps=30, engine="fake", negative="blur", guidance=1.5)
    result = run_series(
        _settings(),
        FakePlanner(events),
        out_dir=tmp_path,
        seed=7,
        flags=flags,
        render=lig,
    )
    assert events == ["plan1", "render1", "plan2", "render2", "plan3", "render3"]
    assert result.exit_code == 0
    assert [str(p) for p in result.paths] == ["/out/1.png", "/out/2.png", "/out/3.png"]
    assert lig.calls[0] == [
        "generate", "prompt 1", "--seed", "7", "--out", str(tmp_path),
        "--size", "768x768", "--steps", "30", "--engine", "fake",
        "--negative", "blur", "--guidance", "1.5",
    ]  # fmt: skip


def test_unset_flags_are_not_passed(tmp_path):
    lig = RecordingLig([])
    run_series(
        _settings(1), FakePlanner([]), out_dir=tmp_path, seed=1, flags=LigFlags(), render=lig
    )
    assert lig.calls[0] == ["generate", "prompt 1", "--seed", "1", "--out", str(tmp_path)]


def test_host_passes_through(tmp_path):
    lig = RecordingLig([])
    run_series(
        _settings(1), FakePlanner([]), out_dir=tmp_path, seed=1,
        flags=LigFlags(host="mac"), render=lig,
    )  # fmt: skip
    assert lig.calls[0][-2:] == ["--host", "mac"]


def test_lig_failure_stops_and_returns_its_code(tmp_path):
    events: list[str] = []
    lig = RecordingLig(events, codes={2: 4})
    result = run_series(
        _settings(), FakePlanner(events), out_dir=tmp_path, seed=1, flags=LigFlags(), render=lig
    )
    assert result.exit_code == 4
    assert len(result.paths) == 1
    assert "plan3" not in events


def test_keep_going_renders_the_rest_and_exits_1(tmp_path):
    lig = RecordingLig([], codes={1: 4})
    result = run_series(
        _settings(), FakePlanner([]), out_dir=tmp_path, seed=1, flags=LigFlags(),
        render=lig, keep_going=True,
    )  # fmt: skip
    assert result.exit_code == 1
    assert len(lig.calls) == 3 and len(result.paths) == 2


def test_planning_failure_keeps_finished_shots(tmp_path):
    lig = RecordingLig([])
    result = run_series(
        _settings(), FakePlanner([], fail_at=2), out_dir=tmp_path, seed=1,
        flags=LigFlags(), render=lig,
    )  # fmt: skip
    assert result.exit_code == 1 and len(result.paths) == 1


def test_series_json_records_seed_and_shots(tmp_path):
    run_series(
        _settings(2), FakePlanner([]), out_dir=tmp_path, seed=99, flags=LigFlags(),
        render=RecordingLig([]),
    )  # fmt: skip
    data = json.loads((tmp_path / "series.json").read_text())
    assert data["seed"] == 99
    assert [s["png"] for s in data["shots"]] == ["/out/1.png", "/out/2.png"]


def test_lig_argv_runs_the_current_interpreter():
    assert LIG_ARGV[0] == sys.executable


# --- integration: real `lig --engine fake` + stub gemma, offline ------------------------------


def _stub_replies(monkeypatch, tmp_path):
    """Stub gemma answers the global call, then every shot call, from one script."""
    script = tmp_path / "gemma-multi"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "system = sys.argv[sys.argv.index('--system') + 1]\n"
        "sys.stdin.read()\n"
        f"glob = {json.dumps(json.dumps(GLOBAL))}\n"
        f"shot = {json.dumps(json.dumps({'title': 'Lamp', 'scene': SCENE}))}\n"
        "print(glob if 'plan a series' in system else shot)\n"
    )
    script.chmod(0o755)
    return script


def test_end_to_end_with_fake_engine(tmp_path, monkeypatch):
    gemma = _stub_replies(monkeypatch, tmp_path)
    out = tmp_path / "series-out"
    result = runner.invoke(
        app,
        ["Create 3 photos of a woman in Paris", "--engine", "fake", "--gemma", str(gemma),
         "--seed", "5", "--out", str(out), "--size", "256x256", "--steps", "1"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    pngs = sorted(out.glob("*.png"))
    assert len(pngs) == 4  # 3 shots + sheet.png
    assert (out / "sheet.png").is_file()
    paths = [line for line in result.stdout.splitlines() if line.endswith(".png")]
    assert len(paths) == 3
    assert all(Path(p).exists() for p in paths)
    assert json.loads((out / "series.json").read_text())["seed"] == 5


def test_default_out_dir_is_timestamped_under_cwd(tmp_path, monkeypatch):
    gemma = _stub_replies(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["Create 1 photo of a woman in Paris", "--engine", "fake", "--gemma", str(gemma),
         "--size", "256x256", "--steps", "1"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    dirs = list((tmp_path / "series").iterdir())
    assert len(dirs) == 1
    assert re.fullmatch(r"\d{8}-\d{6}_create-1-photo.*", dirs[0].name)


def test_missing_gemma_exits_4(tmp_path):
    result = runner.invoke(
        app, ["x", "--gemma", str(tmp_path / "nope"), "--out", str(tmp_path / "o")]
    )
    assert result.exit_code == 4


@pytest.mark.parametrize("flag", ["--keep-going"])
def test_help_lists_flags(flag):
    assert flag in runner.invoke(app, ["--help"], terminal_width=200).output


# --- Story 09.2-002: series.json manifest -----------------------------------------------------


def test_manifest_validates_and_has_every_field(tmp_path):
    from lig import __version__
    from lig.series.manifest import read_manifest

    run_series(
        _settings(2), FakePlanner([]), out_dir=tmp_path, seed=9, flags=LigFlags(),
        render=RecordingLig([]), request="two photos", gemma_model="gemma-4b",
    )  # fmt: skip
    manifest = read_manifest(tmp_path)
    assert manifest.request == "two photos"
    assert manifest.gemma_model == "gemma-4b"
    assert manifest.plan == _settings(2)
    assert (manifest.continuity, manifest.seed, manifest.lig_version) == ("prompt", 9, __version__)
    first = manifest.shots[0]
    assert (first.status, first.title, first.prompt) == ("done", "Title 1", "prompt 1")
    assert (first.png, first.sidecar, first.exit_code) == ("/out/1.png", "/out/1.json", 0)
    assert first.wall_seconds is not None and first.wall_seconds >= 0


def test_manifest_is_written_after_each_shot(tmp_path):
    from lig.series.manifest import read_manifest

    seen: list[int] = []

    def render(argv, label):
        seen.append(len(read_manifest(tmp_path).shots))
        return 0, "/out/x.png"

    run_series(_settings(3), FakePlanner([]), out_dir=tmp_path, seed=1, flags=LigFlags(),
               render=render)  # fmt: skip
    assert seen == [0, 1, 2]


def test_failure_records_failed_and_skipped_shots(tmp_path):
    from lig.series.manifest import read_manifest

    run_series(
        _settings(4), FakePlanner([]), out_dir=tmp_path, seed=1, flags=LigFlags(),
        render=RecordingLig([], codes={2: 4}),
    )  # fmt: skip
    shots = read_manifest(tmp_path).shots
    assert [(s.index, s.status) for s in shots] == [
        (1, "done"), (2, "failed"), (3, "skipped"), (4, "skipped")
    ]  # fmt: skip
    assert shots[1].exit_code == 4 and shots[1].png is None


def test_planning_failure_is_recorded(tmp_path):
    from lig.series.manifest import read_manifest

    run_series(
        _settings(3), FakePlanner([], fail_at=2), out_dir=tmp_path, seed=1, flags=LigFlags(),
        render=RecordingLig([]),
    )  # fmt: skip
    assert [s.status for s in read_manifest(tmp_path).shots] == ["done", "failed", "skipped"]


def test_keep_going_records_failed_then_done(tmp_path):
    from lig.series.manifest import read_manifest

    run_series(
        _settings(), FakePlanner([]), out_dir=tmp_path, seed=1, flags=LigFlags(),
        render=RecordingLig([], codes={1: 4}), keep_going=True,
    )  # fmt: skip
    assert [s.status for s in read_manifest(tmp_path).shots] == ["failed", "done", "done"]


def test_gemma_status_reports_model(tmp_path):
    from lig.series.gemma import GemmaClient

    script = tmp_path / "gemma"
    script.write_text("#!/bin/sh\n[ \"$1\" = --status ] && echo 'model: gemma-4b'\n")
    script.chmod(0o755)
    assert GemmaClient(binary=str(script)).status() == "model: gemma-4b"
    assert GemmaClient(binary=str(tmp_path / "nope")).status() is None
    failing = tmp_path / "bad"
    failing.write_text("#!/bin/sh\nexit 3\n")
    failing.chmod(0o755)
    assert GemmaClient(binary=str(failing)).status() is None


def test_end_to_end_manifest_links_real_sidecars(tmp_path):
    from lig.series.manifest import read_manifest

    gemma = _stub_replies(None, tmp_path)
    out = tmp_path / "o"
    result = runner.invoke(
        app,
        ["Create 2 photos of a woman in Paris", "--engine", "fake", "--gemma", str(gemma),
         "--seed", "5", "--out", str(out), "--size", "256x256", "--steps", "1"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    for shot in read_manifest(out).shots:
        assert shot.png and Path(shot.png).exists()
        assert shot.sidecar and Path(shot.sidecar).exists()
