# Epic 1: Foundation & Core

## Epic Overview
**Epic ID**: Epic-01
**Description**: The package skeleton, domain models, backend protocol, output conventions, configuration and diagnostics that every other epic builds on. Nothing here needs a GPU, weights or the network; it is the part of `lig` that runs identically on the XPS, the Macs and in the offline CI container.
**Business Value**: Makes every later story small and testable. Without a `FakeBackend`, deterministic output naming and a config precedence model, each engine and command would re-invent them.
**Success Metrics**: `lig --help`, `lig doctor` and `lig config show` run from a fresh clone; test suite green in the GitLab arm64 offline container with ≥ 85 % coverage on `core/`, `models/`, `cli/`.
**Requirements**: P0-7, P0-8, P0-9, P0-10, NFR Errors, NFR Code quality.

## Epic Scope
**Total Stories**: 8 | **Total Points**: 25 | **MVP Stories**: 8

## Features in This Epic

### Feature 01.1: Package Skeleton & CI

#### Stories

##### Story 01.1-001: Project scaffold with uv, Typer and quality tooling
**User Story**: As FX, I want a `uv`-managed Python 3.12+ package exposing a `lig` entry point with ruff, pytest and coverage configured so that every later story starts from a working, linted, tested baseline.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** a fresh clone **When** I run `uv sync` then `uv run lig --help` **Then** the Typer app lists the planned subcommands (`generate`, `edit`, `seeds`, `bench`, `models`, `doctor`, `config`, `serve`) as stubs that exit 0.
- **Given** the repo **When** I run `uv run ruff check .` and `uv run pytest` **Then** both pass with at least one smoke test.
- **Given** `pyproject.toml` **When** inspected **Then** it declares `requires-python >= 3.12`, `[project.scripts] lig = "lig.cli.app:app"`, a `src/` layout, and coverage config with `fail_under = 85` scoped to `src/lig/core`, `src/lig/models`, `src/lig/cli`.

**Technical Notes**: `src/lig/` layout per CLAUDE.md. Dependencies: typer, rich, pydantic, pyyaml, pillow, httpx (client), platformdirs. Keep FastAPI/uvicorn and mflux as optional extras (`lig[serve]`, `lig[mlx]`) so the XPS install stays light.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: None
**Risk Level**: Low

##### Story 01.1-002: Offline CI pipeline on the local GitLab stack
**User Story**: As FX, I want a `.gitlab-ci.yml` that runs lint, tests and the coverage gate in the local Linux/arm64, root, no-network job container so that a passing suite on my Mac never masks a failure in CI.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** the pinned job image with `uv` available **When** the pipeline runs **Then** `uv sync --frozen` succeeds from a vendored wheel cache or a pre-populated `UV_CACHE_DIR` without network access.
- **Given** the `test` job **When** it runs **Then** it executes `ruff check`, `ruff format --check` and `pytest --cov` and fails if coverage is below 85 %.
- **Given** a test that opens a network socket **When** the suite runs **Then** the test fails with a clear message (socket guard fixture), proving the offline contract.
- **Given** the CI runs as root **When** any test relies on filesystem permissions **Then** it is skipped with an explicit `euid == 0` message rather than passing vacuously.

**Technical Notes**: Use a pytest autouse fixture that monkeypatches `socket.socket` to raise unless a test is marked `@pytest.mark.network` (none in v1). Case-sensitive ext4 in CI: keep module and file names lowercase.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 01.1-001
**Risk Level**: Medium

### Feature 01.2: Core Domain

#### Stories

