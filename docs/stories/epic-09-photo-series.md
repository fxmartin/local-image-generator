# Epic 9: Photo Series with Gemma

## Epic Overview
**Epic ID**: Epic-09
**Description**: `lig-series` is a small companion CLI. It takes one natural-language request, such as "Create 10 photos black and white of a woman in Paris", and works in two stages through the `gemma` command. That command is FX's `m3max-gemma` uv tool, which asks the M3 Max's local Gemma model over SSH.
1. **Global call.** One `gemma` call returns the series' global settings: count, character, style, setting and arc.
2. **Per-shot loop.** For each photo, one `gemma` call returns that shot's scene. Code composes the final prompt, and `lig generate` (or `lig edit`) renders it before the loop moves on. The same character must be recognisable across every photo of a series, and across later series that reuse the character.
**Business Value**: Makes `lig` usable for stories, slides and blog posts, which need several images of one character. Today that means writing N long prompts by hand and hoping the character looks the same in each.
**Success Metrics**: A single command produces the requested number of photos plus a contact sheet. FX judges the character to be the same person in every shot of a 3-shot series. A second series reusing the saved character passes the same check.
**Requirements**: New capability beyond REQUIREMENTS.md; overlaps Story 08.1-001 (optional prompt rewriter), which this epic can supersede for series use.

**Evidence (2026-09-26)**: Draft system prompts were tested through `gemma` against `gemma-4-26B-A4B-it-heretic` on the M3 Max.
- **Global call.** For "Create 10 photos black and white of a woman in Paris", it returned valid JSON in 6 s: `count` 10, a named character with a 42-word look, a black-and-white 35mm style, Paris as the setting, and a morning-to-midnight arc.
- **Per-shot calls.** Three calls took 3 to 4 s each. Each returned one valid `{title, scene}` that followed the arc (café in the morning, the Seine at dawn, Le Marais at midday), without repeating a location or pose and without restating the look.
- **An earlier single-call variant** also worked, returning all shots in one answer in 9 s. The two-stage flow was chosen for control per shot and for long series.
- **Cost.** Planning costs seconds per shot; rendering costs about 10 minutes per shot on the M3 Max.

**Design decisions** (assumptions, open to review):
- **Separate command.** `lig-series` is a separate console script in this repo, shipped in the same `uv tool install`. It calls `lig` as a subprocess, as asked, never through its Python API. Rendering therefore follows FX's `lig` config: remote to the M3 Max by default, and `--host`/`--engine` pass through.
- **Two-stage planning.** A global `gemma` call fixes what every photo shares. A per-shot `gemma` call writes only what differs: the scene. Each shot's call sees the scenes already used, so a series of 10 or 20 does not repeat itself.
- **Code writes the prompts.** Every final prompt is assembled deterministically, with the character's look text copied verbatim into each one. Continuity never depends on the model repeating itself.
- **Continuity has three layers:**
  - the same look text, style and seed in every shot (09.1-003, 09.2-001);
  - an optional anchor reference image, decided by a spike (09.3-001, 09.3-002);
  - saved characters, reused across series (09.3-003).

## Epic Scope
**Total Stories**: 13 | **Total Points**: 40 | **MVP Stories**: 9

## Features in This Epic

### Feature 09.1: Planning with Gemma

#### Stories

##### Story 09.1-001: Gemma client
**Status**: Done
**User Story**: As FX, I want `lig-series` to call the `gemma` command with a system instruction and my request on stdin, and get back only the model's answer, so that planning runs on the M3 Max's local model with no API keys and no cloud.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** `gemma` on PATH **When** the planner runs **Then** it executes `gemma --system SYS --temperature T --max-tokens N -` with the request on stdin, and returns stdout with surrounding whitespace removed.
- **Given** `--gemma PATH` or env `LIG_SERIES_GEMMA` **When** set **Then** that binary is used instead.
- **Given** `gemma` is not installed **When** `lig-series` runs **Then** it exits 4 with `gemma not found; install m3max-gemma or set --gemma`.
- **Given** `gemma` exits non-zero or times out (default 600 s, `--plan-timeout`) **When** planning **Then** `lig-series` exits 1, showing the last 20 lines of gemma's stderr.
- **Given** the test suite **When** it runs **Then** a stub `gemma` script in `tests/stubs/` stands in for the real one: it records its argv and stdin and replies with a fixture. No network and no SSH.

