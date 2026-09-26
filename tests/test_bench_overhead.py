"""`lig bench --host` records client/server hosts; `lig bench overhead` checks the 10 s target."""

import json

import pytest
from typer.testing import CliRunner

from lig.backends.fake import FakeBackend
from lig.cli.app import app
from lig.core import bench, run

runner = CliRunner()


class FakeRemote(FakeBackend):
    """A FakeBackend that answers like RemoteBackend: server host + configured name stamped."""

    name = "remote"

    def generate(self, request, on_progress):
        result = super().generate(request, on_progress)
        return result.model_copy(update={"host": "macbook-pro-m3-max", "remote_host": "m3max"})


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    for key in ("LIG_ENGINE", "LIG_SIZE", "LIG_STEPS", "LIG_OUTPUT_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


def test_bench_host_records_client_and_server_host(tmp_path, monkeypatch):
    seen = {}

    def make(name, settings, *, verbose=False, host=None):
        seen.update(name=name, host=host)
        return FakeRemote()

    monkeypatch.setattr(run, "make_backend", make)
    result = runner.invoke(app, ["bench", "--host", "m3max", "--size", "256x256", "--steps", "1"])
    assert result.exit_code == 0, result.output
    assert seen == {"name": "remote", "host": "m3max"}
    (path,) = (tmp_path / "bench").glob("*.json")
    report = bench.BenchReport.model_validate_json(path.read_text())
    assert report.server_host == "macbook-pro-m3-max"
    assert report.client_host == report.host
    assert report.results[0].median_wall_s is not None


def test_local_bench_has_no_server_host(tmp_path):
    runner.invoke(app, ["bench", "--engines", "fake", "--size", "256x256", "--steps", "1"])
    (path,) = (tmp_path / "bench").glob("*.json")
    report = bench.BenchReport.model_validate_json(path.read_text())
    assert report.server_host is None and report.client_host is None


def test_host_conflicts_with_other_engines():
    result = runner.invoke(app, ["bench", "--host", "m3max", "--engines", "sdcpp"])
    assert result.exit_code == 2


def _report(tmp_path, name, total, wall=None, server=None, steps=10):
    run_entry = {
        "load_s": 1.0,
        "per_step_s": 1.0,
        "total_s": total,
        "peak_rss_bytes": 1,
        "image_sha256": "0" * 64,
        "wall_s": wall,
    }
    data = {
        "date": "2026-09-26",
        "host": "xps" if server else "m3",
        "client_host": "xps" if server else None,
        "server_host": server,
        "prompt": "p",
        "seed": 1,
        "results": [
            {
                "engine": "remote" if server else "sdcpp",
                "engine_version": "0",
                "build_backend": "metal",
                "weights": ["w"],
                "width": 256,
                "height": 256,
                "steps": steps,
                "runs": [run_entry],
                "median": {
                    k: v for k, v in run_entry.items() if k not in ("image_sha256", "wall_s")
                },
                "median_wall_s": wall,
                "image_sha256": "0" * 64,
            }
        ],
        "skipped": [],
    }
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def test_overhead_passes_within_limit(tmp_path):
    local = _report(tmp_path, "l.json", 100.0)
    remote = _report(tmp_path, "r.json", 100.0, wall=103.5, server="m3")
    result = runner.invoke(app, ["bench", "overhead", str(local), str(remote)])
    assert result.exit_code == 0, result.output
    assert "+3.50 s" in result.output and "PASS" in result.output
    assert "xps -> m3" in result.output


def test_overhead_fails_above_limit_and_says_to_open_issue(tmp_path):
    local = _report(tmp_path, "l.json", 100.0)
    remote = _report(tmp_path, "r.json", 100.0, wall=115.0, server="m3")
    result = runner.invoke(app, ["bench", "overhead", str(local), str(remote)])
    assert result.exit_code == 1
    assert "FAIL" in result.output and "open an issue" in result.output


def test_overhead_falls_back_to_server_total_without_wall(tmp_path):
    local = _report(tmp_path, "l.json", 100.0)
    remote = _report(tmp_path, "r.json", 101.0, server="m3")
    outcome = bench.compute_overhead(bench.load_report(local), bench.load_report(remote), 10)
    assert outcome.overhead_s == pytest.approx(1.0)


def test_overhead_rejects_local_file_as_remote(tmp_path):
    local = _report(tmp_path, "l.json", 100.0)
    result = runner.invoke(app, ["bench", "overhead", str(local), str(local)])
    assert result.exit_code == 1
    assert "server_host" in result.output


def test_overhead_rejects_mismatched_job(tmp_path):
    local = _report(tmp_path, "l.json", 100.0)
    remote = _report(tmp_path, "r.json", 100.0, wall=101.0, server="m3", steps=20)
    result = runner.invoke(app, ["bench", "overhead", str(local), str(remote)])
    assert result.exit_code == 1
    assert "different" in result.output
