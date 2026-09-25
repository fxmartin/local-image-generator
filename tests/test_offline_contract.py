import os
import socket

import pytest

from tests.conftest import OfflineSocketError, requires_non_root


def test_socket_creation_is_blocked_with_clear_message():
    with pytest.raises(OfflineSocketError, match="network access is forbidden"):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_connect_helpers_are_blocked():
    with pytest.raises(OfflineSocketError):
        socket.create_connection(("192.0.2.1", 80), timeout=1)


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
