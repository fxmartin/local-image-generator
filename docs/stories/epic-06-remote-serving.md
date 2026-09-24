# Epic 6: Remote Serving

## Epic Overview
**Epic ID**: Epic-06
**Description**: Phase 2. Give the Macs an engine (stable-diffusion.cpp on Metal), expose it through a `lig serve` FastAPI daemon on the tailnet, and add a `remote` backend so the XPS can render on the M3 Max with `--host m3max` and get a file back that is indistinguishable in convention from a local run.
**Business Value**: The XPS is the daily machine and the weakest; the M3 Max is the strongest and idle. This epic turns the strong box into the art department for the laptop, mirroring how the LLM side of FX's lab already works.
**Success Metrics**: From the XPS, `lig generate "..." --host m3max` produces a local PNG + sidecar with `remote_host` set, with ≤ 10 s overhead beyond the Mac's local time; the daemon frees memory after the idle TTL.
**Requirements**: P1-1, P1-2, P1-3, P1-5, NFR Security (daemon), NFR Performance (remote overhead).

## Epic Scope
**Total Stories**: 8 | **Total Points**: 26 | **MVP Stories**: 0

## Features in This Epic

### Feature 06.1: Mac Engine

#### Stories

##### Story 06.1-001: stable-diffusion.cpp Metal on the M3 Max
**User Story**: As FX, I want sd.cpp built with `-DSD_METAL=ON` on the M3 Max, the `sdcpp` adapter marked available on macOS, and a first `docs/bench/m3max.md` entry, so that the daemon has an engine to serve before MLX exists.
**Priority**: Should Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** the M3 Max **When** sd.cpp is built at the pinned commit with Metal **Then** `lig doctor` shows `sdcpp: available` and `lig generate` at 1024² produces a PNG.
- **Given** `lig bench --engines sdcpp` **When** run **Then** `docs/bench/m3max.md` has the row with versions and timings.
- **Given** the sd.cpp Metal note about large-matrix performance **When** timing is poor **Then** it is recorded as such; correctness, not speed, is the exit criterion.

**Technical Notes**: Build via the nix-darwin managed toolchain if practical, else `cmake` from Homebrew; record which. The README engine section gains a macOS subsection.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 02.2-002, 03.2-002
**Risk Level**: Medium

### Feature 06.2: Daemon

#### Stories

##### Story 06.2-001: `lig serve` skeleton with health and models endpoints
**User Story**: As FX, I want `lig serve [--engine E] [--bind HOST:PORT]` to start a FastAPI app exposing `GET /v1/health` (engine, version, weights, loaded state, uptime) and `GET /v1/models`, so that a client can discover what a host offers before sending work.
**Priority**: Should Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** `lig serve --engine fake` **When** started **Then** `GET /v1/health` returns 200 with engine name, engine version, `loaded: false`, host name and `lig` version.
- **Given** `GET /v1/models` **When** called **Then** it returns the registry state for the served engine (installed/verified per artifact).
- **Given** the `serve` extra is not installed **When** `lig serve` runs **Then** it exits 2 with the install hint.
- **Given** the FastAPI `TestClient` **When** tests run **Then** no real socket is opened.

**Technical Notes**: `lig/server/app.py`; the daemon wraps exactly one local backend chosen at start. Reuse `core/run.py` so behaviour matches the CLI.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 04.1-001, 05.1-003
**Risk Level**: Low

##### Story 06.2-002: `POST /v1/generate` and `POST /v1/edit`
**User Story**: As FX, I want `POST /v1/generate` (JSON request) and `POST /v1/edit` (multipart with the reference image) to run the job on the served engine and return the PNG with the full metadata, so that the wire format carries everything the client needs to write a normal sidecar.
**Priority**: Should Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** a valid `GenerateRequest` JSON **When** posted **Then** the response is 200 with `image/png` body and an `X-Lig-Metadata` header (or a JSON envelope with base64 PNG, decided in the story) containing the sidecar fields plus `remote_host`.
- **Given** an invalid size **When** posted **Then** 422 with the same message the CLI gives.
- **Given** an engine failure **When** it happens **Then** 500 with the last 20 log lines in the body and the log path on the server.
- **Given** a multipart edit with a 20 MB PNG **When** posted **Then** it is accepted; above the configurable limit (default 50 MB) it is rejected with 413.
- **Given** two concurrent requests **When** posted **Then** the second waits on a lock (concurrency 1) rather than launching a second engine; a queue with states is Epic-08.

**Technical Notes**: Prefer the JSON envelope: simpler client, metadata and image atomic. Streaming progress is the next story.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 06.2-001
**Risk Level**: Medium

##### Story 06.2-003: Progress streaming over SSE
**User Story**: As FX, I want `POST /v1/generate?stream=1` to return server-sent events with per-step progress followed by a final event carrying the result, so that the remote progress bar on the XPS looks exactly like a local one.
**Priority**: Should Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** `stream=1` **When** the job runs **Then** events `progress {step, total, elapsed}` are emitted per step and a final `result {metadata, png_b64}` or `error {message, log_tail}` ends the stream.
- **Given** a client disconnect **When** it happens mid-run **Then** the engine process is cancelled via the runner and the lock is released.
- **Given** the fake backend **When** streamed in tests **Then** the event sequence is asserted end to end.

