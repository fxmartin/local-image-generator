"""FastAPI daemon exposing exactly one local backend, chosen when it starts."""

import asyncio
import base64
import hashlib
import json
import logging
import platform
import queue
import tempfile
import threading
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from lig import __version__
from lig.backends.base import Backend, EngineError
from lig.core.bench import build_backend
from lig.core.logs import TAIL_LINES, tail_lines
from lig.core.models import EditRequest, GenerateRequest, ImageResult
from lig.core.output import SidecarSchema, sidecar_for
from lig.models import cache
from lig.models.registry import Registry

log = logging.getLogger(__name__)

DEFAULT_IDLE_TTL_S = 600.0
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
STREAM_POLL_SECONDS = 0.05


class _ClientGone(Exception):
    """Raised inside the progress callback to make the runner cancel the engine."""


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class RemoteMetadata(SidecarSchema):
    """The client's sidecar fields plus the host that actually ran the job."""

    remote_host: str


class GenerateResponse(BaseModel):
    """PNG and metadata in one body so they can never disagree."""

    metadata: RemoteMetadata
    png_base64: str


def parse_bind(text: str) -> tuple[str, int]:
    """Split `HOST:PORT`; raise ValueError naming the bad value."""
    host, sep, port = text.rpartition(":")
    if not sep or not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise ValueError(f"invalid bind '{text}': expected HOST:PORT, e.g. 127.0.0.1:8765")
    return host, int(port)


def _engine_version(backend: Backend) -> str:
    """Adapters that probe a binary can fail; health must still answer."""
    try:
        return str(backend.version())  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - any probe failure degrades to "unknown"
        log.warning("engine version probe failed: %s", exc)
        return "unknown"


def _validation_detail(exc: ValidationError) -> list[dict[str, Any]]:
    return [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]


def _engine_failure(exc: EngineError) -> JSONResponse:
    tail = tail_lines(exc.log_path, TAIL_LINES) or exc.stderr.splitlines()[-TAIL_LINES:]
    return JSONResponse(
        status_code=500,
        content={
            "error": (str(exc).splitlines() or ["engine failed"])[0],
            "log_tail": tail,
            "log_path": str(exc.log_path) if exc.log_path else None,
        },
    )


