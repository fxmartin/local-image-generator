# Epic 8: Polish & Extensions

## Epic Overview
**Epic ID**: Epic-08
**Description**: The P2 backlog: an optional prompt rewriter, a proper job queue for the daemon, scripting conveniences (`--json`, `--open`, shell completion), size-variant contact sheets, and an OpenVINO backend evaluation once Intel validates the pipeline. Opportunistic; none of it gates a phase.
**Business Value**: Each item removes a small recurring annoyance or unlocks a workflow (agents calling `lig`, reusing expanded prompts) without touching the core.
**Success Metrics**: Stories are pulled individually when they pay for themselves; no sprint is planned around this epic.
**Requirements**: §5 P2 list.

## Epic Scope
**Total Stories**: 5 | **Total Points**: 20 | **MVP Stories**: 0

## Features in This Epic

### Feature 08.1: Extensions

#### Stories

##### Story 08.1-001: Optional prompt rewriter
**User Story**: As FX, I want `lig generate --rewrite` to expand the prompt through a local OpenAI-compatible LLM endpoint (or Qwen's official rewriter) and save both the original and expanded prompt in the sidecar, so that a good expansion can be reused with `--prompt-from sidecar.json` without paying the rewriter cost again.
**Priority**: Could Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** `rewriter.endpoint` and `rewriter.model` in config **When** `--rewrite` is set **Then** the expanded prompt is shown before generation, used for the run, and both prompts are in the sidecar.
- **Given** `--prompt-from FILE.json` **When** set **Then** the sidecar's expanded prompt (or original if none) is used and no rewriter call is made.
- **Given** the endpoint is unreachable **When** `--rewrite` is set **Then** the CLI asks whether to continue with the original prompt (non-interactive: continue with a warning).
- **Given** tests **When** run **Then** the endpoint is `httpx.MockTransport`.

**Technical Notes**: Reuses the remote client plumbing. The rewriter system prompt lives in `lig/core/rewriter.py` and mirrors Qwen's published one where licensing allows.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 04.1-001
**Risk Level**: Low

##### Story 08.1-002: Daemon job queue
**User Story**: As FX, I want `lig serve` to accept jobs into a queue (concurrency 1) with `queued / running / done / failed` states, `GET /v1/jobs/{id}` and cancellation, so that two clients or a `seeds` batch against the Mac do not collide or time out on a held lock.
**Priority**: Could Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** two `POST /v1/generate` calls **When** the first is running **Then** the second returns 202 with a job id and position; polling or SSE on `/v1/jobs/{id}` delivers progress and the result.
- **Given** `DELETE /v1/jobs/{id}` **When** the job is queued or running **Then** it is cancelled via the runner and marked `cancelled`.
- **Given** the daemon restarts **When** jobs were queued **Then** they are lost and clients get 404; persistence is out of scope.

**Technical Notes**: In-memory `asyncio.Queue`; the `RemoteBackend` gains an `--wait` path that follows the job.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 06.2-003, 06.3-001
**Risk Level**: Medium

##### Story 08.1-003: Scripting conveniences: `--json`, `--open`, shell completion
**User Story**: As FX, I want every command to support `--json` (machine-readable result on stdout, human output on stderr), `--open` to launch the image in the system viewer, and `lig --install-completion` for bash and zsh, so that agents and shell scripts can drive `lig` and I can look at results without typing paths.
**Priority**: Could Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** `--json` **When** any command runs **Then** stdout holds exactly one JSON document matching the sidecar/bench/models schema and progress goes to stderr.
- **Given** `--open` **When** an image is written **Then** `xdg-open` (Linux) or `open` (macOS) is invoked; failure to launch is a warning, not an error.
- **Given** Typer's completion **When** installed **Then** engine names and registry artifact names complete dynamically.

**Technical Notes**: Typer provides completion; dynamic values via `autocompletion=` callbacks that read the registry without network.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 04.1-001, 04.4-001, 03.2-001
**Risk Level**: Low

##### Story 08.1-004: Size-variant contact sheet
**User Story**: As FX, I want `lig sizes PROMPT --seed S --sizes 1024x1024,1536x864,864x1536` to render the same seed at several aspect ratios into one sheet, so that I can pick the framing for a slide or a post header in one pass.
**Priority**: Could Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** a list of sizes **When** run **Then** each is validated (multiples of 32), rendered sequentially, and composed into a sheet labelled by size.
- **Given** the note from the reference article that a larger size yields a new composition **When** documented **Then** the help text says the tiles are not upscales of each other.

**Technical Notes**: Reuses the seeds sheet builder with a label callback.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 04.3-002
**Risk Level**: Low

##### Story 08.1-005: OpenVINO backend evaluation
**User Story**: As FX, I want a time-boxed evaluation of the Optimum-Intel / OpenVINO Qwen-Image-2.1 pipeline on the XPS, adopted as an `openvino` backend only if it beats the Phase 0 default, so that the Intel-validated path is not ignored once it stabilises.
**Priority**: Could Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** Intel marks the pipeline validated (no longer "experimental") **When** the story is pulled **Then** a 1024², 40-step run is timed on the XPS and added to `docs/bench/xps13.md`.
- **Given** it beats the current XPS default by ≥ 25 % **When** measured **Then** an in-process adapter is implemented following the `mlx` adapter pattern; otherwise the story closes with the numbers.

**Technical Notes**: Trigger condition, not a date. Check Intel's notebook status quarterly.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 02.1-004, 07.1-001
**Risk Level**: Medium

## Sprint Breakdown
| Sprint | Stories | Points | Status |
|---|---|---|---|
| Backlog | 08.1-001, 08.1-002, 08.1-003, 08.1-004, 08.1-005 | 20 | Not planned |

## Epic Progress
- [ ] 08.1-001 (5) · [ ] 08.1-002 (5) · [ ] 08.1-003 (3) · [ ] 08.1-004 (2) · [ ] 08.1-005 (5)
- **Completed**: 0 / 20 points
