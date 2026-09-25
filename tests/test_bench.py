import json
import sys

import pytest
from typer.testing import CliRunner

from lig.backends.base import Availability
from lig.backends.fake import FakeBackend
from lig.cli.app import app
from lig.core import bench, run

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    for key in ("LIG_ENGINE", "LIG_SIZE", "LIG_STEPS", "LIG_OUTPUT_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


def _bench_json(tmp_path):
    files = list((tmp_path / "bench").glob("*.json"))
    assert len(files) == 1
    return files[0], json.loads(files[0].read_text())


def test_bench_fake_records_every_field_and_writes_json(tmp_path):
    result = runner.invoke(app, ["bench", "--engines", "fake", "--size", "256x256", "--steps", "2"])
    assert result.exit_code == 0, result.output
    path, data = _bench_json(tmp_path)
    assert path.name.endswith(f"_{data['host']}.json")
    report = bench.BenchReport.model_validate(data)
    (entry,) = report.results
    assert entry.engine == "fake"
    assert entry.engine_version and entry.build_backend and entry.weights
    assert (entry.width, entry.height, entry.steps) == (256, 256, 2)
    assert len(entry.runs) == 1
    run0 = entry.runs[0]
    assert min(run0.load_s, run0.per_step_s, run0.total_s, run0.peak_rss_bytes) >= 0
    assert len(run0.image_sha256) == 64
    assert "fake" in result.output


def test_runs_keeps_all_and_reports_median(tmp_path):
    result = runner.invoke(
        app, ["bench", "--engines", "fake", "--size", "256x256", "--steps", "1", "--runs", "3"]
    )
    assert result.exit_code == 0, result.output
    _, data = _bench_json(tmp_path)
    entry = data["results"][0]
    assert len(entry["runs"]) == 3
    totals = sorted(r["total_s"] for r in entry["runs"])
    assert entry["median"]["total_s"] == totals[1]


def test_unavailable_engine_is_skipped_others_still_run(tmp_path, monkeypatch):
    real = run.make_backend

    class Down(FakeBackend):
        def available(self):
            return Availability(ok=False, reason="binary missing")

    monkeypatch.setattr(
        run,
        "make_backend",
        lambda name, *a, **k: Down() if name == "sdcpp" else real(name, *a, **k),
    )
    result = runner.invoke(
        app, ["bench", "--engines", "sdcpp,fake", "--size", "256x256", "--steps", "1"]
    )
    assert result.exit_code == 0, result.output
    _, data = _bench_json(tmp_path)
    assert [r["engine"] for r in data["results"]] == ["fake"]
    assert data["skipped"] == [{"engine": "sdcpp", "reason": "binary missing"}]
    assert "binary missing" in result.output


def test_unknown_engine_is_skipped_with_reason(tmp_path):
    result = runner.invoke(
        app, ["bench", "--engines", "nope,fake", "--size", "256x256", "--steps", "1"]
    )
    assert result.exit_code == 0, result.output
    _, data = _bench_json(tmp_path)
    assert data["skipped"][0]["engine"] == "nope"
    assert "unknown engine" in data["skipped"][0]["reason"]


def test_engine_failure_is_skipped(tmp_path, monkeypatch):
    real = run.make_backend
    monkeypatch.setattr(
        run,
        "make_backend",
        lambda name, *a, **k: FakeBackend(fail=True) if name == "sdcpp" else real(name, *a, **k),
    )
    result = runner.invoke(
        app, ["bench", "--engines", "sdcpp,fake", "--size", "256x256", "--steps", "1"]
    )
    assert result.exit_code == 0, result.output
    _, data = _bench_json(tmp_path)
    assert [r["engine"] for r in data["results"]] == ["fake"]
    assert "fake engine failed" in data["skipped"][0]["reason"]


def test_nothing_ran_exits_4(monkeypatch):
    result = runner.invoke(app, ["bench", "--engines", "nope"])
    assert result.exit_code == 4


def test_bad_runs_and_size_exit_2():
    assert runner.invoke(app, ["bench", "--engines", "fake", "--runs", "0"]).exit_code == 2
    assert runner.invoke(app, ["bench", "--engines", "fake", "--size", "7x7"]).exit_code == 2


def _write(tmp_path, name, host, total=10.0, engine="fake"):
    run_entry = {
        "load_s": 1.0,
        "per_step_s": total / 10,
        "total_s": total,
        "peak_rss_bytes": 1000,
        "image_sha256": "0" * 64,
    }
    data = {
        "schema_version": 1,
        "date": "2026-09-26",
        "host": host,
        "prompt": "p",
        "seed": 1,
        "results": [
            {
                "engine": engine,
                "engine_version": "0",
                "build_backend": "cpu",
                "weights": ["w"],
                "width": 256,
                "height": 256,
                "steps": 10,
                "runs": [run_entry],
                "median": {k: v for k, v in run_entry.items() if k != "image_sha256"},
                "image_sha256": "0" * 64,
            }
        ],
        "skipped": [],
    }
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def test_compare_refuses_different_hosts(tmp_path):
    a, b = _write(tmp_path, "a.json", "xps"), _write(tmp_path, "b.json", "m3")
    result = runner.invoke(app, ["bench", "compare", str(a), str(b)])
    assert result.exit_code == 1
    assert "different hosts" in result.output


def test_compare_same_host_prints_delta(tmp_path):
    a = _write(tmp_path, "a.json", "xps", total=10.0)
    b = _write(tmp_path, "b.json", "xps", total=5.0)
    result = runner.invoke(app, ["bench", "compare", str(a), str(b)])
    assert result.exit_code == 0, result.output
    assert "-50.0%" in result.output


def test_compare_invalid_file_exits_1(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    good = _write(tmp_path, "a.json", "xps")
    result = runner.invoke(app, ["bench", "compare", str(bad), str(good)])
    assert result.exit_code == 1


def test_render_emits_markdown_table(tmp_path):
    a = _write(tmp_path, "a.json", "xps")
    result = runner.invoke(app, ["bench", "render", str(a)])
    assert result.exit_code == 0, result.output
    assert "| engine |" in result.stdout
    assert "| fake |" in result.stdout


def test_median_and_rss_units():
    assert bench.median([3.0, 1.0, 2.0]) == 2.0
    assert bench.median([1.0, 3.0]) == 2.0
    assert bench.peak_rss_bytes(in_process=True) > 0
    assert bench.rss_to_bytes(10, "darwin") == 10
    assert bench.rss_to_bytes(10, "linux") == 10 * 1024


def test_build_backend_labels():
    assert bench.build_backend("fake", "linux") == "none"
    assert bench.build_backend("sdcpp", "darwin") == "metal"
    assert bench.build_backend("sdcpp", "linux") == "vulkan"
    assert bench.build_backend("ncnn", sys.platform) == "vulkan"
