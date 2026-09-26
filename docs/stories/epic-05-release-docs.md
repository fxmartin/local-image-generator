# Epic 5: Release & Documentation

## Epic Overview
**Epic ID**: Epic-05
**Description**: Everything that turns a working tree into something installable from a fresh clone: README with per-platform engine setup, `uv tool install` packaging, conventional-commit enforcement, CHANGELOG and version/tag alignment, and the formal Phase 1 acceptance run on the XPS.
**Business Value**: The Phase 1 definition of done is "fresh clone → README → 1024² PNG in one documented command". This epic is that sentence.
**Success Metrics**: FX reproduces the Phase 1 DoD on the XPS from a clean shell in ≤ 10 min per image and records it; `v0.1.0` tag matches `pyproject.toml`.
**Requirements**: P0-11, §6 Definition of done, NFR Code quality, CLAUDE.md Commit Format and Release Version Alignment.

## Epic Scope
**Total Stories**: 4 | **Total Points**: 9 | **MVP Stories**: 4

## Features in This Epic

### Feature 05.1: Docs & Release

#### Stories

##### Story 05.1-001: README with install, engine setup and the five commands
**User Story**: As FX, I want a README covering `uv tool install`, engine build/install per platform (sd.cpp Vulkan on Arch, sd.cpp Metal on macOS, ncnn release binary), first-run `lig models pull`, and `generate`/`edit`/`seeds`/`bench`/`models` with real examples, so that a clean machine can be set up without me remembering anything.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** the README **When** followed on the XPS from a clean shell **Then** every command runs as written; no hostnames, home paths or secrets are hardcoded.
- **Given** the engine section **When** read **Then** each engine has the pinned commit/release, the exact build command, and the expected `lig doctor` row after install.
- **Given** the commands section **When** read **Then** each of the five commands has one copy-pasteable example and its exit codes.
- **Given** the troubleshooting section **When** read **Then** it covers out-of-memory (pre-flight exit 3), missing weights (exit 4), and where logs are.

**Technical Notes**: Keep README under ~300 lines; longer material goes in `docs/`. `lig --help` text and README examples must agree (a test can snapshot `--help`).

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 04.1-001, 04.2-001, 04.3-002, 04.4-001, 03.2-002
**Risk Level**: Low

##### Story 05.1-002: Conventional commits, CHANGELOG and version alignment
**User Story**: As FX, I want commitlint configured for conventional commits, a `CHANGELOG.md` maintained per release, and a check that the git tag `vX.Y.Z` equals `pyproject.toml` version, so that releases carry reliable semver signal.
**Priority**: Must Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** `.commitlintrc.json` **When** a commit header violates the format **Then** the CI `commit-format` job fails; existing history is exempt.
- **Given** `CHANGELOG.md` **When** a release is cut **Then** it has a section per version generated from commit types (`feat`, `fix`, breaking).
- **Given** a tag whose name disagrees with `pyproject.toml` **When** the `release-check` script runs **Then** it exits 1 naming both values.
- **Given** the `uv version` command **When** bumping **Then** `uv.lock` is updated in the same commit.

**Technical Notes**: Node is not a project dependency; run commitlint via `npx` in the CI job only, or use a Python-only checker if the offline container has no Node. Decide in the story, record in CLAUDE.md.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 01.1-002
**Risk Level**: Low

##### Story 05.1-003: `uv tool install` packaging validated on a clean shell
**User Story**: As FX, I want `uv tool install .` (and later `uv tool install lig` from a git URL) to produce a working `lig` on PATH with the `serve` and `mlx` extras optional, so that installation is one command on every machine.
**Priority**: Must Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** a clean shell without the repo venv activated **When** `uv tool install .` runs **Then** `lig --version` prints the version and `lig doctor` works.
- **Given** `uv tool install ".[serve]"` **When** run on the Mac **Then** `lig serve --help` works; without the extra it prints a one-line hint to install it.
- **Given** `pyproject.toml` **When** inspected **Then** metadata (name, description, license, classifiers, urls) is complete and the wheel builds with `uv build`.

**Technical Notes**: Optional extras keep the XPS install free of FastAPI/uvicorn and mflux (which would not install on Linux anyway).

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 01.1-001
**Risk Level**: Low

##### Story 05.1-004: Phase 1 acceptance run on the XPS
**User Story**: As FX, I want a recorded acceptance run that follows the README on the XPS from a fresh clone and produces a 768², 30-step image (the local fallback from Story 02.1-004) in ≤ 10 min, plus edit, seeds, bench and models each exercised once, so that Phase 1 is closed on evidence and `v0.1.0` is tagged.
**Priority**: Must Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** a fresh clone in a new directory **When** the README is followed **Then** `lig generate` yields a 768², 30-step PNG (the local fallback from Story 02.1-004) with total time ≤ 600 s recorded in `docs/bench/xps13.md` under "Phase 1 acceptance".
- **Given** the same session **When** `edit`, `seeds --count 4`, `bench` and `models list/verify` run **Then** each succeeds and its output path or table is pasted into the acceptance section.
- **Given** all of the above **When** done **Then** `pyproject.toml` is `0.1.0`, `CHANGELOG.md` has the section, and tag `v0.1.0` is pushed.
- **Given** any step fails **When** it does **Then** an issue is opened with the failing command and log, and the tag is not created.

**Technical Notes**: This is a manual story; the "tests" are the acceptance record. Time it with `lig bench` output, not a stopwatch.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 05.1-001, 05.1-002, 05.1-003, 02.1-004
**Risk Level**: Medium

## Sprint Breakdown
| Sprint | Stories | Points | Status |
|---|---|---|---|
| 2 | 05.1-002, 05.1-003 | 4 | Not started |
| 4 | 05.1-001, 05.1-004 | 5 | Not started |

## Epic Progress
- [x] 05.1-001 (3) · [x] 05.1-002 (2) · [x] 05.1-003 (2) · [x] 05.1-004 (2)
- **Completed**: 9 / 9 points (Phase 1 acceptance passed 2026-09-26; `v0.1.0`)
