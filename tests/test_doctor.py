import json

from typer.testing import CliRunner

import lig.cli.app as cli_app
from lig.backends.base import Availability
from lig.core import doctor
from lig.core.doctor import PlatformInfo

runner = CliRunner()

GIB = 1024**3


def xps_info(models_dir="/m") -> PlatformInfo:
    return PlatformInfo(
        os="Linux",
        arch="x86_64",
        vulkan_icd=True,
        metal=False,
        oneapi=False,
        ram_total=30 * GIB,
        ram_available=20 * GIB,
        models_dir=models_dir,
        disk_free=100 * GIB,
    )


class _Engine:
    def __init__(self, name, ok, reason=""):
        self.name = name
        self._a = Availability(ok=ok, reason=reason)

    def available(self):
        return self._a


def _factories(*engines):
    return {e.name: (lambda e=e: e) for e in engines}


def test_probe_vulkan_via_vulkaninfo():
    assert doctor.probe_vulkan(which=lambda n: "/usr/bin/vulkaninfo", run=lambda argv: True)


def test_probe_vulkan_falls_back_to_icd_files(tmp_path):
    (tmp_path / "intel_icd.json").write_text("{}")
    assert doctor.probe_vulkan(which=lambda n: None, run=lambda a: False, icd_dirs=[tmp_path])
    assert not doctor.probe_vulkan(
        which=lambda n: None, run=lambda a: False, icd_dirs=[tmp_path / "none"]
    )


def test_probe_vulkan_empty_summary_uses_icd_files(tmp_path):
    (tmp_path / "x.json").write_text("{}")
    assert doctor.probe_vulkan(which=lambda n: "/x", run=lambda a: False, icd_dirs=[tmp_path])


def test_probe_oneapi(tmp_path):
    assert doctor.probe_oneapi(which=lambda n: "/x/sycl-ls", oneapi_dir=tmp_path / "no")
    assert doctor.probe_oneapi(which=lambda n: None, oneapi_dir=tmp_path)
    assert not doctor.probe_oneapi(which=lambda n: None, oneapi_dir=tmp_path / "no")


def test_meminfo_parse():
    total, avail = doctor.parse_meminfo("MemTotal: 1000 kB\nMemAvailable: 400 kB\n")
    assert (total, avail) == (1000 * 1024, 400 * 1024)
    assert doctor.parse_meminfo("garbage") == (None, None)


def test_collect_uses_injected_probes(tmp_path):
    info = doctor.collect_platform_info(
        tmp_path,
        system=lambda: "Darwin",
        machine=lambda: "arm64",
        vulkan=lambda: False,
        oneapi=lambda: False,
        memory=lambda: (8 * GIB, 4 * GIB),
        disk_free=lambda p: 5 * GIB,
    )
    assert info.metal and info.os == "Darwin" and info.arch == "arm64"
    assert info.ram_total == 8 * GIB and info.disk_free == 5 * GIB


def test_disk_free_walks_to_existing_parent(tmp_path):
    assert doctor.disk_free_bytes(tmp_path / "a" / "b") > 0


def test_report_rows_and_cached_weights(tmp_path):
    (tmp_path / "sdcpp").mkdir()
    (tmp_path / "sdcpp" / "w.gguf").write_bytes(b"12345")
    engines = _factories(
        _Engine("sdcpp", False, "sd-cli not found on PATH (set engines.sdcpp.binary)"),
        _Engine("fake", True),
    )
    report = doctor.build_report(xps_info(str(tmp_path)), engines)
    rows = {r["engine"]: r for r in report["engines"]}
    assert rows["sdcpp"]["status"] == "unavailable"
    assert rows["sdcpp"]["reason"].startswith("sd-cli not found on PATH")
    assert rows["sdcpp"]["cached_files"] == 1 and rows["sdcpp"]["cached_bytes"] == 5
    assert rows["fake"]["status"] == "available"
    assert report["platform"]["vulkan_icd"] is True


def test_report_engine_constructor_failure_is_unavailable():
    def boom():
        raise RuntimeError("bad")

    report = doctor.build_report(xps_info(), {"x": boom})
    assert report["engines"][0]["status"] == "unavailable"
    assert "bad" in report["engines"][0]["reason"]


def _patch(monkeypatch):
    monkeypatch.setattr(cli_app, "_platform_info", lambda models_dir: xps_info(str(models_dir)))
    monkeypatch.setattr(
        cli_app,
        "_engine_factories",
        lambda settings: _factories(
            _Engine("sdcpp", False, "sd-cli not found on PATH (set engines.sdcpp.binary)")
        ),
    )


def test_cli_table(monkeypatch, tmp_path):
    _patch(monkeypatch)
    monkeypatch.setenv("LIG_MODELS_DIR", str(tmp_path))
    result = runner.invoke(cli_app.app, ["doctor"])
    assert result.exit_code == 0
    out = " ".join(result.output.split())
    assert "unavailable: sd-cli not found on PATH (set engines.sdcpp.binary)" in out
    assert "x86_64" in out and "Vulkan" in out


def test_cli_json(monkeypatch, tmp_path):
    _patch(monkeypatch)
    monkeypatch.setenv("LIG_MODELS_DIR", str(tmp_path))
    result = runner.invoke(cli_app.app, ["doctor", "--json"])
    data = json.loads(result.output)
    assert data["platform"]["arch"] == "x86_64"
    assert data["engines"][0]["engine"] == "sdcpp"


def test_run_ok_maps_exit_code_and_errors(monkeypatch):
    class Done:
        returncode = 0

    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: Done())
    assert doctor._run_ok(["x"]) is True
    Done.returncode = 1
    assert doctor._run_ok(["x"]) is False

    def boom(*a, **k):
        raise OSError("nope")

    monkeypatch.setattr(doctor.subprocess, "run", boom)
    assert doctor._run_ok(["x"]) is False


def test_probe_memory_reads_proc_meminfo(monkeypatch):
    monkeypatch.setattr(
        doctor.Path, "read_text", lambda self: "MemTotal: 2 kB\nMemAvailable: 1 kB\n"
    )
    assert doctor.probe_memory() == (2048, 1024)


def test_probe_memory_sysconf_fallback_and_unknown(monkeypatch):
    def no_proc(self):
        raise OSError

    monkeypatch.setattr(doctor.Path, "read_text", no_proc)
    monkeypatch.setattr(doctor.os, "sysconf", lambda name: 4096)
    assert doctor.probe_memory() == (4096 * 4096, None)

    def bad(name):
        raise ValueError(name)

    monkeypatch.setattr(doctor.os, "sysconf", bad)
    assert doctor.probe_memory() == (None, None)


def test_disk_free_oserror_is_none(monkeypatch, tmp_path):
    def boom(path):
        raise OSError

    monkeypatch.setattr(doctor.shutil, "disk_usage", boom)
    assert doctor.disk_free_bytes(tmp_path) is None


def test_cli_default_seams_and_config_error(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(
        cli_app.diag,
        "collect_platform_info",
        lambda models_dir: seen.setdefault("info", xps_info(str(models_dir))),
    )
    assert cli_app._platform_info(tmp_path) is seen["info"]
    factories = cli_app._engine_factories(cli_app.cfg.load_settings().settings)
    assert set(factories) == set(cli_app.BACKENDS)
    for name, factory in factories.items():
        assert factory().name == name  # every engine constructs from real settings

    def bad(*a, **k):
        raise cli_app.cfg.ConfigError("broken config")

    monkeypatch.setattr(cli_app.cfg, "load_settings", bad)
    result = runner.invoke(cli_app.app, ["doctor"])
    assert result.exit_code == 1
