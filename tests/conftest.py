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
        "markers", "network: test may open real sockets (none in v1; the release gate is offline)"
    )


class OfflineSocketError(RuntimeError):
    """Raised when a test reaches past loopback without @pytest.mark.network."""


_FORBIDDEN = (
    "network access is forbidden in tests (CI has no network): {what}; "
    "use a loopback fixture or mark the test @pytest.mark.network"
)


def _is_loopback(host: object) -> bool:
    if not isinstance(host, str):
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _check_address(address: object) -> None:
    # AF_UNIX addresses are paths, not (host, port) tuples: always local.
    if isinstance(address, tuple) and not _is_loopback(address[0]):
        raise OfflineSocketError(_FORBIDDEN.format(what=f"connect to {address[0]!r}"))


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read the developer's lig config or LIG_* env: CI has neither, so results differ.

    Modules that need a config set XDG_CONFIG_HOME again and write one there. On macOS
    platformdirs ignores XDG_CONFIG_HOME, so this protects Linux (CI and the XPS) only.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    for key in [k for k in os.environ if k.startswith("LIG_")]:
        monkeypatch.delenv(key)


@pytest.fixture(autouse=True)
def _socket_guard(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Allow loopback (local fixture servers), refuse everything else.

    Creating and binding sockets is fine; connecting or sending to a non-loopback
    address, or resolving a non-local hostname (itself network traffic), raises.
    """
    if request.node.get_closest_marker("network"):
        return

    class GuardedSocket(socket.socket):
        # Subclass rather than a function so isinstance()/subclassing in the stdlib still work.
        def connect(self, address):  # type: ignore[override]
            _check_address(address)
            return super().connect(address)

        def connect_ex(self, address):  # type: ignore[override]
            _check_address(address)
            return super().connect_ex(address)

        def sendto(self, data, *args):  # type: ignore[override]
            _check_address(args[-1])
            return super().sendto(data, *args)

    real_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host is not None and not _is_loopback(host if isinstance(host, str) else host.decode()):
            raise OfflineSocketError(_FORBIDDEN.format(what=f"resolve {host!r}"))
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", GuardedSocket)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


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