**Technical Notes**: Mirror the stub-binary pattern of Story 02.2-004. `gemma` starts the Mac's model server on demand (`--no-start` is not passed), so the first call can take longer; the timeout covers that.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: None
**Risk Level**: Low

##### Story 09.1-002: Global series settings (first `gemma` call)
**Status**: Done
**User Story**: As FX, I want one `gemma` call to turn my request into validated global settings (count, character, style, setting, arc), so that "Create 10 photos black and white of a woman in Paris" fixes once what all ten photos share.
**Priority**: Must Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** a request **When** the global call runs **Then** the answer validates against a pydantic `SeriesSettings` with these fields:
  - `count`, an integer from 1 to `--max-shots`;
  - `character`, with `name` and `look`: 25 to 80 words, visual identity only, never places or actions;
  - `style`: medium, colour, film, lens and light mood shared by every photo, e.g. "black and white, 35mm grain";
  - `setting`, the shared location;
  - `arc`, one sentence on how the series progresses.
- **Given** a request that names a number ("10 photos", "three images") **When** planned **Then** `count` equals it. `--count N` overrides it. `--max-shots` defaults to 20, and a count above it exits 2 before any image is rendered.
- **Given** an answer wrapped in code fences or preceded by prose **When** parsed **Then** the first JSON object is extracted and validated.
- **Given** invalid JSON or a schema violation **When** it happens **Then** the call is retried once with the validation error appended. A second failure exits 1 and saves the raw answer to `settings.invalid.txt` in the series directory.
- **Given** `--style TEXT` or `--setting TEXT` **When** set **Then** that field is fixed, and Gemma is told not to change it.

**Technical Notes**: Start from the global system prompt that passed the 2026-09-26 test (Epic Overview). Temperature 0.4 by default (`--temperature`). Keep the prompts in `lig_series/prompts.py`, with a unit test that pins the key rules: the look never mentions places or actions, and the style is shared.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 09.1-001
**Risk Level**: Medium

##### Story 09.1-003: Deterministic prompt composition
**Status**: Done
**User Story**: As FX, I want every shot's final prompt built by code from the global settings and that shot's scene, with the character's look copied word for word, so that the image model sees the same identity and style in every photo.
**Priority**: Must Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** `SeriesSettings` and a shot **When** its prompt is composed **Then** it is `"{look} {scene} Style: {style}"`. The `look` and `style` substrings are byte-identical across all shots.
- **Given** `--prefix TEXT` / `--suffix TEXT` **When** set **Then** they are added to every prompt unchanged, for fixed framing words such as "35mm photo".
- **Given** a composed prompt **When** it is written **Then** `plan.json` stores it next to its shot, so a re-render needs no LLM call.

**Technical Notes**: Pure function; unit-tested without `gemma` or `lig`. The setting is not repeated in the prompt: the per-shot scene already places the shot within it (09.1-004).

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 09.1-002, 09.1-004
**Risk Level**: Low

##### Story 09.1-004: Per-shot scene (one `gemma` call per photo)
**Status**: Done
**User Story**: As FX, I want each photo's scene written by its own `gemma` call that knows the series settings, its position in the series and the scenes already used, so that ten photos follow the arc without repeating a location or pose.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** the global settings **When** shot i of N is planned **Then** one `gemma` call receives:
  - the settings as JSON;
  - `Shot i of N`;
  - the titles and scenes of shots 1 to i−1.
  It returns a JSON `{title, scene}`, with a scene of 20 to 80 words.
- **Given** the per-shot system prompt **When** used **Then** it tells Gemma to give location within the setting, action, pose, framing, angle and light. It also says not to describe the character's appearance or the style, and not to repeat a location or pose already used.
- **Given** an invalid answer **When** it happens **Then** that shot's call is retried once with the error appended. A second failure stops the series with exit 1, keeping the shots already rendered.
- **Given** a series of N shots **When** planned **Then** exactly N per-shot calls are made after the one global call, and each is timed in `series.json`.

