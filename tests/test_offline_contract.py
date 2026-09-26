import os
import socket
import sys

import pytest

from tests.conftest import OfflineSocketError, requires_non_root


def test_connecting_to_a_non_loopback_address_is_blocked_with_clear_message():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(OfflineSocketError, match="network access is forbidden"):
            sock.connect(("192.0.2.1", 80))


def test_connect_helpers_are_blocked():
    with pytest.raises(OfflineSocketError):
        socket.create_connection(("192.0.2.1", 80), timeout=1)


def test_connect_ex_to_a_non_loopback_address_is_blocked():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(OfflineSocketError):
            sock.connect_ex(("192.0.2.1", 80))


def test_udp_sendto_a_non_loopback_address_is_blocked():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        with pytest.raises(OfflineSocketError):
            sock.sendto(b"x", ("192.0.2.1", 53))


def test_resolving_a_non_local_hostname_is_blocked():
    # A DNS lookup is itself network traffic, so it fails before any connect.
    with pytest.raises(OfflineSocketError):
        socket.getaddrinfo("example.com", 443)


def test_loopback_connections_are_allowed():
    # Local fixtures (e.g. the fake HTTP server in test_pull.py) bind and connect on loopback.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(("127.0.0.1", server.getsockname()[1]), timeout=5) as client:
            assert client.getpeername()[0] == "127.0.0.1"


def test_localhost_resolves_to_loopback():
    infos = socket.getaddrinfo("localhost", 80, type=socket.SOCK_STREAM)
    assert infos


@pytest.mark.network
def test_network_marker_opts_out_of_guard():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        assert sock.family == socket.AF_INET


@requires_non_root
def test_permission_based_failure_needs_non_root(tmp_path):
    target = tmp_path / "ro.txt"
    target.write_text("x")
    target.chmod(0o444)
    with pytest.raises(PermissionError):
        target.open("w")


def test_non_root_marker_skips_with_explicit_reason_as_root():
    reason = requires_non_root.kwargs["reason"]
    assert "euid == 0" in reason
    assert requires_non_root.args[0] == (hasattr(os, "geteuid") and os.geteuid() == 0)


def test_tests_never_read_the_developers_lig_config(tmp_path_factory):
    # A real ~/.config/lig/config.toml (e.g. default_host = "m3max") made doctor tests
    # reach for the network on a developer machine while CI stayed green.
    from pathlib import Path

    from lig.core import config as cfg

    base = tmp_path_factory.getbasetemp()
    assert Path(os.environ["XDG_CONFIG_HOME"]).is_relative_to(base)
    if sys.platform.startswith("linux"):  # platformdirs ignores XDG_CONFIG_HOME on macOS
        assert cfg.default_config_path().is_relative_to(base)
    assert not [k for k in os.environ if k.startswith("LIG_")]
