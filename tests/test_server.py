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


# --- POST /v1/generate and /v1/edit (story 06.2-002) ---

import base64  # noqa: E402
import io  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from PIL import Image  # noqa: E402

from lig.backends.base import EngineError  # noqa: E402


def _png(size: tuple[int, int] = (64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, "PNG")
    return buf.getvalue()


def _decode(body: dict) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(body["png_base64"])))


def test_generate_returns_envelope_with_png_and_sidecar_fields(client):
    resp = client.post(
        "/v1/generate",
        json={"prompt": "a cat", "width": 256, "height": 256, "steps": 2, "seed": 7},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert _decode(body).size == (256, 256)
    meta = body["metadata"]
    assert meta["prompt"] == "a cat"
    assert meta["seed"] == 7
    assert meta["size"] == [256, 256]
    assert meta["engine"] == "fake"
    assert meta["remote_host"]
    assert meta["source_sha256"] is None


def test_generate_invalid_size_is_422_with_cli_message(client):
    resp = client.post("/v1/generate", json={"prompt": "x", "width": 1000})
    assert resp.status_code == 422
    assert "nearest valid size is 992" in resp.text


def test_generate_engine_failure_is_500_with_log_tail_and_path(tmp_path):
    log = tmp_path / "engine.log"
    log.write_text("\n".join(f"line {i}" for i in range(50)))

    class Failing(FakeBackend):
        def _run(self, request, on_progress):
            raise EngineError("boom", log_path=log)

    api = TestClient(create_app(Failing(), load_registry(), tmp_path))
    resp = api.post("/v1/generate", json={"prompt": "x", "steps": 1, "width": 256, "height": 256})
    assert resp.status_code == 500
    detail = resp.json()
    assert detail["log_path"] == str(log)
    assert detail["log_tail"] == [f"line {i}" for i in range(30, 50)]
    assert "boom" in detail["error"]


def test_generate_engine_failure_without_log_falls_back_to_stderr(tmp_path):
    api = TestClient(create_app(FakeBackend(fail=True), load_registry(), tmp_path))
    resp = api.post("/v1/generate", json={"prompt": "x", "steps": 1, "width": 256, "height": 256})
    assert resp.status_code == 500
    assert resp.json()["log_path"] is None
    assert resp.json()["log_tail"] == ["fake engine failure"]


def test_edit_multipart_returns_envelope_with_source_hash(client):
    import hashlib

    data = _png()
    resp = client.post(
        "/v1/edit",
        data={"prompt": "make it blue", "width": "256", "height": "256", "steps": "2"},
        files={"image": ("ref.png", data, "image/png")},
    )
    assert resp.status_code == 200
    meta = resp.json()["metadata"]
    assert meta["source_sha256"] == hashlib.sha256(data).hexdigest()
    assert meta["source_path"] == "ref.png"
    assert meta["remote_host"]


def test_edit_invalid_size_is_422(client):
    resp = client.post(
        "/v1/edit",
        data={"prompt": "x", "width": "1000"},
        files={"image": ("ref.png", _png(), "image/png")},
    )
    assert resp.status_code == 422
    assert "nearest valid size" in resp.text


def test_edit_over_limit_is_413(tmp_path):
    api = TestClient(create_app(FakeBackend(), load_registry(), tmp_path, max_upload_bytes=1024))
    resp = api.post(
        "/v1/edit",
        data={"prompt": "x"},
        files={"image": ("ref.png", b"\0" * 2048, "image/png")},
    )
    assert resp.status_code == 413


def test_edit_accepts_large_upload_under_default_limit(client):
    resp = client.post(
        "/v1/edit",
        data={"prompt": "x", "width": "256", "height": "256", "steps": "1"},
        files={"image": ("ref.png", _png() + b"\0" * (20 * 1024 * 1024), "image/png")},
    )
    assert resp.status_code == 200


def test_concurrent_requests_are_serialised(tmp_path):
    active = 0
    peak = 0
    guard = threading.Lock()

    class Slow(FakeBackend):
        def _run(self, request, on_progress):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            try:
                return super()._run(request, on_progress)
            finally:
                with guard:
                    active -= 1

    api = TestClient(create_app(Slow(), load_registry(), tmp_path))
    payload = {"prompt": "x", "steps": 1, "width": 256, "height": 256}
    codes: list[int] = []
    threads = [
        threading.Thread(
            target=lambda: codes.append(api.post("/v1/generate", json=payload).status_code)
        )
        for _ in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes == [200, 200, 200]
    assert peak == 1


# --- POST /v1/generate?stream=1 (story 06.2-003) ---

import asyncio  # noqa: E402
import json  # noqa: E402

STREAM_PAYLOAD = {"prompt": "x", "steps": 3, "width": 256, "height": 256}


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        name, data = block.split("\n")
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


def test_stream_emits_progress_per_step_then_result(client):
    resp = client.post("/v1/generate?stream=1", json=STREAM_PAYLOAD)
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(resp.text)
    assert [name for name, _ in events] == ["progress"] * 3 + ["result"]
    assert [(d["step"], d["total"]) for _, d in events[:3]] == [(1, 3), (2, 3), (3, 3)]
    assert all(d["elapsed"] >= 0 for _, d in events[:3])
    final = events[-1][1]
    assert final["metadata"]["remote_host"]
    assert base64.b64decode(final["png_b64"]).startswith(b"\x89PNG")


def test_stream_engine_failure_ends_with_error_event(tmp_path):
    api = TestClient(create_app(FakeBackend(fail=True, stderr="a\nb"), load_registry(), tmp_path))
    events = parse_sse(api.post("/v1/generate?stream=1", json=STREAM_PAYLOAD).text)
    assert [name for name, _ in events] == ["error"]
    assert events[0][1]["message"] == "fake engine failed"
    assert events[0][1]["log_tail"] == ["a", "b"]


def test_stream_invalid_request_is_still_422(client):
    resp = client.post("/v1/generate?stream=1", json={"prompt": "x", "width": 1000})
    assert resp.status_code == 422


def test_non_stream_path_unchanged(client):
    assert "png_base64" in client.post("/v1/generate", json=STREAM_PAYLOAD).json()


class _GatedBackend(FakeBackend):
    """Emits step 1, then waits; reports whether the progress callback aborted the run."""

    def __init__(self) -> None:
        super().__init__()
        self.first_step = threading.Event()
        self.proceed = threading.Event()
        self.aborted = threading.Event()

    def generate(self, request, on_progress):
        if on_progress is None:  # the non-streaming follow-up job
            return super().generate(request, None)
        on_progress(1, request.steps)
        self.first_step.set()
        assert self.proceed.wait(10)
        try:
            on_progress(2, request.steps)
        except BaseException:
            self.aborted.set()
            raise
        return super().generate(request, None)


def test_client_disconnect_cancels_engine_and_releases_lock(tmp_path):
    backend = _GatedBackend()
    api = create_app(backend, load_registry(), tmp_path)
    body = json.dumps(STREAM_PAYLOAD).encode()

    async def drive() -> None:
        sent = asyncio.Event()
        first_chunk = asyncio.Event()

        async def receive():
            if not sent.is_set():
                sent.set()
                return {"type": "http.request", "body": body, "more_body": False}
            await first_chunk.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                first_chunk.set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "path": "/v1/generate",
            "raw_path": b"/v1/generate",
            "query_string": b"stream=1",
            "headers": [(b"content-type", b"application/json")],
            "server": ("test", 80),
            "client": ("test", 1),
            "scheme": "http",
            "root_path": "",
        }
        await api(scope, receive, send)

    asyncio.run(drive())
    backend.proceed.set()
    assert backend.aborted.wait(10)
    follow_up = TestClient(api)
    backend.proceed.set()  # the next job must not deadlock on the lock
    assert follow_up.get("/v1/health").status_code == 200
    resp = follow_up.post("/v1/generate", json={**STREAM_PAYLOAD, "steps": 1})
    assert resp.status_code == 200
