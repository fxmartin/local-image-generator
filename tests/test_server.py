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


# --- idle-unload TTL (06.2-004) ---------------------------------------------------------------

GEN = {"prompt": "a red cube", "steps": 2, "width": 64, "height": 64, "seed": 1}


def _wait_for(predicate, timeout=10.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _warm_client(tmp_path, ttl, backend=None):
    backend = backend or FakeBackend(warm=True, cold_load_s=0.5)
    return backend, TestClient(create_app(backend, load_registry(), tmp_path, idle_ttl_s=ttl))


def test_second_job_within_ttl_skips_load(tmp_path):
    _, client = _warm_client(tmp_path, ttl=600)
    first = client.post("/v1/generate", json=GEN).json()["metadata"]
    second = client.post("/v1/generate", json=GEN).json()["metadata"]
    assert first["timings"]["load_s"] > 0
    assert second["timings"]["load_s"] == 0
    health = client.get("/v1/health").json()
    assert health["loaded"] is True
    assert health["warm"] == "supported"


def test_idle_ttl_unloads_engine(tmp_path):
    backend, client = _warm_client(tmp_path, ttl=0.05)
    client.post("/v1/generate", json=GEN)
    assert _wait_for(lambda: not backend.loaded)
    assert client.get("/v1/health").json()["loaded"] is False
    # The next job pays the load again.
    assert client.post("/v1/generate", json=GEN).json()["metadata"]["timings"]["load_s"] > 0


def test_ttl_zero_unloads_after_every_job(tmp_path):
    backend, client = _warm_client(tmp_path, ttl=0)
    client.post("/v1/generate", json=GEN)
    assert backend.loaded is False
    assert client.get("/v1/health").json()["loaded"] is False
    assert backend.unloads == 1


def test_job_arriving_before_ttl_defers_unload(tmp_path):
    backend, client = _warm_client(tmp_path, ttl=600)
    client.post("/v1/generate", json=GEN)
    assert backend.loaded is True
    assert backend.unloads == 0


def test_engine_without_warm_support_reports_unsupported(client):
    client.post("/v1/generate", json=GEN)
    health = client.get("/v1/health").json()
    assert health["warm"] == "unsupported"
    assert health["loaded"] is False


def test_ttl_is_noop_for_unsupported_engine(tmp_path):
    api = create_app(FakeBackend(), load_registry(), tmp_path, idle_ttl_s=0)
    client = TestClient(api)
    assert client.post("/v1/generate", json=GEN).status_code == 200


def test_failed_job_still_unloads_with_ttl_zero(tmp_path):
    backend = FakeBackend(warm=True, fail=True)
    _, client = _warm_client(tmp_path, ttl=0, backend=backend)
    assert client.post("/v1/generate", json=GEN).status_code == 500
    assert backend.loaded is False


def test_cli_serve_passes_idle_ttl(isolated, monkeypatch):
    import uvicorn

    calls = {}
    monkeypatch.setattr(uvicorn, "run", lambda api, **kw: calls.update(api=api, **kw))
    result = runner.invoke(app, ["serve", "--engine", "fake", "--idle-ttl", "0"])
    assert result.exit_code == 0, result.output


def test_cli_serve_rejects_negative_ttl(isolated):
    result = runner.invoke(app, ["serve", "--engine", "fake", "--idle-ttl", "-1"])
    assert result.exit_code == 2
