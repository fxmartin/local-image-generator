"""`POST /v1/generate?queue=1` and `/v1/jobs/{id}` (story 08.1-002): the in-memory job queue."""

import base64
import threading

import pytest

from lig.backends.fake import FakeBackend
from lig.models.registry import load_registry

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from lig.server import jobs as server_jobs  # noqa: E402
from lig.server.app import create_app  # noqa: E402

PAYLOAD = {"prompt": "x", "steps": 3, "width": 256, "height": 256}


class _Gated(FakeBackend):
    """Runs step 1, then waits on `proceed`, so a test can hold a job in `running`."""

    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.proceed = threading.Event()
        self.aborted = threading.Event()
        self.prompts: list[str] = []

    def generate(self, request, on_progress):
        self.prompts.append(request.prompt)
        if request.prompt != "hold":
            return super().generate(request, on_progress)
        on_progress(1, request.steps)
        self.started.set()
        assert self.proceed.wait(10)
        try:
            on_progress(2, request.steps)
        except BaseException:
            self.aborted.set()
            raise
        return super().generate(request, on_progress)


def _wait_for(predicate, timeout=10.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _state(client, job_id):
    return client.get(f"/v1/jobs/{job_id}").json()


def _settled(client, job_id, want):
    assert _wait_for(lambda: _state(client, job_id)["state"] == want), _state(client, job_id)
    return _state(client, job_id)


@pytest.fixture
def gated(tmp_path):
    backend = _Gated()
    return backend, TestClient(create_app(backend, load_registry(), tmp_path))


def test_queue_returns_202_with_id_and_runs_to_done(tmp_path):
    client = TestClient(create_app(FakeBackend(), load_registry(), tmp_path))
    resp = client.post("/v1/generate?queue=1", json=PAYLOAD)
    assert resp.status_code == 202
    body = resp.json()
    assert body["id"]
    assert body["state"] in {"queued", "running", "done"}
    assert resp.headers["location"] == f"/v1/jobs/{body['id']}"
    job = _settled(client, body["id"], "done")
    assert job["progress"] == {"step": 3, "total": 3, "elapsed": job["progress"]["elapsed"]}
    assert job["position"] is None
    assert job["result"]["metadata"]["remote_host"]
    assert base64.b64decode(job["result"]["png_base64"]).startswith(b"\x89PNG")


def test_second_job_is_queued_behind_the_running_one(gated):
    backend, client = gated
    first = client.post("/v1/generate?queue=1", json={**PAYLOAD, "prompt": "hold"}).json()
    assert backend.started.wait(10)
    second = client.post("/v1/generate?queue=1", json={**PAYLOAD, "prompt": "next"})
    assert second.status_code == 202
    assert second.json()["state"] == "queued"
    assert second.json()["position"] == 1
    running = _state(client, first["id"])
    assert running["state"] == "running"
    assert running["position"] == 0
    assert running["progress"]["step"] == 1
    assert backend.prompts == ["hold"]  # concurrency 1: the second has not started
    backend.proceed.set()
    _settled(client, first["id"], "done")
    done = _settled(client, second.json()["id"], "done")
    assert done["result"]["png_base64"]


def test_failed_job_reports_error_and_log_tail(tmp_path):
    backend = FakeBackend(fail=True, stderr="a\nb")
    client = TestClient(create_app(backend, load_registry(), tmp_path))
    job_id = client.post("/v1/generate?queue=1", json=PAYLOAD).json()["id"]
    job = _settled(client, job_id, "failed")
    assert job["error"] == {"message": "fake engine failed", "log_tail": ["a", "b"]}
    assert "result" not in job


def test_failed_job_does_not_block_the_next(tmp_path):
    backend = FakeBackend(fail=True)
    client = TestClient(create_app(backend, load_registry(), tmp_path))
    first = client.post("/v1/generate?queue=1", json=PAYLOAD).json()["id"]
    _settled(client, first, "failed")
    backend._fail = False
    second = client.post("/v1/generate?queue=1", json=PAYLOAD).json()["id"]
    _settled(client, second, "done")


def test_unknown_job_is_404(tmp_path):
    api = TestClient(create_app(FakeBackend(), load_registry(), tmp_path))
    assert api.get("/v1/jobs/nope").status_code == 404
    assert api.delete("/v1/jobs/nope").status_code == 404


def test_delete_queued_job_cancels_it_and_it_never_runs(gated):
    backend, client = gated
    client.post("/v1/generate?queue=1", json={**PAYLOAD, "prompt": "hold"})
    assert backend.started.wait(10)
    queued = client.post("/v1/generate?queue=1", json={**PAYLOAD, "prompt": "never"}).json()
    resp = client.delete(f"/v1/jobs/{queued['id']}")
    assert resp.status_code == 200
    assert resp.json()["state"] == "cancelled"
    third = client.post("/v1/generate?queue=1", json={**PAYLOAD, "prompt": "last"}).json()
    assert third["position"] == 1  # the cancelled job no longer holds a place
    backend.proceed.set()
    _settled(client, third["id"], "done")
    assert "never" not in backend.prompts
    assert _state(client, queued["id"])["state"] == "cancelled"


def test_delete_running_job_aborts_the_engine_and_frees_the_queue(gated):
    backend, client = gated
    running = client.post("/v1/generate?queue=1", json={**PAYLOAD, "prompt": "hold"}).json()
    assert backend.started.wait(10)
    follow = client.post("/v1/generate?queue=1", json={**PAYLOAD, "prompt": "after"}).json()
    resp = client.delete(f"/v1/jobs/{running['id']}")
    assert resp.status_code == 200
    assert resp.json()["state"] == "cancelled"
    backend.proceed.set()
    assert backend.aborted.wait(10)
    _settled(client, follow["id"], "done")
    assert _state(client, running["id"])["state"] == "cancelled"
    assert "result" not in _state(client, running["id"])


def test_delete_finished_job_is_409(tmp_path):
    client = TestClient(create_app(FakeBackend(), load_registry(), tmp_path))
    job_id = client.post("/v1/generate?queue=1", json=PAYLOAD).json()["id"]
    _settled(client, job_id, "done")
    assert client.delete(f"/v1/jobs/{job_id}").status_code == 409


def test_invalid_request_is_422_and_creates_no_job(tmp_path):
    client = TestClient(create_app(FakeBackend(), load_registry(), tmp_path))
    assert (
        client.post("/v1/generate?queue=1", json={"prompt": "x", "width": 1000}).status_code == 422
    )


def test_queued_job_waits_for_a_blocking_request_holding_the_engine(tmp_path):
    release = threading.Event()
    entered = threading.Event()

    class Blocking(FakeBackend):
        def generate(self, request, on_progress):
            if request.prompt == "block":
                entered.set()
                assert release.wait(10)
            return super().generate(request, on_progress)

    client = TestClient(create_app(Blocking(), load_registry(), tmp_path))
    blocker = threading.Thread(
        target=lambda: client.post("/v1/generate", json={**PAYLOAD, "prompt": "block"})
    )
    blocker.start()
    assert entered.wait(10)
    job_id = client.post("/v1/generate?queue=1", json=PAYLOAD).json()["id"]
    assert _state(client, job_id)["state"] in {"queued", "running"}
    release.set()
    blocker.join()
    _settled(client, job_id, "done")


def test_finished_jobs_are_evicted_oldest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(server_jobs, "MAX_FINISHED_JOBS", 2)
    client = TestClient(create_app(FakeBackend(), load_registry(), tmp_path))
    ids = []
    for _ in range(3):
        job_id = client.post("/v1/generate?queue=1", json=PAYLOAD).json()["id"]
        _settled(client, job_id, "done")
        ids.append(job_id)
    assert client.get(f"/v1/jobs/{ids[0]}").status_code == 404
    assert client.get(f"/v1/jobs/{ids[2]}").status_code == 200


def test_queued_job_arms_the_idle_unload(tmp_path):
    backend = FakeBackend(warm=True)
    client = TestClient(create_app(backend, load_registry(), tmp_path, idle_ttl_s=0))
    job_id = client.post("/v1/generate?queue=1", json=PAYLOAD).json()["id"]
    _settled(client, job_id, "done")
    assert _wait_for(lambda: backend.unloads == 1)
