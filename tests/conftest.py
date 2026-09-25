"""Shared fixtures: the CI contract (offline, honest about root) and stub engine binaries."""

import ipaddress
import os
import shutil
import socket
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

STUBS_DIR = Path(__file__).parent / "stubs"
# Source file -> the real binary name the adapters look up on PATH.
STUB_BINARIES = {"sd_cli_stub.py": "sd-cli", "ncnn_stub.py": "qwenimage-ncnn-vulkan"}

requires_non_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="euid == 0: permission-based fault injection is a no-op as root (CI runs as root)",
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "network: test may reach non-loopback addresses (none in v1; the release gate is offline)",
    )


class OfflineSocketError(RuntimeError):
    """Raised when a test reaches a non-loopback address without @pytest.mark.network."""


def _is_loopback(address: object) -> bool:
    # AF_UNIX paths and loopback hosts never leave the job container, so they work offline.
    if not isinstance(address, tuple):
        return True
    host = address[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _socket_guard(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("network"):
        return

    class GuardedSocket(socket.socket):
        # Subclass rather than a function so isinstance()/subclassing in the stdlib still work.
        def _check(self, address: object) -> None:
            if not _is_loopback(address):
                raise OfflineSocketError(
                    f"network access to {address!r} is forbidden in tests (CI has no network); "
                    "use a fake/loopback fixture or mark the test @pytest.mark.network"
                )

        def connect(self, address):
            self._check(address)
            return super().connect(address)

        def connect_ex(self, address):
            self._check(address)
            return super().connect_ex(address)

        def bind(self, address):
            self._check(address)
            return super().bind(address)

        def sendto(self, data, *args):
            self._check(args[-1])
            return super().sendto(data, *args)

    monkeypatch.setattr(socket, "socket", GuardedSocket)


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
