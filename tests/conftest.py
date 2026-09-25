"""Shared fixtures: stub engine binaries installed under their real names on PATH."""

import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

STUBS_DIR = Path(__file__).parent / "stubs"
# Source file -> the real binary name the adapters look up on PATH.
STUB_BINARIES = {"sd_cli_stub.py": "sd-cli", "ncnn_stub.py": "qwenimage-ncnn-vulkan"}


@pytest.fixture
def stub_bin_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copy the stubs to a temp dir with real names, chmod +x, prepend to PATH."""
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    for source, name in STUB_BINARIES.items():
        target = bin_dir / name
        shutil.copyfile(STUBS_DIR / source, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir


@pytest.fixture
def stub_argv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """File the stubs append their argv to (one JSON list per invocation)."""
    path = tmp_path / "argv.jsonl"
    monkeypatch.setenv("STUB_ARGV_FILE", str(path))
    return path


@pytest.fixture
def read_stub_argv(stub_argv_file: Path) -> Callable[[], list[list[str]]]:
    import json

    def _read() -> list[list[str]]:
        return [json.loads(line) for line in stub_argv_file.read_text().splitlines()]

    return _read
