"""Client backend for `lig serve`: posts jobs over HTTP, relays progress, returns the PNG."""

import base64
import json
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from lig.backends.base import (
    Availability,
    Capabilities,
    EngineError,
    EngineUnavailable,
    ProgressCallback,
)
from lig.core.models import EditRequest, GenerateRequest, ImageResult, Timings, WeightsUsed

CONNECT_TIMEOUT_S = 5.0
HEALTH_TIMEOUT_S = 10.0
RETRY_BACKOFF_S = 1.0
POLL_INTERVAL_S = 0.5
# Health predates the `capabilities` field on older servers; assume the common case.
FALLBACK_CAPABILITIES = Capabilities(supports_edit=True, supports_transparent=False, platforms=[])
_UNREACHABLE = (httpx.ConnectError, httpx.ConnectTimeout)


def make_client() -> httpx.Client:
    """Generation can take minutes, so only connecting has a deadline."""
    return httpx.Client(timeout=httpx.Timeout(None, connect=CONNECT_TIMEOUT_S))


def fetch_health(client: httpx.Client, url: str) -> dict[str, Any]:
    """GET /v1/health once; raise EngineUnavailable naming the URL on any failure."""
    target = f"{url.rstrip('/')}/v1/health"
    try:
        response = client.get(target, timeout=HEALTH_TIMEOUT_S)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise EngineUnavailable(f"cannot reach {url}: {exc}") from exc
    if not isinstance(body, dict):
        raise EngineUnavailable(f"{url} did not answer like a `lig serve` daemon")
    return body


def _sse_events(lines: Iterator[str]) -> Iterator[tuple[str, dict[str, Any]]]:
    event, data = "message", []
    for line in lines:
        if line:
            field, _, value = line.partition(":")
            if field == "event":
                event = value.strip()
            elif field == "data":
                data.append(value.removeprefix(" "))
        elif data:
            yield event, json.loads("\n".join(data))
            event, data = "message", []


