"""In-memory job queue behind `POST /v1/generate?queue=1`: one worker, so concurrency 1.

Jobs live only as long as the daemon; a restart loses them and clients get 404.
"""

import logging
import queue
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lig.backends.base import EngineError, ProgressCallback
from lig.core.logs import TAIL_LINES, tail_lines
from lig.core.models import GenerateRequest

log = logging.getLogger(__name__)

MAX_FINISHED_JOBS = 32  # each finished job holds its PNG, so the history is bounded

QUEUED, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"
FINISHED_STATES = {DONE, FAILED, CANCELLED}

# (request, on_progress, cancelled) -> result envelope; raises Cancelled when `cancelled()` is true.
Execute = Callable[[GenerateRequest, ProgressCallback, Callable[[], bool]], dict[str, Any]]


class Cancelled(Exception):
    """Raised inside the progress callback (or before the engine starts) to abort a job."""


class JobAlreadyFinished(Exception):
    """DELETE on a job that has already reached done / failed / cancelled."""


@dataclass
class Job:
    request: GenerateRequest
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = QUEUED
    progress: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    cancel: threading.Event = field(default_factory=threading.Event)


class JobQueue:
    def __init__(self, execute: Execute) -> None:
        self._execute = execute
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._active: list[Job] = []  # running first, then queued in arrival order
        self._finished: deque[str] = deque()
        self._pending: queue.Queue[Job] = queue.Queue()
        self._worker: threading.Thread | None = None

    def submit(self, request: GenerateRequest) -> dict[str, Any]:
        job = Job(request)
        with self._lock:
            self._jobs[job.id] = job
            self._active.append(job)
            if self._worker is None:
                self._worker = threading.Thread(target=self._work, daemon=True)
                self._worker.start()
            self._pending.put(job)
            return self._view(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return self._view(job) if job else None

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        """Cancel a queued or running job; None if unknown, JobAlreadyFinished if over."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.state in FINISHED_STATES:
                raise JobAlreadyFinished(job.state)
            if job.state == QUEUED:
                self._active.remove(job)
                self._retire(job)
            # A running job stays in `_active` until the runner aborts the engine.
            job.state = CANCELLED
            job.cancel.set()
            return self._view(job)

    def _view(self, job: Job) -> dict[str, Any]:
        """Call with the lock held."""
        position = self._active.index(job) if job.state in {QUEUED, RUNNING} else None
        view: dict[str, Any] = {
            "id": job.id,
            "state": job.state,
            "position": position,
            "progress": job.progress,
        }
        if job.result is not None:
            view["result"] = job.result
        if job.error is not None:
            view["error"] = job.error
        return view

    def _retire(self, job: Job) -> None:
        """Call with the lock held: remember a finished job, evicting the oldest ones."""
        self._finished.append(job.id)
        while len(self._finished) > MAX_FINISHED_JOBS:
            self._jobs.pop(self._finished.popleft(), None)

    def _work(self) -> None:
        while True:
            job = self._pending.get()
            with self._lock:
                if job.state != QUEUED:  # cancelled while waiting
                    continue
                job.state = RUNNING
            self._run(job)

    def _run(self, job: Job) -> None:
        began = time.monotonic()

        def on_progress(step: int, total: int) -> None:
            if job.cancel.is_set():
                raise Cancelled
            job.progress = {
                "step": step,
                "total": total,
                "elapsed": round(time.monotonic() - began, 3),
            }

        result: dict[str, Any] | None = None
        error: dict[str, Any] | None = None
        try:
            result = self._execute(job.request, on_progress, job.cancel.is_set)
        except Cancelled:
            log.info("job %s cancelled", job.id)
        except EngineError as exc:
            log.error("job %s failed: %s", job.id, exc)
            tail = tail_lines(exc.log_path, TAIL_LINES) or exc.stderr.splitlines()[-TAIL_LINES:]
            error = {"message": (str(exc).splitlines() or ["engine failed"])[0], "log_tail": tail}
        except BaseException as exc:  # noqa: BLE001 - runner cancels via KeyboardInterrupt
            if not job.cancel.is_set():
                log.exception("job %s crashed", job.id)
                error = {"message": str(exc) or "internal error", "log_tail": []}
        with self._lock:
            if job.state == RUNNING:  # a cancel already marked the job otherwise
                job.state = DONE if result is not None else FAILED
                job.result, job.error = result, error
            self._active.remove(job)
            self._retire(job)
