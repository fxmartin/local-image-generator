"""RemoteBackend and `--host`: httpx.MockTransport plays `lig serve`; no sockets."""

import base64
import json

import httpx
import pytest
from PIL import Image
from typer.testing import CliRunner

from lig.backends import remote
from lig.backends.base import EngineError, EngineUnavailable
from lig.backends.fake import FakeBackend
from lig.backends.remote import RemoteBackend
from lig.cli.app import app
from lig.core import config as cfg
from lig.core import doctor
from lig.core.models import EditRequest, GenerateRequest

runner = CliRunner()
URL = "http://100.1.2.3:7860"
CAPS = {"supports_edit": True, "supports_transparent": True, "platforms": ["darwin"]}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    for key in ("LIG_ENGINE", "LIG_SIZE", "LIG_STEPS", "LIG_OUTPUT_DIR", "LIG_DEFAULT_HOST"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


def write_config(tmp_path, text):
    path = tmp_path / "cfg" / "lig" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(text)


class Server:
    """A fake daemon: the real ASGI app would need sockets, so replay its wire format."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.backend = FakeBackend()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/v1/health":
            return httpx.Response(
                200, json={"engine": "sdcpp", "capabilities": CAPS, "host": "mac", "build": "metal"}
            )
        if path == "/v1/generate":
            req = GenerateRequest(**json.loads(request.content))
            return self._stream(req)
        if path == "/v1/edit":
            return self._edit(request)
        return httpx.Response(404)

    def _meta(self, result):
        return {
            "engine": "sdcpp",
            "engine_version": "9",
            "weights": [w.model_dump() for w in result.weights],
            "timings": result.timings.model_dump(),
            "host": "mac",
            "remote_host": "mac",
        }

    def _stream(self, req):
        result = self.backend.generate(req, None)
        body = "".join(
            f'event: progress\ndata: {{"step": {i}, "total": {req.steps}, "elapsed": 0.1}}\n\n'
            for i in range(1, req.steps + 1)
        )
        payload = {"metadata": self._meta(result), "png_b64": base64.b64encode(result.png).decode()}
        body += f"event: result\ndata: {json.dumps(payload)}\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    def _edit(self, request):
        assert request.headers["content-type"].startswith("multipart/form-data")
        assert b'name="image"; filename="teapot.png"' in request.content
        assert b'name="prompt"' in request.content
        req = GenerateRequest(prompt="x", width=256, height=256, steps=2, seed=1)
        result = self.backend.generate(req, None)
        return httpx.Response(
            200,
            json={
                "metadata": self._meta(result),
                "png_base64": base64.b64encode(result.png).decode(),
            },
        )


@pytest.fixture
def server(monkeypatch):
    srv = Server()
    monkeypatch.setattr(
        remote, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(srv.handler))
    )
    monkeypatch.setattr(remote.time, "sleep", lambda s: None)
    return srv


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "teapot.png"
    Image.new("RGB", (256, 256), "red").save(path)
    return path


def backend(server) -> RemoteBackend:
    return RemoteBackend("m3max", URL)


def test_generate_relays_progress_and_stamps_remote_host(server):
    steps = []
    request = GenerateRequest(prompt="a cat", width=256, height=256, steps=3, seed=5)
    result = backend(server).generate(request, lambda s, t: steps.append((s, t)))
    assert steps == [(1, 3), (2, 3), (3, 3)]
    assert result.remote_host == "m3max"
    assert (result.engine, result.engine_version, result.host) == ("sdcpp", "9", "mac")
    assert result.request.seed == 5 and result.png.startswith(b"\x89PNG")


def test_capabilities_come_from_health_and_are_cached(server):
    remote_backend = backend(server)
    assert remote_backend.capabilities().platforms == ["darwin"]
    remote_backend.capabilities()
    remote_backend.available()
    assert [r.url.path for r in server.requests] == ["/v1/health"]


def test_build_comes_from_server_health(server):
    assert backend(server).build == "metal"


def test_build_is_unknown_for_old_server():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"engine": "x"}))
    remote_backend = RemoteBackend("h", URL, client=httpx.Client(transport=transport))
    assert remote_backend.build == "unknown"


def test_capabilities_fallback_for_old_server(monkeypatch):
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"engine": "x"}))
    remote_backend = RemoteBackend("h", URL, client=httpx.Client(transport=transport))
    assert remote_backend.capabilities().supports_edit


def test_edit_uploads_reference(server, source):
    request = EditRequest(
        prompt="blue",
        width=256,
        height=256,
        steps=2,
        reference_image=source,
        reference_sha256="a" * 64,
        strength=0.5,
    )
    result = backend(server).edit(request, None)
    body = server.requests[-1].content
    assert b'name="strength"' in body and b'name="reference_sha256"' not in body
    assert result.request.reference_image == source


def test_unreachable_retries_once_then_names_url(monkeypatch):
    calls = []

    def refuse(request):
        calls.append(request)
        raise httpx.ConnectError("refused", request=request)

    sleeps = []
    remote_backend = RemoteBackend(
        "m3max",
        URL,
        client=httpx.Client(transport=httpx.MockTransport(refuse)),
        sleep=sleeps.append,
    )
    availability = remote_backend.available()
    assert not availability.ok and URL in availability.reason and "refused" in availability.reason
    assert len(calls) == 2 and len(sleeps) == 1
    with pytest.raises(EngineUnavailable, match="refused"):
        remote_backend.generate(GenerateRequest(prompt="x", steps=1), None)
    assert len(calls) == 4


def test_non_health_http_error_is_not_retried():
    calls = []
    transport = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(503))
    remote_backend = RemoteBackend("h", URL, client=httpx.Client(transport=transport))
    assert not remote_backend.available().ok
    assert len(calls) == 1


def test_sse_error_event_becomes_engine_error():
    body = 'event: error\ndata: {"message": "boom", "log_tail": ["l1", "l2"]}\n\n'
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)
    )
    remote_backend = RemoteBackend("h", URL, client=httpx.Client(transport=transport))
    with pytest.raises(EngineError, match="boom") as info:
        remote_backend.generate(GenerateRequest(prompt="x", steps=1), None)
    assert "l2" in info.value.stderr


def test_truncated_stream_and_http_500_and_422():
    def serve(status, **kw):
        transport = httpx.MockTransport(lambda r: httpx.Response(status, **kw))
        return RemoteBackend("h", URL, client=httpx.Client(transport=transport))

    request = GenerateRequest(prompt="x", steps=1)
    with pytest.raises(EngineError, match="before sending a result"):
        serve(200, headers={"content-type": "text/event-stream"}, text="").generate(request, None)
    with pytest.raises(EngineError, match="engine died"):
        serve(500, json={"error": "engine died", "log_tail": ["x"]}).generate(request, None)
    with pytest.raises(EngineError, match="HTTP 422"):
        serve(422, json={"detail": "bad"}).generate(request, None)


def test_plain_json_response_is_accepted():
    fake = FakeBackend().generate(GenerateRequest(prompt="x", width=256, height=256, steps=1), None)
    payload = {
        "metadata": {
            "engine": "e",
            "engine_version": "1",
            "weights": [],
            "timings": fake.timings.model_dump(),
            "host": "h",
        },
        "png_base64": base64.b64encode(fake.png).decode(),
    }
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    result = RemoteBackend("h", URL, client=httpx.Client(transport=transport)).generate(
        GenerateRequest(prompt="x", steps=1), None
    )
    assert result.engine == "e"


def test_unreadable_reference_is_engine_error(tmp_path):
    request = EditRequest(
        prompt="x", reference_image=tmp_path / "gone.png", reference_sha256="a" * 64
    )
    with pytest.raises(EngineError, match="cannot read"):
        RemoteBackend("h", URL).edit(request, None)


def test_server_health_reports_capabilities(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from lig.models.registry import load_registry
    from lig.server.app import create_app

    body = TestClient(create_app(FakeBackend(), load_registry(), tmp_path)).get("/v1/health").json()
    assert body["capabilities"]["supports_edit"] is True
    assert body["build"] == "none"  # the server reports its own build (fake has none)


# --- config and host resolution ---


def test_hosts_table_loads_without_unknown_key_warnings(tmp_path):
    write_config(tmp_path, f'[hosts]\nm3max = "{URL}"\n')
    resolved = cfg.load_settings()
    assert resolved.settings.hosts == {"m3max": URL}
    assert resolved.warnings == []


def test_host_must_be_http_url(tmp_path):
    write_config(tmp_path, '[hosts]\nm3max = "ssh://x"\n')
    with pytest.raises(cfg.ConfigError, match="http"):
        cfg.load_settings()


# --- CLI ---


def test_generate_host_writes_local_outputs_with_remote_host(tmp_path, server):
    write_config(tmp_path, f'[hosts]\nm3max = "{URL}"\n')
    result = runner.invoke(
        app, ["generate", "a cat", "--host", "m3max", "--size", "256x256", "--steps", "2"]
    )
    assert result.exit_code == 0, result.output
    png = next((tmp_path / "outputs").glob("*.png"))
    sidecar = json.loads(png.with_suffix(".json").read_text())
    assert sidecar["remote_host"] == "m3max"
    assert sidecar["engine"] == "sdcpp" and sidecar["engine_version"] == "9"
    assert any(str(r.url).startswith(URL) for r in server.requests)
    assert "step 2/2" in result.output or "generating" in result.output


def test_generate_default_host_is_used(tmp_path, server):
    write_config(tmp_path, f'default_host = "m3max"\n[hosts]\nm3max = "{URL}"\n')
    result = runner.invoke(app, ["generate", "a cat", "--size", "256x256", "--steps", "1"])
    assert result.exit_code == 0, result.output
    assert next((tmp_path / "outputs").glob("*.json")).read_text().count('"remote_host": "m3max"')


def test_remote_ignores_linux_local_fallback(tmp_path, server):
    write_config(tmp_path, f'[hosts]\nm3max = "{URL}"\n')
    result = runner.invoke(app, ["generate", "a cat", "--host", "m3max", "--steps", "1"])
    assert result.exit_code == 0, result.output
    generated = next(r for r in server.requests if r.url.path == "/v1/generate")
    assert json.loads(generated.content)["width"] == 1024


def test_edit_host_sidecar_source_is_local(tmp_path, server, source):
    write_config(tmp_path, f'[hosts]\nm3max = "{URL}"\n')
    result = runner.invoke(app, ["edit", str(source), "blue", "--host", "m3max", "--steps", "2"])
    assert result.exit_code == 0, result.output
    png = next((tmp_path / "outputs").glob("*.png"))
    sidecar = json.loads(png.with_suffix(".json").read_text())
    assert sidecar["source_path"] == str(source)
    assert sidecar["remote_host"] == "m3max"


def test_unknown_host_exits_2(tmp_path, server):
    write_config(tmp_path, f'[hosts]\nm3max = "{URL}"\n')
    result = runner.invoke(app, ["generate", "x", "--host", "nope"])
    assert result.exit_code == 2
    assert "unknown host 'nope'" in result.output and "m3max" in result.output


def test_host_with_other_engine_exits_2(server):
    result = runner.invoke(app, ["generate", "x", "--host", "h:1", "--engine", "sdcpp"])
    assert result.exit_code == 2


def test_unreachable_host_exits_4_with_url(tmp_path, monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("Connection refused", request=request)

    monkeypatch.setattr(
        remote, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(refuse))
    )
    monkeypatch.setattr(remote.time, "sleep", lambda s: None)
    write_config(tmp_path, f'[hosts]\nm3max = "{URL}"\n')
    result = runner.invoke(app, ["generate", "x", "--host", "m3max"])
    assert result.exit_code == 4
    assert URL in result.output and "Connection refused" in result.output


def test_literal_host_address_is_accepted(server):
    assert run_resolve("mac.ts.net:8765") == ("mac.ts.net:8765", "http://mac.ts.net:8765")
    assert run_resolve("https://x.example") == ("https://x.example", "https://x.example")


def run_resolve(host):
    from lig.core import run

    return run.resolve_host(cfg.Settings(), host)


def test_remote_without_host_is_unavailable():
    result = runner.invoke(app, ["generate", "x", "--engine", "remote"])
    assert result.exit_code == 4


# --- doctor ---


def test_probe_host_reachable_and_unreachable(monkeypatch):
    def handler(request):
        if request.url.host == "up":
            return httpx.Response(200, json={"engine": "sdcpp"})
        raise httpx.ConnectError("no route", request=request)

    monkeypatch.setattr(
        remote, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    up = doctor.probe_host("a", "http://up:1")
    down = doctor.probe_host("b", "http://down:1")
    assert (up["status"], up["engine"]) == ("reachable", "sdcpp")
    assert down["status"] == "unreachable" and "no route" in down["reason"]


def test_doctor_lists_hosts(tmp_path, monkeypatch):
    from lig.cli import app as cli_app

    write_config(tmp_path, f'[hosts]\nm3max = "{URL}"\n')
    monkeypatch.setattr(cli_app, "_engine_factories", lambda settings: {})
    monkeypatch.setattr(
        remote,
        "make_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"engine": "sdcpp"}))
        ),
    )
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["hosts"][0]["host"] == "m3max"
    table = runner.invoke(app, ["doctor"])
    assert "m3max" in table.output and URL in table.output