**Technical Notes**: Start from the per-shot system prompt that passed the 2026-09-26 test (Epic Overview). Temperature 0.7 by default (`--shot-temperature`): higher than the global call, for variety between shots. Only titles and scenes of earlier shots are passed, not their full prompts, which keeps the context small for 20-shot series.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 09.1-002
**Risk Level**: Medium

### Feature 09.2: Rendering a series

#### Stories

##### Story 09.2-001: Series runner calling `lig generate`
**Status**: Done
**User Story**: As FX, I want `lig-series "Create 10 photos black and white of a woman in Paris"` to run the global call, then loop over the shots (per-shot `gemma` call, compose the prompt, `lig generate`), printing each PNG path, so that one command produces the whole series with my usual `lig` settings.
**Priority**: Must Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** global settings with `count` N **When** the series runs **Then** a loop runs N times. Each pass makes that shot's `gemma` call (09.1-004), composes its prompt (09.1-003), then runs `lig generate PROMPT --seed S --out SERIES_DIR`. The next shot's `gemma` call starts only after the render finishes. `--size`, `--steps`, `--engine`, `--host`, `--negative` and `--guidance` pass through unchanged; unset flags fall back to `lig`'s own defaults.
- **Given** no `--seed` **When** rendering **Then** one random base seed is drawn and used for every shot, and recorded. Same character text plus same seed is the first continuity layer.
- **Given** a shot **When** `lig` finishes **Then** the PNG path is read from the last line of `lig`'s stdout. Progress stays visible on stderr, prefixed `[2/3 Repairing the lamp]`.
- **Given** a `lig` failure (non-zero exit) **When** it happens **Then** the series stops, keeping finished shots, and exits with `lig`'s code. `--keep-going` renders the remaining shots and exits 1 at the end.
- **Given** the default output **When** a series runs **Then** everything goes to `series/YYYYMMDD-HHMMSS_<slug>/` under the working directory (`--out` overrides).
- **Given** the test suite **When** it runs **Then** it drives the real `lig` with `--engine fake`, which needs no weights, plus the stub `gemma`. The integration test runs offline.

**Technical Notes**: `subprocess.run` with the argv as a list, never `shell=True`. Gemma and the image engine both run on the M3 Max: about 15 GB for Gemma plus about 10 GB peak for `sd-cli` fits in 48 GB, and the loop never runs them at the same moment. Rendering time is real: each 1024², 40-step shot takes about 10 min, so "10 photos" takes about 100 min. The README must say so, and must suggest `--size 768x768 --steps 30` for drafts. Never go below about 30 steps: fewer gives ghosted, doubled subjects (observed 2026-09-26).

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 09.1-003, 09.1-004
**Risk Level**: Medium

##### Story 09.2-002: Series manifest
**Status**: Done
**User Story**: As FX, I want each series directory to contain a `series.json` that ties together the request, the plan, every prompt and seed, and each image with its `lig` sidecar, so that I can reproduce or extend a series later.
**Priority**: Must Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** a finished series **When** `series.json` is read **Then** it contains the fields below and validates against a pydantic schema:
  - the original request, the `gemma` model reported by `gemma --status`, and the plan;
  - the continuity mode, the base seed, and `lig --version`;
  - one entry per shot: title, prompt, PNG path, sidecar path, `lig`'s exit code and wall time.
- **Given** a series stopped by a failure **When** `series.json` is written **Then** the failed and skipped shots are recorded with their status.

**Technical Notes**: Written after each shot, not only at the end, so an interrupted series can be resumed by 09.2-003.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 09.2-001
**Risk Level**: Low

##### Story 09.2-003: Review the plan before rendering
**Status**: Done
**User Story**: As FX, I want `--plan-only` to run the global call and all per-shot calls without rendering, and `--from-plan plan.json` to render a plan I have edited, so that I fix a weak scene before spending up to 100 minutes of GPU on it.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** `--plan-only` **When** run **Then** the global call and all N per-shot calls run. The plan is printed as a readable list: settings, then one line per shot with its final prompt. `plan.json` is written, and no `lig` process starts.
- **Given** `--from-plan FILE` **When** run **Then** `gemma` is not called. The plan is validated, the prompts are re-composed from its fields, and the series renders.
- **Given** `--from-plan` on an interrupted series directory **When** run with `--resume` **Then** only shots without an image are rendered.

