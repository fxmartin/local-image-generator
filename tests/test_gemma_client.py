"""Story 09.1-001: the gemma client against the stub `gemma` (no network, no SSH)."""

import json
import shutil
import stat
from pathlib import Path

import pytest

from lig.series.gemma import GemmaClient, GemmaError, GemmaNotFound

STUB = Path(__file__).parent / "stubs" / "gemma_stub.py"


@pytest.fixture
def stdin_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "stdin.txt"
    monkeypatch.setenv("STUB_STDIN_FILE", str(path))
    return path


def test_runs_gemma_with_flags_and_stdin_and_strips_output(
    stub_bin_dir, stub_argv_file, read_stub_argv, stdin_file, monkeypatch
):
    monkeypatch.setenv("STUB_GEMMA_REPLY", "the answer")
    out = GemmaClient().complete("SYS", "my request", temperature=0.7, max_tokens=512)
    assert out == "the answer"
    assert read_stub_argv() == [
        ["--system", "SYS", "--temperature", "0.7", "--max-tokens", "512", "-"]
    ]
    assert stdin_file.read_text() == "my request"


def test_gemma_flag_overrides_path(stub_bin_dir, stub_argv_file, read_stub_argv, tmp_path):
    custom = tmp_path / "my-gemma"
    shutil.copyfile(STUB, custom)
    custom.chmod(custom.stat().st_mode | stat.S_IXUSR)
    (stub_bin_dir / "gemma").unlink()  # PATH has no gemma; only the override works
    GemmaClient(binary=str(custom)).complete("s", "r", temperature=0.1, max_tokens=1)
    assert len(read_stub_argv()) == 1


def test_env_overrides_path(stub_bin_dir, stub_argv_file, read_stub_argv, tmp_path, monkeypatch):
    custom = tmp_path / "env-gemma"
    shutil.copyfile(STUB, custom)
    custom.chmod(custom.stat().st_mode | stat.S_IXUSR)
    (stub_bin_dir / "gemma").unlink()
    monkeypatch.setenv("LIG_SERIES_GEMMA", str(custom))
    GemmaClient().complete("s", "r", temperature=0.1, max_tokens=1)
    assert len(read_stub_argv()) == 1


def test_flag_beats_env(stub_bin_dir, monkeypatch):
    monkeypatch.setenv("LIG_SERIES_GEMMA", "/nonexistent/gemma")
    assert GemmaClient(binary=str(stub_bin_dir / "gemma")).resolve().endswith("gemma")


def test_missing_gemma_exits_4(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("LIG_SERIES_GEMMA", raising=False)
    with pytest.raises(GemmaNotFound) as info:
        GemmaClient().complete("s", "r", temperature=0.1, max_tokens=1)
    assert info.value.exit_code == 4
    assert str(info.value) == "gemma not found; install m3max-gemma or set --gemma"


def test_nonzero_exit_reports_last_20_stderr_lines(stub_bin_dir, monkeypatch):
    monkeypatch.setenv("STUB_FAIL", "1")
    with pytest.raises(GemmaError) as info:
        GemmaClient().complete("s", "r", temperature=0.1, max_tokens=1)
    assert info.value.exit_code == 1
    message = str(info.value)
    assert "stub failure line 29" in message
    assert "stub failure line 10" in message
    assert "stub failure line 9\n" not in message + "\n"


def test_timeout_exits_1(stub_bin_dir, monkeypatch):
    monkeypatch.setenv("STUB_SLEEP", "5")
    with pytest.raises(GemmaError) as info:
        GemmaClient(timeout=0.5).complete("s", "r", temperature=0.1, max_tokens=1)
    assert info.value.exit_code == 1
    assert "timed out" in str(info.value)


def test_stub_records_argv_as_json(stub_bin_dir, stub_argv_file):
    GemmaClient().complete("s", "r", temperature=0.2, max_tokens=3)
    assert json.loads(stub_argv_file.read_text().splitlines()[0])[0] == "--system"


def test_os_error_launching_is_a_gemma_error(stub_bin_dir, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("exec format error")

    monkeypatch.setattr("lig.series.gemma.subprocess.run", boom)
    with pytest.raises(GemmaError, match="could not run gemma: exec format error"):
        GemmaClient().complete("s", "r", temperature=0.1, max_tokens=1)
