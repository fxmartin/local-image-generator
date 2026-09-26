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
    ) -> None:
        self.host_name = host_name
        self.url = url.rstrip("/")
        self._client = client or make_client()
        self._sleep = sleep
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
                    return self._result(response.json(), request)
            except _UNREACHABLE as exc:
                if attempt == 2:
                    raise EngineUnavailable(f"cannot reach {self.url}: {exc}") from exc
                self._sleep(RETRY_BACKOFF_S)
            except httpx.HTTPError as exc:
                raise EngineError(f"connection to {self.url} failed: {exc}") from exc
        raise AssertionError("unreachable")  # pragma: no cover

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
