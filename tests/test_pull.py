"""`lig models pull` against an in-process loopback HTTP server; no public network."""

import hashlib
import http.server
import threading
from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from lig.cli import app as cli_app
from lig.cli.app import app
from lig.models import cache, downloader
from lig.models.registry import Artifact, Registry

runner = CliRunner()
PAYLOAD = bytes(range(256)) * 400  # ~100 KB


class _Handler(http.server.BaseHTTPRequestHandler):
    honor_range = True
    ranges: list[str | None] = []

    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:
        rng = self.headers.get("Range")
        type(self).ranges.append(rng)
        if self.path == "/missing":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body, status = PAYLOAD, 200
        if rng and type(self).honor_range:
            start = int(rng.removeprefix("bytes=").rstrip("-"))
            body, status = PAYLOAD[start:], 206
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server() -> Iterator[str]:
    _Handler.honor_range = True
    _Handler.ranges = []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def _artifact(url: str, sha: str | None = None, path: str = "/w.gguf") -> Artifact:
    return Artifact(
        name="w",
        repo="r",
        filename="w.gguf",
        sha256=sha or hashlib.sha256(PAYLOAD).hexdigest(),
        size_bytes=len(PAYLOAD),
        engines=["sdcpp"],
        role="bundle",
        license="mit",
        url=url + path,
    )


@pytest.fixture
def env(tmp_path, monkeypatch, server):
    models = tmp_path / "models"
    monkeypatch.setenv("LIG_MODELS_DIR", str(models))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    art = _artifact(server)
    registry = Registry.model_validate(
        {
            "artifacts": [art.model_dump()],
            "sets": {"s": {"engine": "sdcpp", "artifacts": ["w"]}},
        }
    )
    monkeypatch.setattr(cli_app, "load_registry", lambda: registry)
    monkeypatch.setattr(downloader, "free_bytes", lambda _p: 10**12)
    return models, art


def test_fresh_pull_verifies_and_marks(env):
    models, art = env
    result = runner.invoke(app, ["models", "pull", "w"])
    assert result.exit_code == 0, result.output
    assert (models / "w.gguf").read_bytes() == PAYLOAD
    assert not (models / "w.gguf.part").exists()
    assert cache.artifact_status(models, art) == "installed"
    assert "to download" in result.output and "free disk" in result.output


def test_pull_by_engine(env):
    models, art = env
    assert runner.invoke(app, ["models", "pull", "--engine", "sdcpp"]).exit_code == 0
    assert cache.artifact_status(models, art) == "installed"


def test_requires_name_or_engine(env):
    assert runner.invoke(app, ["models", "pull"]).exit_code == 2
    assert runner.invoke(app, ["models", "pull", "w", "--engine", "sdcpp"]).exit_code == 2


def test_unknown_name_exits_1(env):
    assert runner.invoke(app, ["models", "pull", "nope"]).exit_code == 1


def test_resume_sends_range_and_completes(env):
    models, art = env
    models.mkdir(parents=True)
    (models / "w.gguf.part").write_bytes(PAYLOAD[:1000])
    result = runner.invoke(app, ["models", "pull", "w"])
    assert result.exit_code == 0, result.output
    assert _Handler.ranges == ["bytes=1000-"]
    assert (models / "w.gguf").read_bytes() == PAYLOAD
    assert cache.artifact_status(models, art) == "installed"


def test_range_ignored_restarts_with_warning(env):
    models, art = env
    _Handler.honor_range = False
    models.mkdir(parents=True)
    (models / "w.gguf.part").write_bytes(PAYLOAD[:1000])
    result = runner.invoke(app, ["models", "pull", "w"])
    assert result.exit_code == 0, result.output
    assert "ignored the Range" in result.output
    assert (models / "w.gguf").read_bytes() == PAYLOAD
    assert cache.artifact_status(models, art) == "installed"


def test_checksum_mismatch_renames_corrupt_no_marker(env, monkeypatch):
    models, art = env
    bad = art.model_copy(update={"sha256": "a" * 64})
    registry = Registry(artifacts=[bad])
    monkeypatch.setattr(cli_app, "load_registry", lambda: registry)
    result = runner.invoke(app, ["models", "pull", "w"])
    assert result.exit_code == 1
    assert "a" * 64 in result.output
    assert hashlib.sha256(PAYLOAD).hexdigest() in result.output
    assert (models / "w.gguf.corrupt").is_file()
    assert not (models / "w.gguf").exists()
    assert not cache.marker_path(models, bad).exists()


def test_already_installed_skipped_and_force_redownloads(env):
    models, art = env
    assert runner.invoke(app, ["models", "pull", "w"]).exit_code == 0
    _Handler.ranges = []
    skipped = runner.invoke(app, ["models", "pull", "w"])
    assert "already installed" in skipped.output
    assert _Handler.ranges == []
    forced = runner.invoke(app, ["models", "pull", "w", "--force"])
    assert forced.exit_code == 0
    assert "already installed" not in forced.output
    assert len(_Handler.ranges) == 1


def test_refuses_when_disk_short_unless_force(env, monkeypatch):
    models, art = env
    monkeypatch.setattr(downloader, "free_bytes", lambda _p: len(PAYLOAD) + 1)
    refused = runner.invoke(app, ["models", "pull", "w"])
    assert refused.exit_code == 1
    assert "not enough disk" in refused.output
    assert not (models / "w.gguf").exists()
    assert runner.invoke(app, ["models", "pull", "w", "--force"]).exit_code == 0


def test_http_error_keeps_part_and_exits_1(env, server, monkeypatch):
    models, art = env
    broken = art.model_copy(update={"url": server + "/missing"})
    registry = Registry(artifacts=[broken])
    monkeypatch.setattr(cli_app, "load_registry", lambda: registry)
    result = runner.invoke(app, ["models", "pull", "w"])
    assert result.exit_code == 1
    assert "failed" in result.output