def create_app(
    backend: Backend,
    registry: Registry,
    models_dir: Path,
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    idle_ttl_s: float = DEFAULT_IDLE_TTL_S,
) -> FastAPI:
    api = FastAPI(title="lig serve", version=__version__)
    started = time.monotonic()
    host = platform.node() or "localhost"
    # One engine process at a time; a queue with states is Epic-08.
    engine_lock = threading.Lock()
    warm = bool(getattr(backend, "supports_warm", False))
    last_job_end = 0.0
    idle_timer: threading.Timer | None = None

    def unload_engine() -> None:
        try:
            backend.unload()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - an unload failure must not fail the job
            log.warning("engine unload failed: %s", exc)

    def idle_expired() -> None:
        with engine_lock:
            # A job that ran meanwhile re-armed its own timer; this one is stale.
            if time.monotonic() - last_job_end >= idle_ttl_s:
                unload_engine()

    def job_finished() -> None:
        """Call with `engine_lock` held: unload now (ttl 0) or arm the idle timer."""
        nonlocal last_job_end, idle_timer
        if not warm:
            return
        last_job_end = time.monotonic()
        if idle_timer is not None:
            idle_timer.cancel()
        if idle_ttl_s <= 0:
            unload_engine()
            return
        idle_timer = threading.Timer(idle_ttl_s, idle_expired)
        idle_timer.daemon = True
        idle_timer.start()

    def respond(result: ImageResult, source_name: str | None = None) -> GenerateResponse:
        sidecar = sidecar_for(result, datetime.now(UTC))
        if source_name is not None:
            # The server-side temp path is meaningless to the client.
            sidecar = sidecar.model_copy(update={"source_path": source_name})
        metadata = RemoteMetadata(**{**sidecar.model_dump(), "remote_host": host})
        return GenerateResponse(
            metadata=metadata, png_base64=base64.b64encode(result.png).decode("ascii")
        )

    def report() -> dict[str, Any]:
        return cache.build_report(registry, models_dir, backend.name)

    @api.get("/v1/health")
    def health() -> dict[str, Any]:
        artifacts = report()["artifacts"]
        return {
            "engine": backend.name,
            "engine_version": _engine_version(backend),
            "build": build_backend(backend.name),
            "capabilities": backend.capabilities().model_dump(),
            "weights": {
                "installed": sum(a["status"] == "installed" for a in artifacts),
                "total": len(artifacts),
            },
            "loaded": bool(getattr(backend, "loaded", False)) if warm else False,
            # Subprocess engines exit after each job, so the idle TTL cannot apply to them.
            "warm": "supported" if warm else "unsupported",
            "host": host,
            "lig_version": __version__,
            "uptime_s": round(time.monotonic() - started, 3),
        }

    @api.get("/v1/models")
    def models() -> dict[str, Any]:
        return report()

    def stream_generate(request: GenerateRequest) -> StreamingResponse:
        """Run the job on a worker thread and relay its progress as server-sent events."""
        events: queue.Queue[str | None] = queue.Queue()
        gone = threading.Event()

        def work() -> None:
            with engine_lock:
                if gone.is_set():  # client left while waiting for the lock
                    events.put(None)
                    return
                began = time.monotonic()

                def on_progress(step: int, total: int) -> None:
                    if gone.is_set():
                        raise _ClientGone
                    elapsed = round(time.monotonic() - began, 3)
                    events.put(_sse("progress", {"step": step, "total": total, "elapsed": elapsed}))

                try:
                    body = respond(backend.generate(request, on_progress))
                    events.put(
                        _sse(
                            "result",
                            {"metadata": body.metadata.model_dump(), "png_b64": body.png_base64},
                        )
                    )
                except _ClientGone:
                    log.info("client disconnected; generate cancelled")
                except EngineError as exc:
                    log.error("generate failed: %s", exc)
                    failure = json.loads(_engine_failure(exc).body)
                    events.put(
                        _sse(
                            "error",
                            {"message": failure["error"], "log_tail": failure["log_tail"]},
                        )
                    )
                except BaseException as exc:  # noqa: BLE001 - runner cancels via KeyboardInterrupt
                    if not gone.is_set():
                        log.exception("generate crashed")
                        events.put(
                            _sse("error", {"message": str(exc) or "internal error", "log_tail": []})
                        )
                finally:
                    events.put(None)

        async def relay() -> AsyncIterator[str]:
            threading.Thread(target=work, daemon=True).start()
            try:
                while True:
                    try:
                        item = events.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(STREAM_POLL_SECONDS)
                        continue
                    if item is None:
                        return
                    yield item
            finally:
                # Also runs on cancellation when the client drops the connection.
                gone.set()

        return StreamingResponse(
            relay(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @api.post("/v1/generate", response_model=GenerateResponse)
    def generate(request: GenerateRequest, stream: int = 0) -> Any:
        if stream:
            return stream_generate(request)
        with engine_lock:
            try:
                result = backend.generate(request, None)
            except EngineError as exc:
                log.error("generate failed: %s", exc)
                return _engine_failure(exc)
            finally:
                job_finished()
        return respond(result)

    @api.post("/v1/edit", response_model=GenerateResponse)
    def edit(
        image: Annotated[UploadFile, File()],
        prompt: Annotated[str, Form()],
        width: Annotated[int | None, Form()] = None,
        height: Annotated[int | None, Form()] = None,
        steps: Annotated[int | None, Form()] = None,
        seed: Annotated[int | None, Form()] = None,
        guidance: Annotated[float | None, Form()] = None,
        negative_prompt: Annotated[str | None, Form()] = None,
        transparent: Annotated[bool, Form()] = False,
        strength: Annotated[float | None, Form()] = None,
    ) -> Any:
        with tempfile.TemporaryDirectory(prefix="lig-edit-") as tmp:
            reference = Path(tmp) / "reference.png"
            digest = hashlib.sha256()
            received = 0
            with reference.open("wb") as out:
                while chunk := image.file.read(UPLOAD_CHUNK_BYTES):
                    received += len(chunk)
                    if received > max_upload_bytes:
                        raise HTTPException(
                            413, f"reference image exceeds the {max_upload_bytes} byte limit"
                        )
                    digest.update(chunk)
                    out.write(chunk)
            given = {
                "prompt": prompt,
                "width": width,
                "height": height,
                "steps": steps,
                "seed": seed,
                "guidance": guidance,
                "negative_prompt": negative_prompt,
                "strength": strength,
            }
            fields: dict[str, Any] = {k: v for k, v in given.items() if v is not None}
            try:
                request = EditRequest(
                    **fields,
                    transparent=transparent,
                    reference_image=reference,
                    reference_sha256=digest.hexdigest(),
                )
            except ValidationError as exc:
                raise HTTPException(422, detail=_validation_detail(exc)) from exc
            with engine_lock:
                try:
                    result = backend.edit(request, None)
                except EngineError as exc:
                    log.error("edit failed: %s", exc)
                    return _engine_failure(exc)
                finally:
                    job_finished()
        return respond(result, source_name=image.filename or "reference.png")

    return api
