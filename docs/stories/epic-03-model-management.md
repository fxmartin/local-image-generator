# Epic 3: Model Management

## Epic Overview
**Epic ID**: Epic-03
**Description**: A curated registry of Qwen-Image-2.1 weight artifacts (repo, filename, sha256, size, engine, role, license), a resumable verified downloader, one cache directory, and the `lig models` command family. Includes the pre-flight memory estimate that refuses runs that cannot fit.
**Business Value**: First-run friction is the biggest reason local image tools get abandoned: 10–35 GB across three or four files, a VAE version that silently breaks output, no idea what is on disk. This epic makes weights boring.
**Success Metrics**: `lig models pull --engine sdcpp` on a clean machine fetches exactly the needed files, verifies them, and `lig models list` shows sizes, licenses and disk usage; a corrupted file is caught by `verify`.
**Requirements**: P0-6, NFR Memory safety, NFR Licensing, NFR Offline after first pull, Risk rows 3–4.

## Epic Scope
**Total Stories**: 6 | **Total Points**: 19 | **MVP Stories**: 6

## Features in This Epic

### Feature 03.1: Artifact Registry

#### Stories

##### Story 03.1-001: Registry schema and loader
**User Story**: As FX, I want a YAML registry checked into the repo describing every weight artifact with repo, filename, sha256, size, engine, role and license, validated on load, so that adapters resolve weights by role instead of hardcoding paths.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** `src/lig/models/registry.yaml` **When** loaded **Then** each artifact validates against `Artifact(name, repo, filename, sha256, size_bytes, engines[], role in {transformer, text_encoder, vae, mmproj, bundle}, license, url)` and duplicate names fail loudly.
- **Given** an engine name **When** `registry.set_for(engine, platform)` is called **Then** it returns the ordered list of artifacts that engine needs on that platform, or raises if a role is missing.
- **Given** a registry with an invalid sha256 length or negative size **When** loaded **Then** a validation error names the artifact and field.
- **Given** the registry **When** a test loads it **Then** no network is touched.

**Technical Notes**: Engine sets are declared in the same file (`sets: sdcpp-q4: [...]`). Keep `url` explicit rather than derived, so non-HF mirrors work.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 01.1-001
**Risk Level**: Low

##### Story 03.1-002: Seed the registry with the Qwen-Image-2.1 sets
**User Story**: As FX, I want the registry populated with the sd.cpp Q4 set (leejet Q4 GGUF transformer, `Qwen3VL-8B-Instruct-Q4_K_M.gguf`, `qwen_image_2.1_vae_bf16.safetensors`, `mmproj-Qwen3VL-8B-Instruct-F16.gguf`) and the ncnn model bundle, with hashes taken from the Phase 0 downloads, so that `pull` works on day one.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** the files downloaded during 02.1-001 and 02.1-002 **When** their sha256 and sizes are entered **Then** `lig models verify` on the spike machine passes for every artifact.
- **Given** each artifact **When** listed **Then** its license is recorded (Apache-2.0 for official Qwen weights; the actual license of each community conversion, checked on its model card).
- **Given** a second quantization (e.g. Q8 transformer) **When** added **Then** it appears as an alternative set, not the default.
- **Given** the sd.cpp doc's warning **When** the VAE is registered **Then** its description notes it is specific to 2.1 and not interchangeable with earlier Qwen-Image VAEs.

**Technical Notes**: Prefer leejet/unsloth GGUF repos. Registry entries carry a `pinned_engine` note (sd.cpp commit, ncnn release) so an engine bump is reviewed together with its weights.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 03.1-001, 02.1-001, 02.1-002
**Risk Level**: Medium

### Feature 03.2: Cache & Download

#### Stories

##### Story 03.2-001: Cache directory and `lig models list`
**User Story**: As FX, I want weights cached under `$XDG_CACHE_HOME/lig/models` (override `LIG_MODELS_DIR` or config), and `lig models list` showing each artifact's installed/missing state, size, license and the total disk used and free, so that I know what I have before I pull anything.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** no override **When** the cache path resolves **Then** it is `platformdirs.user_cache_dir("lig")/models` and is created on first use.
- **Given** `lig models list` **When** run **Then** a table shows name, role, engine set, size, license, status (`installed`, `missing`, `partial`, `unverified`) and a footer with cache size and free disk.
- **Given** `--engine sdcpp` **When** listing **Then** only that engine's set is shown.
- **Given** `--json` **When** listing **Then** the same data is emitted as JSON.

