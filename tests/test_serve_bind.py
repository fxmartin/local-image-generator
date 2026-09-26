"""Tailnet-only bind default for `lig serve`; the Tailscale probe is always a fake."""

import subprocess

import pytest
from typer.testing import CliRunner

from lig.cli.app import app
from lig.server import bind as bindmod
from lig.server.bind import BindRefused, resolve_bind

runner = CliRunner()


def test_tailscale_up_binds_tailnet_ip_on_7860():
    d = resolve_bind(None, None, probe=lambda: "100.101.102.103")
    assert (d.host, d.port) == ("100.101.102.103", 7860)
    assert "http://100.101.102.103:7860" in d.notice


def test_tailscale_absent_binds_loopback_and_explains():
    d = resolve_bind(None, None, probe=lambda: None)
    assert (d.host, d.port) == ("127.0.0.1", 7860)
    assert "--bind" in d.notice


def test_configured_bind_beats_probe_and_explicit_beats_configured():
    assert resolve_bind(None, ("10.0.0.1", 1), probe=lambda: "100.64.0.1").host == "10.0.0.1"
    assert resolve_bind(("10.0.0.2", 2), ("10.0.0.1", 1), probe=lambda: None).host == "10.0.0.2"


def test_wildcard_without_tailscale_is_refused_without_i_know():
    with pytest.raises(BindRefused, match="no auth|NO authentication"):
        resolve_bind(("0.0.0.0", 7860), None, probe=lambda: None)


def test_wildcard_without_tailscale_proceeds_with_i_know_and_warns():
    d = resolve_bind(("0.0.0.0", 7860), None, probe=lambda: None, i_know=True)
    assert d.host == "0.0.0.0" and "NO authentication" in d.warning


def test_wildcard_with_tailscale_present_is_allowed():
    d = resolve_bind(("0.0.0.0", 7860), None, probe=lambda: "100.64.0.1")
    assert d.host == "0.0.0.0" and d.warning is None


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("100.64.0.1", True),
        ("100.127.255.254", True),
        ("100.128.0.1", False),
        ("10.0.0.1", False),
        ("x", False),
    ],
)
def test_is_tailnet_ip(text, ok):
    assert bindmod._is_tailnet_ip(text) is ok


def test_cli_probe_reads_tailscale_ip_output(monkeypatch):
    monkeypatch.setattr(bindmod.shutil, "which", lambda name: "/usr/bin/tailscale")
    monkeypatch.setattr(
        bindmod.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="100.90.80.70\n", stderr=""),
    )
    assert bindmod._from_cli() == "100.90.80.70"


def test_cli_probe_absent_binary_or_failure_is_none(monkeypatch):
    monkeypatch.setattr(bindmod.shutil, "which", lambda name: None)
    assert bindmod._from_cli() is None
    monkeypatch.setattr(bindmod.shutil, "which", lambda name: "/usr/bin/tailscale")

    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, "tailscale")

    monkeypatch.setattr(bindmod.subprocess, "run", boom)
    assert bindmod._from_cli() is None


def test_interface_probe_finds_tailscale_iface(monkeypatch):
    psutil = pytest.importorskip("psutil")
    from types import SimpleNamespace as NS

    monkeypatch.setattr(
        psutil,
        "net_if_addrs",
        lambda: {"eth0": [NS(address="192.168.1.2")], "tailscale0": [NS(address="100.70.1.2")]},
    )
    assert bindmod._from_interfaces() == "100.70.1.2"


@pytest.fixture
def env(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")
    monkeypatch.setenv("LIG_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("LIG_ENGINE", raising=False)
    import uvicorn

    calls = {}
    monkeypatch.setattr(uvicorn, "run", lambda api, **kw: calls.update(kw))
    return calls


def test_cli_default_bind_uses_probe(env, monkeypatch):
    monkeypatch.setattr(bindmod, "probe_tailscale_ip", lambda: "100.64.9.9")
    result = runner.invoke(app, ["serve", "--engine", "fake"])
    assert result.exit_code == 0, result.output
    assert (env["host"], env["port"]) == ("100.64.9.9", 7860)
    assert "http://100.64.9.9:7860" in result.output


def test_cli_wildcard_refused_then_allowed(env, monkeypatch):
    monkeypatch.setattr(bindmod, "probe_tailscale_ip", lambda: None)
    refused = runner.invoke(app, ["serve", "--engine", "fake", "--bind", "0.0.0.0:7860"])
    assert refused.exit_code == 2 and "--i-know" in refused.output and not env
    ok = runner.invoke(app, ["serve", "--engine", "fake", "--bind", "0.0.0.0:7860", "--i-know"])
    assert ok.exit_code == 0 and env["host"] == "0.0.0.0"
    assert "NO authentication" in ok.output