class RemoteBackend:
    name = "remote"
    progress_indeterminate = False
    # `/v1/edit` answers only once the job is done, so an edit has no steps to show.
    edit_progress_indeterminate = True

    def __init__(
        self,
        host_name: str,
        url: str,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        wait: bool = False,
    ) -> None:
        self.host_name = host_name
        self.url = url.rstrip("/")
        self._client = client or make_client()
        self._sleep = sleep
        # Queue generates on the daemon and poll the job, instead of holding one request open.
        self._wait = wait
        self._health: dict[str, Any] | None = None

    def _get_health(self) -> dict[str, Any]:
        """Cached for the process lifetime; one retry with backoff if the host is unreachable."""
        if self._health is None:
            try:
                self._health = fetch_health(self._client, self.url)
            except EngineUnavailable as exc:
                if not isinstance(exc.__cause__, _UNREACHABLE):
                    raise
                self._sleep(RETRY_BACKOFF_S)
                self._health = fetch_health(self._client, self.url)
        return self._health

    def available(self) -> Availability:
        try:
            self._get_health()
        except EngineUnavailable as exc:
            return Availability(ok=False, reason=str(exc))
        return Availability(ok=True)

    @property
    def build(self) -> str:
        """The server's engine build (e.g. `metal`), from /v1/health; `unknown` if not reported."""
        return str(self._get_health().get("build") or "unknown")

    def capabilities(self) -> Capabilities:
        raw = self._get_health().get("capabilities")
        return Capabilities.model_validate(raw) if raw else FALLBACK_CAPABILITIES

    def generate(
        self, request: GenerateRequest, on_progress: ProgressCallback | None
    ) -> ImageResult:
        if self._wait:
            return self._generate_queued(request, on_progress)
        return self._post(
            "/v1/generate?stream=1", request, on_progress, json=request.model_dump(mode="json")
        )

    def edit(self, request: EditRequest, on_progress: ProgressCallback | None) -> ImageResult:
        fields = request.model_dump(
            mode="json",
            exclude={"reference_image", "reference_sha256"},
            exclude_none=True,
        )
        try:
            image = request.reference_image.read_bytes()
        except OSError as exc:
            raise EngineError(f"cannot read {request.reference_image}: {exc}") from exc
        files = {"image": (request.reference_image.name, image, "image/png")}
        data = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in fields.items()}
        return self._post("/v1/edit", request, on_progress, data=data, files=files)

    def _post(
        self,
        path: str,
        request: GenerateRequest,
        on_progress: ProgressCallback | None,
        **kwargs: Any,
    ) -> ImageResult:
        target = self.url + path
        for attempt in (1, 2):
            try:
                with self._client.stream("POST", target, **kwargs) as response:
                    if response.status_code != 200:
                        response.read()
                        raise self._http_error(response)
                    if response.headers.get("content-type", "").startswith("text/event-stream"):
                        return self._result_from_stream(response, request, on_progress)
                    response.read()  # a streamed response has no body until it is read
                    return self._result(response.json(), request)
            except _UNREACHABLE as exc:
                if attempt == 2:
                    raise EngineUnavailable(f"cannot reach {self.url}: {exc}") from exc
                self._sleep(RETRY_BACKOFF_S)
            except httpx.HTTPError as exc:
                raise EngineError(f"connection to {self.url} failed: {exc}") from exc
        raise AssertionError("unreachable")  # pragma: no cover

    def _generate_queued(
        self, request: GenerateRequest, on_progress: ProgressCallback | None
    ) -> ImageResult:
        """POST `?queue=1`, then poll `/v1/jobs/{id}`; Ctrl-C cancels the job on the daemon."""
        payload = request.model_dump(mode="json")
        try:
            response = self._client.post(self.url + "/v1/generate?queue=1", json=payload)
        except _UNREACHABLE as exc:
            raise EngineUnavailable(f"cannot reach {self.url}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise EngineError(f"connection to {self.url} failed: {exc}") from exc
        if response.status_code == 200:  # a daemon without a job queue ran it inline
            return self._result(response.json(), request)
        if response.status_code != 202:
            raise self._http_error(response)
        job_id = response.json()["id"]
        try:
            return self._follow_job(job_id, request, on_progress)
        except BaseException:
            self._cancel_job(job_id)
            raise

    def _follow_job(
        self, job_id: str, request: GenerateRequest, on_progress: ProgressCallback | None
    ) -> ImageResult:
        target = f"{self.url}/v1/jobs/{job_id}"
        last_step = 0
        while True:
            try:
                response = self._client.get(target)
            except httpx.HTTPError as exc:
                raise EngineError(f"connection to {self.url} failed: {exc}") from exc
            if response.status_code == 404:
                raise EngineError(f"{self.url} no longer knows job {job_id} (daemon restarted?)")
            if response.status_code != 200:
                raise self._http_error(response)
            job = response.json()
            progress = job.get("progress")
            if progress and on_progress and progress["step"] > last_step:
                last_step = progress["step"]
                on_progress(progress["step"], progress["total"])
            state = job["state"]
            if state == "done":
                return self._result(job["result"], request)
            if state == "failed":
                error = job.get("error") or {}
                raise EngineError(
                    f"{self.url}: {error.get('message', 'job failed')}",
                    "\n".join(error.get("log_tail") or []),
                )
            if state == "cancelled":
                raise EngineError(f"{self.url}: job {job_id} was cancelled")
            self._sleep(POLL_INTERVAL_S)

    def _cancel_job(self, job_id: str) -> None:
        """Best effort: the job is abandoned either way, so a failure here is only logged."""
        try:
            self._client.delete(f"{self.url}/v1/jobs/{job_id}", timeout=CONNECT_TIMEOUT_S)
        except httpx.HTTPError:
            pass

    def _http_error(self, response: httpx.Response) -> EngineError:
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and "error" in body:
            return EngineError(
                f"{self.url}: {body['error']}", "\n".join(body.get("log_tail") or [])
            )
        detail = body.get("detail") if isinstance(body, dict) else None
        return EngineError(
            f"{self.url} answered HTTP {response.status_code}: {detail or ''}".strip()
        )

    def _result_from_stream(
        self,
        response: httpx.Response,
        request: GenerateRequest,
        on_progress: ProgressCallback | None,
    ) -> ImageResult:
        for event, data in _sse_events(response.iter_lines()):
            if event == "progress" and on_progress:
                on_progress(data["step"], data["total"])
            elif event == "error":
                raise EngineError(
                    f"{self.url}: {data['message']}", "\n".join(data.get("log_tail") or [])
                )
            elif event == "result":
                return self._result(
                    {"metadata": data["metadata"], "png_base64": data["png_b64"]}, request
                )
        raise EngineError(f"{self.url} closed the stream before sending a result")

    def _result(self, body: dict[str, Any], request: GenerateRequest) -> ImageResult:
        meta = body["metadata"]
        return ImageResult(
            png=base64.b64decode(body["png_base64"]),
            request=request,
            engine=meta["engine"],
            engine_version=meta["engine_version"],
            weights=[WeightsUsed(**w) for w in meta["weights"]],
            timings=Timings(**meta["timings"]),
            host=meta["host"],
            remote_host=self.host_name,
        )