**Technical Notes**: `partial` means a `.part` file exists; `unverified` means the file exists but no `.sha256.ok` marker; verification writes the marker.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 03.1-001, 01.3-001
**Risk Level**: Low

##### Story 03.2-002: `lig models pull` with resume and verification
**User Story**: As FX, I want `lig models pull [NAME | --engine E]` to download artifacts with HTTP range resume, show progress, verify sha256 on completion, refuse to overwrite a verified file and print the disk estimate before starting, so that a 20 GB download interrupted at 90 % does not start over and a corrupt file never reaches an engine.
**Priority**: Must Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** a `.part` file **When** `pull` runs **Then** it resumes with a `Range` header and, if the server ignores the range, restarts from zero with a warning.
- **Given** a completed download **When** the sha256 mismatches **Then** the file is renamed `.corrupt`, the command exits 1 with the expected and actual hashes, and no marker is written.
- **Given** an artifact already verified **When** `pull` runs **Then** it is skipped with `already installed`; `--force` re-downloads.
- **Given** the set to download **When** `pull` starts **Then** it prints total bytes and free disk and refuses if free disk < total + 2 GB unless `--force`.
- **Given** the test suite **When** `pull` is tested **Then** a local fake HTTP server (in-process, loopback) serves fixture bytes; no public network.

**Technical Notes**: `httpx` streaming with a Rich progress bar; sha256 computed incrementally during download so a second pass over 20 GB is not needed. Only this command may open a socket; the socket guard fixture is disabled for its tests via the loopback allowance.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 03.2-001
**Risk Level**: Medium

##### Story 03.2-003: `lig models verify`, `rm` and `path`
**User Story**: As FX, I want `verify` to re-hash installed artifacts and exit non-zero on any mismatch, `rm` to delete an artifact after confirmation, and `path` to print an artifact's absolute path, so that I can audit, clean up and script around the cache.
**Priority**: Must Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** a tampered file **When** `lig models verify` runs **Then** it reports the mismatch, removes the `.ok` marker and exits 1; healthy files print `ok`.
- **Given** `lig models rm NAME` **When** run interactively **Then** it asks for confirmation showing the size; `--yes` skips the prompt.
- **Given** `lig models path NAME` **When** the artifact is installed **Then** it prints the absolute path and exits 0; if missing, it prints nothing and exits 1.
- **Given** `rm` on an artifact needed by the configured default engine **When** run **Then** a warning says which engine becomes unavailable.

**Technical Notes**: Share the hashing helper with `pull`; hashing 20 GB is slow, so `verify` shows a progress bar.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 03.2-001
**Risk Level**: Low

### Feature 03.3: Safety

#### Stories

##### Story 03.3-001: Pre-flight memory estimate and refusal
**User Story**: As FX, I want `lig` to estimate peak memory from the artifact sizes plus a per-engine overhead factor and refuse to start a run that exceeds available RAM, with `--force` to override, so that a 25 GB run on a 30 GB laptop with a browser open fails in 1 second instead of swapping for 10 minutes.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** an engine set and a size **When** the estimate runs **Then** it returns `sum(artifact sizes loaded into memory) × engine_factor + activation_estimate(size)` using constants stored in the registry per engine.
- **Given** available memory (from `/proc/meminfo` MemAvailable on Linux, `vm_stat` on macOS, injected in tests) **When** the estimate exceeds it **Then** the CLI prints the estimate, the available figure, hints (close apps, smaller size, offload flag) and exits 3.
- **Given** `--force` **When** set **Then** the run proceeds with a warning line.
- **Given** the Phase 0 measured peak RSS **When** the engine factor is calibrated **Then** the estimate for the spike configuration is within 20 % of the measured figure.

**Technical Notes**: Text-encoder offload changes the split between GPU and system memory but on an iGPU it is all one pool; keep the estimate as total system memory.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 03.1-002, 01.3-002
**Risk Level**: Low

## Sprint Breakdown
| Sprint | Stories | Points | Status |
|---|---|---|---|
| 2 | 03.1-001, 03.2-001 | 6 | Not started |
| 3 | 03.1-002, 03.2-002, 03.2-003, 03.3-001 | 13 | Not started |

## Epic Progress
- [ ] 03.1-001 (3) · [ ] 03.1-002 (3) · [ ] 03.2-001 (3) · [ ] 03.2-002 (5) · [ ] 03.2-003 (2) · [ ] 03.3-001 (3)
- **Completed**: 0 / 19 points