##### Story 01.2-001: Request and result models with size validation
**User Story**: As FX, I want typed `GenerateRequest`, `EditRequest` and `ImageResult` models with validation so that every engine and command speaks one vocabulary and bad sizes are rejected before an engine is ever launched.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** a `GenerateRequest(prompt, width, height, steps, seed, guidance, negative_prompt, transparent)` **When** width or height is not a multiple of 32 or is below 256 or above 4096 **Then** validation fails with a message naming the nearest valid size.
- **Given** no seed **When** the request is built **Then** a random 32-bit seed is assigned and recorded, so every result is reproducible.
- **Given** an `EditRequest` **When** built **Then** it carries the reference image path, its sha256 and an optional strength, and inherits all `GenerateRequest` fields.
- **Given** an `ImageResult` **When** built **Then** it holds PNG bytes, the resolved request, engine name and version, weights used (name + sha256), timings (load, per-step, total) and host name.

**Technical Notes**: pydantic v2 models in `lig/core/models.py`. Defaults: 1024×1024, 40 steps, guidance `None` (adapter decides). Keep engine-specific knobs out of the core model; adapters map them.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 01.1-001
**Risk Level**: Low

##### Story 01.2-002: Backend protocol and FakeBackend
**User Story**: As FX, I want a `Backend` protocol with a `FakeBackend` implementation that emits a valid PNG so that commands, naming and metadata can be fully tested without weights, a GPU or the network.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** the protocol **When** inspected **Then** it defines `name`, `available() -> Availability(ok, reason)`, `generate(GenerateRequest, on_progress) -> ImageResult`, `edit(EditRequest, on_progress) -> ImageResult`, and `capabilities()` (supports_edit, supports_transparent, platforms).
- **Given** `FakeBackend` **When** `generate` is called **Then** it returns a deterministic PNG whose pixels derive from the seed and size, invokes `on_progress` once per step, and fills all `ImageResult` fields.
- **Given** `FakeBackend` configured to fail **When** `generate` is called **Then** it raises `EngineError` with a stderr excerpt, exercising the error path used by real adapters.
- **Given** a backend registry **When** `lig` resolves `--engine fake` **Then** the `FakeBackend` is selected; the registry maps engine names to classes and is the single place new engines are registered.

**Technical Notes**: `typing.Protocol` in `lig/backends/base.py`; `EngineError`, `WeightsMissing`, `EngineUnavailable` exceptions. `FakeBackend` uses Pillow to draw a seeded gradient plus the seed number so contact sheets are visually testable.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 01.2-001
**Risk Level**: Low

##### Story 01.2-003: Deterministic output naming with sidecar and PNG metadata
**User Story**: As FX, I want every output written as `YYYYMMDD-HHMMSS_<prompt-slug>_s<seed>.png` with a JSON sidecar and matching PNG text chunks so that six months later I can tell which prompt, seed and engine made any file.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** an `ImageResult` **When** written to an output dir **Then** the PNG name follows the pattern, the slug is ASCII, lowercase, ≤ 40 chars, and collisions are resolved with a `-2`, `-3` suffix.
- **Given** the written PNG **When** the sidecar `<same-name>.json` is read **Then** it validates against `SidecarSchema` (prompt, negative prompt, seed, steps, size, guidance, engine, engine version, weights with hashes, timings, host, `lig` version, created-at, and for edits the source path and sha256).
- **Given** the written PNG **When** its `tEXt` chunks are read with Pillow **Then** `lig:prompt`, `lig:seed`, `lig:engine`, `lig:sidecar` are present and match the sidecar.
- **Given** an output dir that does not exist **When** writing **Then** it is created; the default is `./outputs` unless configured.

**Technical Notes**: `lig/core/output.py`. Timestamps are local time. Write the PNG atomically (temp file + rename) so an interrupted run never leaves a truncated image beside a sidecar.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 01.2-001
**Risk Level**: Low

### Feature 01.3: Configuration & Diagnostics

#### Stories

