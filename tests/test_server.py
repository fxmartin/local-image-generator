"""`lig serve` app and CLI wiring; the TestClient calls the ASGI app directly, no socket."""

import importlib.util

import pytest
from typer.testing import CliRunner

from lig import __version__
from lig.backends.fake import FAKE_VERSION, FakeBackend
from lig.cli.app import app
from lig.core import config as cfg
from lig.models.registry import load_registry

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from lig.server.app import create_app, parse_bind  # noqa: E402

runner = CliRunner()


@pytest.fixture
def client(tmp_path):
    api = create_app(FakeBackend(), load_registry(), tmp_path)
    return TestClient(api)


def test_health_reports_engine_and_versions(client):
    body = client.get("/v1/health").json()
    assert body["engine"] == "fake"
    assert body["engine_version"] == FAKE_VERSION
    assert body["loaded"] is False
    assert body["lig_version"] == __version__
    assert body["host"]
    assert body["uptime_s"] >= 0
    assert body["weights"] == {"installed": 0, "total": 0}


def test_health_counts_installed_weights(tmp_path):
    registry = load_registry()
    artifact = next(a for a in registry.artifacts if "sdcpp" in a.engines)
    (tmp_path / artifact.filename).write_bytes(b"x")
    (tmp_path / f"{artifact.filename}.sha256.ok").write_text("")
    from lig.backends.sdcpp import SdcppBackend

    backend = SdcppBackend(models_dir=tmp_path)
    backend.version = lambda: "abc123"  # the real one shells out to sd-cli
    body = TestClient(create_app(backend, registry, tmp_path)).get("/v1/health").json()
    assert body["engine_version"] == "abc123"
    assert body["weights"]["installed"] == 1
    assert body["weights"]["total"] >= 1


def test_health_survives_engine_version_failure(tmp_path):
    backend = FakeBackend()

    def boom() -> str:
        raise OSError("no binary")

    backend.version = boom
    body = TestClient(create_app(backend, load_registry(), tmp_path)).get("/v1/health").json()
    assert body["engine_version"] == "unknown"


def test_models_lists_registry_state_for_engine(tmp_path):
    registry = load_registry()
    artifact = next(a for a in registry.artifacts if "sdcpp" in a.engines)
    (tmp_path / artifact.filename).write_bytes(b"x")
    from lig.backends.sdcpp import SdcppBackend

    api = create_app(SdcppBackend(models_dir=tmp_path), registry, tmp_path)
    body = TestClient(api).get("/v1/models").json()
    status = {a["name"]: a["status"] for a in body["artifacts"]}
    assert status[artifact.name] == "unverified"
    assert all("sdcpp" in a["engines"] for a in body["artifacts"])


def test_models_empty_for_engine_without_weights(client):
    assert client.get("/v1/models").json()["artifacts"] == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [("127.0.0.1:8765", ("127.0.0.1", 8765)), ("0.0.0.0:80", ("0.0.0.0", 80))],
)
def test_parse_bind(text, expected):
    assert parse_bind(text) == expected


@pytest.mark.parametrize("text", ["8765", "host:", "host:abc", ":80", "h:70000"])
def test_parse_bind_rejects(text):
    with pytest.raises(ValueError, match="bind"):
        parse_bind(text)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("LIG_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("LIG_ENGINE", raising=False)


def test_cli_serve_runs_uvicorn_with_bind(isolated, monkeypatch):
    import uvicorn

    calls = {}
    monkeypatch.setattr(uvicorn, "run", lambda api, **kw: calls.update(api=api, **kw))
    result = runner.invoke(app, ["serve", "--engine", "fake", "--bind", "0.0.0.0:9000"])
    assert result.exit_code == 0, result.output
    assert (calls["host"], calls["port"]) == ("0.0.0.0", 9000)
    assert TestClient(calls["api"]).get("/v1/health").json()["engine"] == "fake"


def test_cli_serve_defaults_to_configured_bind(isolated, monkeypatch):
    import uvicorn

    calls = {}
    monkeypatch.setattr(uvicorn, "run", lambda api, **kw: calls.update(kw))
    assert runner.invoke(app, ["serve", "--engine", "fake"]).exit_code == 0
    host, port = parse_bind(cfg.ServeSettings().bind)
    assert (calls["host"], calls["port"]) == (host, port)


def test_cli_serve_bad_bind_exits_2(isolated):
    result = runner.invoke(app, ["serve", "--engine", "fake", "--bind", "nope"])
    assert result.exit_code == 2
    assert "bind" in result.output


def test_cli_serve_unknown_engine_exits_2(isolated):
    result = runner.invoke(app, ["serve", "--engine", "nope"])
    assert result.exit_code == 2


def test_cli_serve_refuses_planned_engine(isolated):
    assert runner.invoke(app, ["serve", "--engine", "remote"]).exit_code != 0


def test_cli_serve_without_extra_exits_2(monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name in {"fastapi", "uvicorn"} else real(name, *a),
    )
    result = runner.invoke(app, ["serve", "--engine", "fake"])
    assert result.exit_code == 2
    assert "[serve]" in result.output
