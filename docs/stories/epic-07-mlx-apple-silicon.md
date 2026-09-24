# Epic 7: MLX on Apple Silicon

## Epic Overview
**Epic ID**: Epic-07
**Description**: Phase 3. An in-process `mlx` backend built on mflux's `QwenImage21`, quantized by default, with edit support, a Mac bench against sd.cpp Metal, transparent PNG output where engines support it, and `lig models pull --for ENGINE`.
**Business Value**: sd.cpp Metal has known large-matrix performance issues; mflux reports ~1.5 s/step at 1024² in bf16 on Apple Silicon. This epic makes the M3 Max fast, which makes remote rendering from the XPS worth it.
**Success Metrics**: `docs/bench/m3max.md` shows MLX vs sd.cpp Metal; macOS default engine set from the numbers; ≤ 2 min per 1024² image on the M3 Max.
**Requirements**: P1-4, P1-6, P1-7, NFR Performance (M3 Max).

## Epic Scope
**Total Stories**: 5 | **Total Points**: 16 | **MVP Stories**: 0

## Features in This Epic

### Feature 07.1: MLX Backend

#### Stories

##### Story 07.1-001: mflux `QwenImage21` in-process adapter
**User Story**: As FX, I want an `mlx` backend that loads mflux's `QwenImage21` with `-q 8` quantization by default (bf16 optional) and runs `generate` in-process with per-step progress, so that the Macs use the fastest available engine.
**Priority**: Should Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** macOS arm64 with the `mlx` extra installed **When** `lig generate --engine mlx` runs **Then** a PNG is produced with `engine_version` set to the mflux version and `weights` naming the quantization.
- **Given** Linux **When** `available()` runs **Then** it returns `unsupported platform: mlx requires macOS arm64` without importing mflux.
- **Given** `engines.mlx.quantize = 4|8|none` **When** set **Then** the corresponding mflux option is used and recorded in the sidecar.
- **Given** the test suite on Linux **When** run **Then** the adapter is tested through an injected fake `QwenImage21` class; mflux is never imported in CI.
- **Given** the daemon's idle TTL **When** the engine is served **Then** the loaded model object is released on unload and `health` reports `warm: supported`.

**Technical Notes**: mflux downloads `Qwen/Qwen-Image-2.1` (~33 GB bf16) into the HF cache on first use; either point it at `lig`'s cache via `HF_HOME` or register the HF snapshot as a `bundle` artifact so `models list` reports it. Decide in the story.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 01.2-002, 06.2-004
**Risk Level**: Medium

##### Story 07.1-002: MLX edit support
**User Story**: As FX, I want `lig edit --engine mlx` mapped to mflux's image-to-image path (`image_path`, `image_strength`) so that editing works on the Macs too.
**Priority**: Should Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** an `EditRequest` **When** `mlx.edit` runs against the fake class **Then** the call carries the reference image path and strength (default from config, e.g. 0.6).
- **Given** mflux's edit semantics differ from sd.cpp's instruction editing **When** documented **Then** the README states the difference and the recommended strength range.
- **Given** an engine without the reference-image feature at the pinned version **When** `capabilities()` runs **Then** `supports_edit` is false and `lig edit` exits 4 with the reason.

**Technical Notes**: Verify at the pinned mflux version whether Qwen 2.1 exposes instruction editing or only img2img; record in the adapter docstring.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 07.1-001
**Risk Level**: Medium

##### Story 07.1-003: Mac bench and macOS default engine
**User Story**: As FX, I want `lig bench --engines mlx,sdcpp` on the M3 Max recorded in `docs/bench/m3max.md` and the built-in macOS default engine set from the winner, so that Mac users (me) get the fast path without configuring anything.
**Priority**: Should Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** both engines installed **When** benched at 1024², 40 steps **Then** the doc has both rows with versions, quantization, timings and peak memory.
- **Given** MLX ≤ 120 s total **When** the target is met **Then** the macOS default is `mlx`; otherwise the doc records why and the default stays `sdcpp`.
- **Given** the `home-lab` M1 Pro **When** available **Then** a second row set is recorded for it.

**Technical Notes**: Run bench with the daemon stopped so memory numbers are clean.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 07.1-001, 06.1-001, 04.4-001
**Risk Level**: Low

### Feature 07.2: Output & Model Conveniences

#### Stories

##### Story 07.2-001: `--transparent` RGBA output
**User Story**: As FX, I want `lig generate --transparent` to produce an RGBA PNG with a real alpha channel on engines that support it (sd.cpp per its docs) and fail clearly on those that do not, so that logos and cut-outs for slides need no post-processing.
**Priority**: Should Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** `--transparent` on `sdcpp` **When** run **Then** the adapter applies the documented prompt/flag form for alpha output and the PNG mode is `RGBA` with at least one pixel below 255 alpha (asserted via the stub writing an RGBA image).
- **Given** `--transparent` on an engine with `supports_transparent = false` **When** run **Then** exit 4 with the reason.
- **Given** the sidecar **When** read **Then** `transparent: true` is recorded.

**Technical Notes**: sd.cpp's doc says alpha is supported in PNG/WebP with a specific prompt format; capture that format in the adapter's flag table during implementation.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 02.2-002
**Risk Level**: Low

##### Story 07.2-002: `lig models pull --for ENGINE`
**User Story**: As FX, I want `lig models pull --for ENGINE` to pull exactly the artifact set that engine needs on this platform, printing the disk estimate first, so that no orphan downloads accumulate.
**Priority**: Should Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** `--for sdcpp` on Linux **When** run **Then** only the sd.cpp set is pulled; `--for mlx` on Linux exits 2 with `unsupported platform`.
- **Given** an engine set with alternatives (Q4 vs Q8) **When** `--quant` is not given **Then** the registry default is used and named in the output.
- **Given** `lig models prune` **When** run **Then** artifacts belonging to no engine set for this platform are listed for deletion with confirmation.

**Technical Notes**: Builds on `registry.set_for(engine, platform)` from 03.1-001.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 03.2-002
**Risk Level**: Low

## Sprint Breakdown
| Sprint | Stories | Points | Status |
|---|---|---|---|
| 7 | 07.1-001, 07.1-002, 07.1-003 | 10 | Not started |
| 8 | 07.2-001, 07.2-002 | 6 | Not started |

## Epic Progress
- [ ] 07.1-001 (5) · [ ] 07.1-002 (3) · [ ] 07.1-003 (2) · [ ] 07.2-001 (3) · [ ] 07.2-002 (3)
- **Completed**: 0 / 16 points