**Technical Notes**: `sse-starlette` or hand-rolled `StreamingResponse`; keep the non-streaming path for scripts.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 06.2-002
**Risk Level**: Medium

##### Story 06.2-004: Idle-unload TTL
**User Story**: As FX, I want the daemon to keep the engine warm between jobs and unload it after a configurable idle TTL (default 10 min; `0` means exit the engine after every job as in the reference setup), so that back-to-back renders skip the load time while the Mac gets its memory back when I stop.
**Priority**: Should Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** an in-process engine **When** two jobs arrive within the TTL **Then** the second reports `load_s ≈ 0` in its metadata.
- **Given** no job for TTL seconds **When** the timer fires **Then** the engine is unloaded, `GET /v1/health` shows `loaded: false`, and process memory returns near baseline (checked manually on the Mac, asserted via a fake in tests).
- **Given** a subprocess engine (sd.cpp) that cannot stay warm **When** served **Then** `health` reports `warm: unsupported` and the TTL is a no-op; the story documents that warm serving arrives with MLX.
- **Given** `--idle-ttl 0` **When** set **Then** every job unloads on completion.

**Technical Notes**: For sd.cpp, "warm" would need its server mode; out of scope. The TTL matters for the MLX adapter in Epic-07, which is why the mechanism lands here.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 06.2-002
**Risk Level**: Low

##### Story 06.2-005: Tailnet-only bind by default
**User Story**: As FX, I want `lig serve` to bind to the host's Tailscale address by default and warn loudly when asked to bind `0.0.0.0` without Tailscale present, so that a daemon with no auth is never exposed beyond my own network by accident.
**Priority**: Should Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** Tailscale is up **When** `lig serve` starts without `--bind` **Then** it binds the `100.x` address on port 7860 and prints the URL.
- **Given** Tailscale is absent **When** started without `--bind` **Then** it binds `127.0.0.1` and explains how to expose it.
- **Given** `--bind 0.0.0.0:7860` **When** Tailscale is absent **Then** a red warning states there is no auth and requires `--i-know` to proceed.
- **Given** tests **When** run **Then** the Tailscale probe is injected (reads `tailscale ip -4` output from a fake).

**Technical Notes**: Probe via `tailscale ip -4` if the binary exists, else the `tailscale0`/`utun` interface list via `psutil.net_if_addrs()`.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 06.2-001
**Risk Level**: Low

### Feature 06.3: Remote Client

#### Stories

##### Story 06.3-001: `RemoteBackend` and `--host`
**User Story**: As FX, I want a `remote` backend selected by `--host NAME` or config `default_host` that posts requests to `lig serve`, streams progress, uploads the reference image for edits, downloads the PNG and writes it with the standard local naming and sidecar plus `remote_host`, so that "use the Mac" is one flag.
**Priority**: Should Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** `hosts.m3max = "http://100.x.y.z:7860"` in config **When** `lig generate "..." --host m3max` runs **Then** the request goes to that URL, progress shows locally, and the resulting PNG and sidecar land in `./outputs` with `remote_host: m3max` and the server's engine details.
- **Given** `lig edit img.png "..." --host m3max` **When** run **Then** the image is uploaded and the sidecar's `source` fields refer to the local file.
- **Given** the host is unreachable **When** run **Then** exit 4 with the URL and the connection error; no retry storm (one retry with backoff).
- **Given** `lig doctor` **When** run **Then** each configured host row shows reachable/unreachable and its served engine from `/v1/health`.
- **Given** tests **When** run **Then** `httpx.MockTransport` serves fake responses; no sockets.

**Technical Notes**: `lig/backends/remote.py` implements the same protocol; `capabilities()` is fetched from `/v1/health` and cached for the process lifetime.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 06.2-003, 01.3-001
**Risk Level**: Medium

##### Story 06.3-002: Remote overhead measured and documented
**User Story**: As FX, I want `lig bench --host m3max` to compare a remote run from the XPS against the Mac's local bench for the same prompt and record the overhead in `docs/bench/m3max.md`, so that the ≤ 10 s overhead target is verified rather than assumed.
**Priority**: Should Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** the Mac's local bench JSON and a remote bench from the XPS **When** compared **Then** the overhead (remote total − local total) is printed and recorded; ≤ 10 s passes, otherwise an issue is opened with the numbers.
- **Given** the remote bench JSON **When** inspected **Then** it records both the client host and the server host.

**Technical Notes**: Overhead sources: request/response transfer of a ~2 MB PNG over Tailscale and SSE overhead; both should be well under 10 s on a LAN.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 06.3-001, 04.4-001
**Risk Level**: Low

## Sprint Breakdown
| Sprint | Stories | Points | Status |
|---|---|---|---|
| 5 | 06.1-001, 06.2-001, 06.2-002, 06.2-005 | 13 | Not started |
| 6 | 06.2-003, 06.2-004, 06.3-001, 06.3-002 | 13 | Not started |

## Epic Progress
- [ ] 06.1-001 (3) · [ ] 06.2-001 (3) · [ ] 06.2-002 (5) · [ ] 06.2-003 (3) · [ ] 06.2-004 (3) · [ ] 06.2-005 (2) · [ ] 06.3-001 (5) · [ ] 06.3-002 (2)
- **Completed**: 0 / 26 points
