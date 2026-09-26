# Epic 4: Generation Commands

## Epic Overview
**Epic ID**: Epic-04
**Description**: The user-facing commands that make `lig` useful: `generate`, `edit`, `seeds` with a contact sheet, and `bench`. Each resolves config, selects a backend, runs it with progress output, and writes the image with its sidecar.
**Business Value**: This is the product. Everything else exists so that these four commands are one line each and work the same on every machine.
**Success Metrics**: On the XPS with the Phase 0 default engine, each command produces its output in one invocation; `bench` writes a JSON record per host.
**Requirements**: P0-1, P0-2, P0-3, P0-4, NFR Errors, NFR Reproducibility.

## Epic Scope
**Total Stories**: 6 | **Total Points**: 21 | **MVP Stories**: 6

## Features in This Epic

### Feature 04.1: Generate

#### Stories

##### Story 04.1-001: `lig generate` end to end
**Status**: Done
**User Story**: As FX, I want `lig generate PROMPT [--size WxH] [--steps N] [--seed S] [--engine E] [--out DIR] [--negative TEXT]` to resolve config, run the memory pre-flight, select the backend, generate and write the PNG plus sidecar, so that a hero image for a post is one command.
**Priority**: Must Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** `lig generate "a lighthouse at dusk" --engine fake` **When** run **Then** a PNG and sidecar appear in `./outputs`, the final line prints the path, and the exit code is 0.
- **Given** `--size 1000x1000` **When** run **Then** the command exits 2 before touching any engine with the nearest valid sizes suggested.
- **Given** the configured default engine is unavailable **When** run **Then** the message includes the `available()` reason and suggests `lig doctor`; exit code 4.
- **Given** `--seed 42` twice with the fake backend **When** run **Then** the two PNGs are byte-identical.
- **Given** `--negative TEXT` **When** the engine's guidance is 1.0 **Then** the CLI warns that the negative prompt has no effect at guidance 1 and suggests `--guidance`.
- **Given** Linux and no `--size`/`--steps` flag or config value **When** `lig generate` runs locally **Then** it uses 768×768 and 30 steps, the XPS local fallback from Story 02.1-004; flags and config override it.

**Technical Notes**: `lig/cli/generate.py` orchestrates; keep the orchestration in `lig/core/run.py` so `edit`, `seeds` and the daemon reuse it. Exit codes: 1 engine error, 2 usage/validation, 3 memory refusal, 4 engine unavailable.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 01.2-002, 01.2-003, 01.3-001, 03.3-001
**Risk Level**: Medium

##### Story 04.1-002: Rich progress output
**Status**: Done
**User Story**: As FX, I want a progress bar with step count, elapsed and estimated remaining time during generation, degrading to plain lines when not a TTY, so that a four-minute render does not look hung.
**Priority**: Must Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** a backend reporting per-step progress **When** running in a TTY **Then** a Rich bar shows `step 12/40`, elapsed and ETA, followed by load and total times on completion.
- **Given** a backend with no step progress (ncnn) **When** running **Then** a spinner with elapsed time is shown.
- **Given** stdout is not a TTY or `NO_COLOR` is set **When** running **Then** progress is printed as plain lines at most once per 10 % and no ANSI codes are emitted.
- **Given** `--quiet` **When** set **Then** only the final path is printed.

**Technical Notes**: Rich `Progress` with a custom column; the `on_progress` callback from the backend protocol feeds it.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 04.1-001
**Risk Level**: Low

### Feature 04.2: Edit

#### Stories

##### Story 04.2-001: `lig edit IMAGE PROMPT`
**Status**: Done
**User Story**: As FX, I want `lig edit IMAGE PROMPT [--size] [--steps] [--seed] [--engine] [--strength]` to apply an instruction edit to an existing PNG and write the result with the source image's path and hash in the sidecar, so that "make the teapot blue" keeps the rest of the picture and stays traceable.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** a PNG and a prompt **When** `lig edit` runs with the fake backend **Then** an output PNG and sidecar are written and the sidecar's `source.path` and `source.sha256` match the input.
- **Given** no `--size` **When** editing **Then** the output size defaults to the source image size rounded down to multiples of 32, and the CLI says so.
- **Given** an engine whose `capabilities().supports_edit` is false or whose mmproj is missing **When** `lig edit` runs **Then** it exits 4 with the reason.
- **Given** an input that is not a readable image **When** run **Then** exit 2 with a clear message.