**Technical Notes**: The `plan.json` format is the `SeriesSettings` from 09.1-002, the shots from 09.1-004, and the composed prompts from 09.1-003.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 09.2-002
**Risk Level**: Low

##### Story 09.2-004: Series contact sheet
**Status**: Done
**User Story**: As FX, I want a contact sheet of the series, labelled with each shot's title, so that I can judge the character's continuity at a glance.
**Priority**: Should Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** a finished series of 2 or more shots **When** it completes **Then** `sheet.png` is written: a near-square grid (4×3 for 10 shots) with 384 px tiles, each labelled with its shot number and title. `--no-sheet` skips it.
- **Given** a series with failed shots **When** the sheet is built **Then** only rendered shots appear.

**Technical Notes**: Pillow only, like `lig`'s seed sheet (Story 04.3-002); do not import `lig` internals.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 09.2-001
**Risk Level**: Low

### Feature 09.3: Character continuity

#### Stories

##### Story 09.3-001: Continuity spike: shared prompt vs anchor image
**User Story**: As FX, I want a measured comparison of the continuity strategies on one real 3-shot series, so that the default is chosen on evidence rather than guessed.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** a 3-shot request, e.g. "3 photos black and white of a woman in Paris" **When** the spike runs from the XPS against the M3 Max **Then** it renders the same plan in each of these modes:
  - (a) **prompt**: shared look text and shared seed;
  - (b) **anchor-edit**: shot 1 with `lig generate`, then shots 2 and 3 with `lig edit SHOT1.png "<look> <scene>"`;
  - (c) **anchor-portrait**: a neutral full-body reference portrait of the character first, then every shot as `lig edit PORTRAIT "Place this person in: <scene> …"`.
- **Given** the three results **When** recorded in `docs/bench/series-continuity.md` **Then** the page has a contact sheet per mode, the wall time per mode, and FX's verdict on two questions: same person, and does the scene change enough.
- **Given** the verdict **When** the spike closes **Then** the default mode for 09.3-002 is named. A mode that keeps the reference's background instead of building the new scene is rejected with the image as evidence.

**Technical Notes**: The known risk is that Qwen-Image-2.1's edit is instruction editing, built to change something in a picture. It may keep too much of the reference's composition for a new scene, which is exactly what this spike checks. Run it by hand, not through the sdlc controller: each mode is about 30 min at 1024² and 40 steps, over the controller's 1-hour agent limit for the whole spike. Use `--size 768x768 --steps 30` if time matters, and do it the same for every mode.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 09.2-001
**Risk Level**: High

##### Story 09.3-002: Anchor continuity mode
**User Story**: As FX, I want `--continuity prompt|anchor` with the spike's winner as the default, so that characters stay recognisable even when the scenes differ a lot.
**Priority**: Should Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** `--continuity anchor` **When** rendering **Then** the reference image chosen by 09.3-001 (first shot or portrait) is rendered first and saved as `reference.png`. Every later shot runs through `lig edit reference.png "<prompt>"` with the same seed and pass-through flags.
- **Given** `--continuity prompt` **When** rendering **Then** only 09.2-001's shared-text and shared-seed layer applies.
- **Given** an engine that cannot edit (`lig` exits 4 on `edit`) **When** anchor mode runs **Then** `lig-series` falls back to prompt mode, and says so once on stderr.
- **Given** anchor mode **When** `series.json` is written **Then** it records the reference image path and its sha256.

**Technical Notes**: If the spike rejects both anchor variants, this story shrinks to documenting prompt mode as the only mode (1 point) and 09.3-003 keeps the look text only.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 09.3-001
**Risk Level**: Medium

