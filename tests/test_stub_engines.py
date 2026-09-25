"""The stub engines behave like the real binaries as far as adapters can tell."""

import subprocess
import time
from pathlib import Path

import pytest
from PIL import Image

BINARIES = ["sd-cli", "qwenimage-ncnn-vulkan"]


def run(name: str, *args: str, env: dict[str, str] | None = None):
    import os

    return subprocess.run(
        [name, *args], capture_output=True, text=True, env={**os.environ, **(env or {})}
    )


@pytest.mark.parametrize("name", BINARIES)
def test_writes_valid_png_and_echoes_argv(
    name, stub_bin_dir, stub_argv_file, read_stub_argv, tmp_path: Path
):
    out = tmp_path / "out.png"
    argv = ["-p", "a cat", "--steps", "4", "-o", str(out)]
    result = run(name, *argv)
    assert result.returncode == 0
    with Image.open(out) as img:
        assert img.format == "PNG"
    assert read_stub_argv() == [argv]
    assert result.stdout.strip() != ""  # fake progress lines


@pytest.mark.parametrize("name", BINARIES)
def test_argv_file_accumulates_invocations(
    name, stub_bin_dir, stub_argv_file, read_stub_argv, tmp_path: Path
):
    run(name, "-o", str(tmp_path / "a.png"))
    run(name, "-o", str(tmp_path / "b.png"))
    assert len(read_stub_argv()) == 2


@pytest.mark.parametrize("name", BINARIES)
def test_stub_fail_exits_2_with_stderr(name, stub_bin_dir, tmp_path: Path):
    out = tmp_path / "out.png"
    result = run(name, "-o", str(out), env={"STUB_FAIL": "1"})
    assert result.returncode == 2
    assert result.stderr.strip() != ""
    assert not out.exists()


@pytest.mark.parametrize("name", BINARIES)
def test_stub_sleep_delays(name, stub_bin_dir, tmp_path: Path):
    start = time.monotonic()
    result = run(name, "-o", str(tmp_path / "o.png"), env={"STUB_SLEEP": "0.5"})
    assert result.returncode == 0
    assert time.monotonic() - start >= 0.5


@pytest.mark.parametrize("name", BINARIES)
def test_missing_output_path_is_an_error(name, stub_bin_dir):
    assert run(name, "-p", "x").returncode != 0


@pytest.mark.parametrize("name", BINARIES)
def test_stub_shebang_needs_only_python3(name, stub_bin_dir):
    first = (stub_bin_dir / name).read_text().splitlines()[0]
    assert first == "#!/usr/bin/env python3"