**Technical Notes**: Reuse `core/run.py`. Manual acceptance on the XPS: a single-object recolor at 1024² should leave the background visibly intact; record the result in `docs/bench/xps13.md`.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 04.1-001
**Risk Level**: Medium

### Feature 04.3: Seeds

#### Stories

##### Story 04.3-001: `lig seeds PROMPT --count N` sequential renders
**Status**: Done
**User Story**: As FX, I want `lig seeds PROMPT --count N [--seed-start S]` to render N images with consecutive seeds, so that I can compare compositions before spending four minutes on a 2K render.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** `--count 4 --seed-start 100` **When** run **Then** four PNGs with seeds 100–103 and their sidecars are written, sharing a `batch_id` in the sidecar.
- **Given** `--count 9` **When** run **Then** exit 2 with `max 8`.
- **Given** a failure on the third seed **When** it happens **Then** the first two outputs are kept, the error is reported, and the exit code is 1.
- **Given** no `--seed-start` **When** run **Then** a random start is chosen and printed.

**Technical Notes**: Sequential, not parallel: a single iGPU cannot run two engines. The engine is launched once per seed in v1; keeping it warm across seeds is a later optimisation via the daemon.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 04.1-001
**Risk Level**: Low

##### Story 04.3-002: Contact sheet with seed labels
**Status**: Done
**User Story**: As FX, I want `lig seeds` to also write a `<batch>_sheet.png` grid with each tile labelled by seed, so that picking a winner is one glance.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** N renders **When** the sheet is built **Then** tiles are laid out in a near-square grid (2×2 for 4, 3×3 for up to 8 with an empty cell), each downscaled to 512 px on the long edge, with the seed drawn in the corner.
- **Given** the sheet **When** its sidecar is read **Then** it lists the member files and seeds.
- **Given** `--no-sheet` **When** set **Then** no sheet is produced.
- **Given** the fake backend **When** the sheet is tested **Then** the test asserts grid dimensions and that each tile's dominant colour matches the corresponding render.

**Technical Notes**: Pillow only; use `ImageDraw` with the default font so no font files are needed in CI.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 04.3-001
**Risk Level**: Low

### Feature 04.4: Bench

#### Stories

##### Story 04.4-001: `lig bench` engine comparison
**Status**: Done
**User Story**: As FX, I want `lig bench [--engines a,b] [--size] [--steps] [--runs N]` to run a fixed prompt and seed on each installed engine, print a table and write `bench/<date>_<host>.json`, so that "best performance" on each machine is a recorded measurement.
**Priority**: Must Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** two available engines **When** `bench` runs **Then** for each it records engine, engine version, build backend, weights set, size, steps, load s, s/step, total s, peak RSS, and the output image hash; the table is printed and the JSON written.
- **Given** an unavailable engine in `--engines` **When** run **Then** it is listed as skipped with its reason, and the others still run.
- **Given** `--runs 3` **When** run **Then** the median is reported and all runs are kept in the JSON.
- **Given** `lig bench compare A.json B.json` **When** the files come from different hosts **Then** it refuses; same host prints a delta table.
- **Given** the fake backend **When** benched in CI **Then** the JSON schema is validated and timings are non-negative; no wall-clock assertions.

**Technical Notes**: Peak RSS via `resource.getrusage(RUSAGE_CHILDREN)` for subprocess engines and `psutil` for in-process ones. The bench JSON is what `docs/bench/*.md` tables are generated from (`lig bench render`).

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 04.1-001, 02.2-002, 02.2-003
**Risk Level**: Medium

## Sprint Breakdown
| Sprint | Stories | Points | Status |
|---|---|---|---|
| 3 | 04.1-001, 04.1-002 | 7 | Not started |
| 4 | 04.2-001, 04.3-001, 04.3-002, 04.4-001 | 14 | Not started |

## Epic Progress
- [ ] 04.1-001 (5) · [ ] 04.1-002 (2) · [ ] 04.2-001 (3) · [ ] 04.3-001 (3) · [ ] 04.3-002 (3) · [ ] 04.4-001 (5)
- **Completed**: 0 / 21 points