##### Story 09.3-003: Reusable characters across series
**Status**: Done
**User Story**: As FX, I want `--character NAME` to save the character's look, name and reference image the first time, and reuse them in every later series, so that the same person appears in all my series, not only within one.
**Priority**: Must Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** `--character elara` for a name not yet saved **When** a series finishes **Then** `~/.local/share/lig/characters/elara/` holds `character.json` (name, look, style, base seed, source series) and, in anchor mode, `reference.png`.
- **Given** a saved character **When** a new series runs with `--character elara` **Then** the global call receives the saved look as fixed input. The saved look replaces whatever look the model returns, and the saved reference and seed are reused.
- **Given** `lig-series characters list|show NAME|rm NAME` **When** run **Then** it lists, prints or deletes saved characters; `rm` asks for confirmation unless given `--yes`.
- **Given** the test suite **When** it runs **Then** the characters directory is a temp dir (`XDG_DATA_HOME`), never the real one.

**Technical Notes**: Path from `platformdirs.user_data_dir("lig")`. This is the "continuity across multiple series" requirement.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 09.2-002
**Risk Level**: Low

### Feature 09.4: Packaging and acceptance

#### Stories

##### Story 09.4-001: `lig-series` entry point and docs
**Status**: Done
**User Story**: As FX, I want `lig-series` installed by the same `uv tool install` as `lig`, with a README section and `--help`, so that it is one install on the XPS.
**Priority**: Must Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** `uv tool install .` **When** it finishes **Then** both `lig` and `lig-series` are on PATH, and `lig-series --help` lists every flag from this epic.
- **Given** the README **When** read **Then** a "Photo series" section shows:
  - one example request, `--plan-only` and `--from-plan`;
  - `--character`;
  - the expected time per shot on the M3 Max, and the 30-step minimum.
- **Given** `gemma` is missing **When** `lig-series --help` runs **Then** it still works: only running a plan needs `gemma`.

**Technical Notes**: `[project.scripts] lig-series = "lig_series.cli:app"`, a sibling package under `src/`. No new runtime dependency beyond what `lig` already has (typer, rich, pydantic, pillow).

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 09.2-001
**Risk Level**: Low

##### Story 09.4-002: Acceptance: two series, one character
**Status**: Done
**User Story**: As FX, I want a recorded run of two series with the same saved character, rendered from the XPS on the M3 Max, so that the epic closes on evidence.
**Priority**: Must Have
**Story Points**: 2

**Acceptance Criteria**:
- **Given** the XPS with `default_host = "m3max"` **When** FX runs `lig-series "Create 3 photos black and white of a woman in Paris" --character elara` and then `lig-series "2 photos of her at a flea market" --character elara` **Then** both succeed, each writes its images and contact sheet, and the second reuses the saved character.
- **Given** both contact sheets **When** FX reviews them **Then** the verdict (same person across all 5 photos: yes or no) and the wall times are recorded in `docs/bench/series-continuity.md`.

**Technical Notes**: Manual story, like 05.1-004. Expect about 50 min at 1024², 40 steps for 5 shots, or about 25 min at 768², 30 steps.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] User-facing docs updated in the same commit for behavior-changing diffs (README/docs/usage/help; CHANGELOG excluded — Epic-05 owns it)

**Dependencies**: 09.3-003, 09.4-001, 09.2-004
**Risk Level**: Medium

## Sprint Breakdown
| Sprint | Stories | Points | Status |
|---|---|---|---|
| 1 | 09.1-001, 09.1-002, 09.1-004, 09.1-003, 09.2-001, 09.4-001 | 20 | Not started |
| 2 | 09.2-002, 09.2-003, 09.2-004, 09.3-001 (hand-run) | 10 | Not started |
| 3 | 09.3-002, 09.3-003, 09.4-002 (hand-run) | 10 | Not started |

MVP (9 stories): 09.1-001, 09.1-002, 09.1-003, 09.1-004, 09.2-001, 09.2-002, 09.2-003, 09.3-003, 09.4-001.

## Epic Progress
- [ ] 09.1-001 (3) · [ ] 09.1-002 (5) · [ ] 09.1-003 (2) · [ ] 09.1-004 (3) · [ ] 09.2-001 (5) · [ ] 09.2-002 (2) · [ ] 09.2-003 (3) · [ ] 09.2-004 (2) · [ ] 09.3-001 (3) · [ ] 09.3-002 (5) · [ ] 09.3-003 (3) · [ ] 09.4-001 (2) · [ ] 09.4-002 (2)
- **Completed**: 0 / 40 points