##### Story 01.3-001: Layered configuration with provenance
**User Story**: As FX, I want configuration resolved as flag > `LIG_*` env > `~/.config/lig/config.toml` > defaults, with `lig config show` printing every effective value and where it came from, so that I never have to guess why a run used a given engine or size.
**Priority**: Must Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** a value set at several layers **When** resolved **Then** the highest-precedence layer wins, verified by a parametrised test over the full precedence matrix for at least `engine`, `output_dir`, `models_dir`, `default_host`, `steps`, `size`.
- **Given** `lig config show` **When** run **Then** each key prints its value and one of `flag`, `env`, `file`, `default`, plus the config file path used.
- **Given** `lig config init` **When** run **Then** a commented `config.toml` is written to the platform config dir (`platformdirs`) unless one exists, in which case it refuses.
- **Given** an unknown key in the file **When** loaded **Then** a warning names the key and the file line; the run continues.

**Technical Notes**: `lig/core/config.py` with a pydantic `Settings` model; env prefix `LIG_`; nested keys use `__` (e.g. `LIG_SERVE__BIND`). Store per-key provenance alongside values.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 01.1-001
**Risk Level**: Medium

##### Story 01.3-002: `lig doctor` platform and engine diagnostics
**User Story**: As FX, I want `lig doctor` to print a table of every known engine with available/unavailable and a reason, plus platform facts (OS, arch, Vulkan ICD, Metal, oneAPI, RAM, models dir, disk free), so that a failed run is diagnosable in one command.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** the XPS **When** `lig doctor` runs **Then** it reports Linux x86_64, Vulkan ICD present, no oneAPI/Level Zero, no Metal, total and available RAM, and the cached weights per engine.
- **Given** an engine whose binary is missing **When** `doctor` runs **Then** the row says `unavailable: sd-cli not found on PATH (set engines.sdcpp.binary)`.
- **Given** `--json` **When** `doctor` runs **Then** the same data is emitted as JSON for scripting.
- **Given** the CI container **When** the doctor tests run **Then** platform probes are injected via a `PlatformInfo` seam, not read from the real host.

**Technical Notes**: Probe Vulkan via `vulkaninfo --summary` if present, else the ICD json files under `/usr/share/vulkan/icd.d`; Metal via `platform.system() == "Darwin"`; oneAPI via `sycl-ls` or `/opt/intel/oneapi`. Never shell out during unit tests.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 01.2-002, 01.3-001
**Risk Level**: Low

##### Story 01.3-003: Engine log capture and friendly error surface
**User Story**: As FX, I want engine stdout/stderr captured to `~/.local/state/lig/logs/<timestamp>_<engine>.log` and, on failure, the last 20 lines plus the log path shown instead of a traceback, so that failures are readable and nothing is lost.
**Priority**: Must Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** a run **When** the engine emits output **Then** it is streamed to the log file and, at `-v`, echoed to the terminal.
- **Given** an `EngineError` **When** the CLI handles it **Then** it prints a one-line summary, the last 20 log lines in a Rich panel, the log path, and exits 1; no Python traceback unless `--debug`.
- **Given** the state dir does not exist **When** logging starts **Then** it is created with the platform state path (`platformdirs.user_state_dir`).
- **Given** more than 50 log files **When** a new run starts **Then** the oldest beyond 50 are pruned.

**Technical Notes**: A single `lig/core/logs.py`; the CLI installs one exception handler in `app.py`. Keep the Rich panel readable when not a TTY (plain text).

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 01.2-002
**Risk Level**: Low

## Sprint Breakdown
| Sprint | Stories | Points | Status |
|---|---|---|---|
| 1 | 01.1-001, 01.2-001, 01.2-002, 01.2-003 | 12 | Not started |
| 2 | 01.1-002, 01.3-001, 01.3-002, 01.3-003 | 13 | Not started |

## Epic Progress
- [ ] 01.1-001 (3) · [ ] 01.1-002 (3) · [ ] 01.2-001 (3) · [ ] 01.2-002 (3) · [ ] 01.2-003 (3) · [ ] 01.3-001 (5) · [ ] 01.3-002 (3) · [ ] 01.3-003 (2)
- **Completed**: 0 / 25 points
