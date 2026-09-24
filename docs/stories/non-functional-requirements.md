# Non-Functional Requirements

Cross-cutting requirements from `REQUIREMENTS.md` §5 "Non-functional". Where a functional story already implements the requirement, the NFR story is a verification story that references it rather than duplicating work.

## Overview
**Total Stories**: 10 | **Total Points**: 18

## Performance Requirements

### Story NFR-PERF-001: XPS 13 generation time target
**User Story**: As FX, I want a 1024², 40-step image on the XPS 13 to complete in ≤ 600 s (hard) with ≤ 300 s as the aspiration, so that image generation fits into a writing session rather than replacing it.
**Priority**: Must Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** the Phase 0 bench (02.1-004) **When** the fastest engine is chosen **Then** its recorded total time at 1024² is ≤ 600 s, or the PRD fallback is enacted and documented.
- **Given** the Phase 1 acceptance run (05.1-004) **When** timed with `lig bench` **Then** the figure is recorded in `docs/bench/xps13.md`.
- **Given** any later engine or weight bump **When** merged **Then** a fresh bench row is added; a regression > 20 % blocks the merge.

**Dependencies**: 02.1-004, 04.4-001, 05.1-004
**Risk Level**: High

### Story NFR-PERF-002: M3 Max generation time target
**User Story**: As FX, I want a 1024², 40-step image on the M3 Max via MLX in ≤ 120 s, so that remote rendering from the XPS is clearly worth the round trip.
**Priority**: Should Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** the Mac bench (07.1-003) **When** MLX is measured **Then** total ≤ 120 s sets `mlx` as the macOS default; otherwise the shortfall is recorded with the quantization used.

**Dependencies**: 07.1-003
**Risk Level**: Medium

### Story NFR-PERF-003: Remote overhead
**User Story**: As FX, I want a remote 1024² render from the XPS to add ≤ 10 s over the Mac's local time, so that the network path is never the bottleneck.
**Priority**: Should Have
**Story Points**: 1

**Acceptance Criteria**:
- **Given** 06.3-002 **When** the overhead is measured **Then** it is ≤ 10 s, else an issue is opened with the breakdown (upload, generation, download).

**Dependencies**: 06.3-002
**Risk Level**: Low

## Security Requirements

### Story NFR-SEC-001: Daemon exposure
**User Story**: As FX, I want the unauthenticated daemon to bind only to the tailnet or loopback by default and to require explicit acknowledgement for wider binds, so that a v1 decision to skip auth cannot become an open image server on a hotel network.
**Priority**: Should Have
**Story Points**: 1

**Acceptance Criteria**:
- **Given** 06.2-005 **When** verified **Then** the default bind on the M3 Max is its `100.x` address and `0.0.0.0` without Tailscale needs `--i-know`.
- **Given** the README **When** read **Then** the "no auth in v1" decision and its scope are stated in one paragraph.

**Dependencies**: 06.2-005
**Risk Level**: Medium

### Story NFR-SEC-002: Artifact provenance and licensing
**User Story**: As FX, I want every weight artifact pinned by sha256 with its license recorded and shown by `lig models list`, so that I never run an unverified file and always know what terms apply.
**Priority**: Must Have
**Story Points**: 1

**Acceptance Criteria**:
- **Given** the registry (03.1-002) **When** listed **Then** each artifact shows a license string; artifacts without one fail registry validation.
- **Given** an engine launch **When** any required artifact lacks a `.sha256.ok` marker **Then** `available()` reports `unverified` and the run refuses unless `--force`.

**Dependencies**: 03.1-002, 03.2-003
**Risk Level**: Low

## Accessibility Requirements

### Story NFR-ACC-001: Terminal accessibility
**User Story**: As FX, I want `lig` output to respect `NO_COLOR`, degrade to plain text when not a TTY, and never convey meaning by colour alone, so that logs, screen readers and CI captures stay readable.
**Priority**: Must Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** `NO_COLOR=1` or a non-TTY stdout **When** any command runs **Then** no ANSI escape sequences are emitted (asserted in tests by capturing output).
- **Given** status tables (`doctor`, `models list`, `bench`) **When** rendered **Then** status is a word (`available`, `missing`) not only a coloured glyph.
- **Given** `--quiet` **When** set **Then** only the essential result line is printed.

**Dependencies**: 04.1-002, 01.3-002
**Risk Level**: Low

## Integration Requirements

### Story NFR-INT-001: Offline guarantee
**User Story**: As FX, I want every command except `models pull` (and the optional rewriter/remote backends when explicitly invoked) to work with networking disabled, enforced by a test-suite socket guard, so that the tool keeps working on a plane and never phones home.
**Priority**: Must Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** the socket guard fixture (01.1-002) **When** the suite runs **Then** any unmarked test that opens a socket fails.
- **Given** networking disabled on the XPS **When** `generate`, `edit`, `seeds`, `bench`, `models list/verify`, `doctor`, `config` run **Then** all succeed with cached weights.
- **Given** mflux's HF download behaviour (07.1-001) **When** weights are cached **Then** `HF_HUB_OFFLINE=1` is set by the adapter so no metadata request is attempted.

**Dependencies**: 01.1-002, 07.1-001
**Risk Level**: Low

### Story NFR-INT-002: Reproducibility from a sidecar
**User Story**: As FX, I want `lig generate --from SIDECAR.json` to re-run a past image with the same engine, weights, seed and parameters, warning if any of them differ on this host, so that a sidecar is a complete recipe.
**Priority**: Should Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** a sidecar from the fake backend **When** `--from` runs on the same host **Then** the new PNG is byte-identical.
- **Given** a sidecar whose engine version or weight hashes differ from what is installed **When** `--from` runs **Then** each difference is printed and the run continues (`--strict` makes it exit 2).
- **Given** a sidecar with an expanded prompt (08.1-001) **When** `--from` runs **Then** the expanded prompt is used.

**Dependencies**: 01.2-003, 04.1-001
**Risk Level**: Low

## Infrastructure Requirements

### Story NFR-INF-001: Engine and weight pinning
**User Story**: As FX, I want engine versions (sd.cpp commit, ncnn release, mflux version) and weight hashes pinned in the registry and checked by `doctor`, so that an upstream change four days into a model's life cannot silently alter my outputs.
**Priority**: Must Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** the registry **When** an engine set is declared **Then** it carries `pinned_engine` (version string or commit) and `doctor` shows `version mismatch` when the installed engine reports a different one.
- **Given** a bump PR **When** opened **Then** it changes registry pins and adds a bench row in the same change; CI checks that a pin change is accompanied by a `docs/bench/` diff.

**Dependencies**: 03.1-002, 01.3-002
**Risk Level**: Medium

### Story NFR-INF-002: Error surface and logs
**User Story**: As FX, I want no command to ever print a raw traceback by default, with engine logs retained under the state dir and pruned to 50 files, so that failures are readable and disk does not fill.
**Priority**: Must Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** 01.3-003 **When** any `EngineError`, validation error or IO error occurs **Then** the output is a one-line summary plus context; `--debug` shows the traceback.
- **Given** an unexpected exception **When** it escapes **Then** the top-level handler prints the log path and asks to file an issue with it; exit code 1.

**Dependencies**: 01.3-003
**Risk Level**: Low
