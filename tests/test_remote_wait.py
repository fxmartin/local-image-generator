"""`RemoteBackend(wait=True)` / `lig generate --wait`: follow a queued job on `lig serve`."""

import threading
import time

import httpx
import pytest
from typer.testing import CliRunner

from lig.backends import remote
from lig.backends.base import EngineError
from lig.backends.fake import FakeBackend
from lig.backends.remote import RemoteBackend
from lig.cli.app import app
from lig.core.models import GenerateRequest
from lig.models.registry import load_registry

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from lig.server.app import create_app  # noqa: E402

runner = CliRunner()
URL = "http://testserver"
REQUEST = GenerateRequest(prompt="a cat", width=256, height=256, steps=3, seed=5)


def _fast_sleep(seconds: float) -> None:
    time.sleep(0.005)


def wait_backend(api_backend, tmp_path) -> RemoteBackend:
    api = create_app(api_backend, load_registry(), tmp_path)
    return RemoteBackend("mac", URL, client=TestClient(api), sleep=_fast_sleep, wait=True)


def test_wait_follows_the_job_and_relays_progress(tmp_path):
    steps = []
    result = wait_backend(FakeBackend(), tmp_path).generate(
        REQUEST, lambda s, t: steps.append((s, t))
    )
    assert result.png.startswith(b"\x89PNG")
    assert result.remote_host == "mac"
    assert steps and steps[-1] == (3, 3)
    assert steps == sorted(set(steps))  # each step reported once, in order


def test_wait_raises_engine_error_with_log_tail_on_failed_job(tmp_path):
    backend = wait_backend(FakeBackend(fail=True, stderr="a\nb"), tmp_path)
    with pytest.raises(EngineError) as exc:
        backend.generate(REQUEST, None)
    assert "fake engine failed" in str(exc.value)
    assert exc.value.stderr == "a\nb"


class _Held(FakeBackend):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.proceed = threading.Event()
        self.aborted = threading.Event()

    def generate(self, request, on_progress):
        on_progress(1, request.steps)
        self.started.set()
        assert self.proceed.wait(10)
        try:
            on_progress(2, request.steps)
        except BaseException:
            self.aborted.set()
            raise
        return super().generate(request, on_progress)


def test_interrupt_while_waiting_cancels_the_server_job(tmp_path):
    held = _Held()

    def interrupt(step: int, total: int) -> None:
        raise KeyboardInterrupt

    backend = wait_backend(held, tmp_path)
    with pytest.raises(KeyboardInterrupt):
        backend.generate(REQUEST, interrupt)
    held.proceed.set()
    assert held.aborted.wait(10)


def _mock_backend(handler) -> RemoteBackend:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return RemoteBackend("mac", URL, client=client, sleep=lambda s: None, wait=True)


def test_job_lost_to_a_daemon_restart_is_a_clear_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"id": "j1", "state": "queued", "position": 0})
        return httpx.Response(404, json={"detail": "no such job: j1"})

    with pytest.raises(EngineError, match="restarted"):
        _mock_backend(handler).generate(REQUEST, None)


def test_job_cancelled_by_someone_else_is_an_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"id": "j1", "state": "queued", "position": 0})
        return httpx.Response(200, json={"id": "j1", "state": "cancelled", "position": None})

    with pytest.raises(EngineError, match="cancelled"):
        _mock_backend(handler).generate(REQUEST, None)


def test_server_without_job_queue_answers_inline_and_is_accepted(tmp_path):
    """An older daemon ignores `?queue=1` and answers 200 with the envelope; use it."""
    api = create_app(FakeBackend(), load_registry(), tmp_path)
    inner = TestClient(api)

    def handler(request: httpx.Request) -> httpx.Response:
        return inner.post("/v1/generate", json=REQUEST.model_dump(mode="json"))

    result = _mock_backend(handler).generate(REQUEST, None)
    assert result.png.startswith(b"\x89PNG")


def test_post_rejection_is_an_engine_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "bad size"})

    with pytest.raises(EngineError, match="422"):
        _mock_backend(handler).generate(REQUEST, None)


def test_unreachable_daemon_while_polling_is_an_engine_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"id": "j1", "state": "queued", "position": 0})
        raise httpx.ReadError("boom")

    with pytest.raises(EngineError, match="connection"):
        _mock_backend(handler).generate(REQUEST, None)


def test_without_wait_the_stream_path_is_used(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(500, json={"error": "stop here"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(EngineError):
        RemoteBackend("mac", URL, client=client).generate(REQUEST, None)
    assert seen == [f"{URL}/v1/generate?stream=1"]


def test_cli_wait_flag_builds_a_waiting_remote_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.chdir(tmp_path)
    api = create_app(FakeBackend(), load_registry(), tmp_path)
    monkeypatch.setattr(remote, "make_client", lambda: TestClient(api))
    result = runner.invoke(
        app,
        ["generate", "a cat", "--host", URL, "--wait", "--size", "256x256", "--steps", "2", "-q"],
    )
    assert result.exit_code == 0, result.output
    assert list((tmp_path / "outputs").glob("*.png"))


def test_cli_wait_without_remote_engine_is_a_usage_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["generate", "a cat", "--engine", "fake", "--wait"])
    assert result.exit_code == 2
    assert "--wait" in result.output
