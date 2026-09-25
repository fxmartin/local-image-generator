# local-image-generator — Local image generation CLI for Qwen-Image-2.1

## Project Context

A command-line tool that generates images with Qwen-Image-2.1 entirely on the
developer's own machines, no cloud. It runs the model locally (Apple Silicon via
MLX, or GGUF quantizations via stable-diffusion.cpp on Linux/Intel iGPU), and can
also drive a remote engine exposed by another machine on the tailnet, e.g. the
M3 Max serving a lighter client on the XPS 13. Model management (download, cache,
verify, switch quantizations) is a first-class feature, not an afterthought.

## Tech Stack

- **Language**: Python 3.12+
- **Framework**: Typer (CLI), Rich (terminal output)
- **Runtime**: CPython, managed with `uv`
- **Inference backends**: MLX (macOS/Apple Silicon), stable-diffusion.cpp GGUF
  (cross-platform), remote HTTP engine (client to a daemon on another host)

## Architecture

CLI tool (`lig`) over a `Backend` protocol. Standalone engines are wrapped as
subprocesses (`sd-cli` from stable-diffusion.cpp, `qwenimage-ncnn-vulkan`);
Python-native engines run in-process (mflux on MLX). A `RemoteBackend` talks HTTP
to `lig serve`, a FastAPI daemon on another host. Every backend consumes the same
`GenerateRequest`/`EditRequest` and returns the same `ImageResult`. Weights come
from a curated registry (repo, filename, sha256, size, engine, role, license)
into one cache. Config precedence: flag > `LIG_*` env > `~/.config/lig/config.toml`
> defaults.

**Phasing** (see `REQUIREMENTS.md` §7): Phase 0 engine spike on the XPS → Phase 1
XPS local (P0) → Phase 2 remote to the M3 Max → Phase 3 MLX on the Macs.

## Repository Structure

```
local-image-generator/
├── src/lig/
│   ├── cli/          # Typer commands: generate, edit, seeds, bench, models, doctor, config, serve
│   ├── core/         # Request/result models, output naming, sidecar + PNG metadata
│   ├── backends/     # Backend protocol + sdcpp / ncnn / mlx / remote / fake
│   ├── models/       # Registry (YAML), downloader (resume + sha256), cache, disk report
│   └── server/       # FastAPI daemon exposing one local backend (Phase 2)
├── tests/            # Offline, weight-free; FakeBackend + stub engine binaries
├── docs/bench/       # Per-host benchmark reports (xps13.md, m3max.md)
├── REQUIREMENTS.md
├── CLAUDE.md
├── PROJECT-SEED.md
├── .sdlc-harness.yaml
└── .gitignore
```

## Preferred CLI Tools

Use these instead of their traditional counterparts. They're installed and expected.

| Instead of | Use | Why |
|------------|-----|-----|
| `find` | `fd` | Faster, respects `.gitignore` |
| `grep` (via Bash) | `rg` | ripgrep — faster, better defaults |
| `cat` | `bat` | Syntax highlighting, line numbers |
| `cd` | `zoxide` (`z`) | Jump to frecent directories |
| `jq` for JSON | `jq` | Installed for JSON processing |

## Source Control — GitLab is master, GitHub is a mirror

`origin` is the **local-ci-cd GitLab on `home-lab`**
(`http://home-lab.tailac3c7a.ts.net:8080/root/local-image-generator.git`).
Branches, merge requests and issues live there. `github`
(`https://github.com/fxmartin/local-image-generator`) is a named remote kept
only so the push mirror has somewhere to land.

- **Never push to `github`, and never merge on GitHub.** GitLab push-mirrors to
  it; anything committed on the GitHub side is divergent history that the next
  mirror run will fight with.
- **Always use the tailnet FQDN** `home-lab.tailac3c7a.ts.net`, never the bare
  `home-lab`: on the XPS the bare name also resolves to an unreachable global
  IPv6 via the `fritz.box` search domain, and `glab`/`git` then hang for ~2 min.
- Use `glab` for merge requests, issues and API calls. It is authenticated at
  the instance level (token in the OS keyring). `--hostname` will not take a
  `host:port`, so set `GITLAB_HOST=home-lab.tailac3c7a.ts.net:8080`.
- `gh` remains correct for reading the GitHub mirror, and for any *other* repo
  that still has GitHub as its master.
- The `sdlc` controller's GitHub PR flow is **not authoritative** here.
  `.sdlc-forge.yaml` points it at GitLab; issue numbers are GitLab iids.
- Mirror lag is up to five minutes and GitLab enforces a backoff between runs.
  A stale `github/main` is expected, not a fault.

## Testing Strategy

- TDD. Unit tests on `core/`, `models/`, `cli/` with ≥ 85 % line coverage; ruff clean.
- No test touches the network, needs weights, or needs a GPU. A `FakeBackend`
  emits a valid PNG; subprocess adapters are tested against stub `sd-cli` /
  `qwenimage-ncnn-vulkan` scripts that echo their argv and write a PNG.
- Engine correctness and speed are verified manually per host and recorded in
  `docs/bench/`; CI cannot run engines.
- Inject failures through seams (fake backends, injected errors), never via
  filesystem permissions: CI runs as root.

## CI/CD

- Local GitLab stack on `home-lab`: Linux/arm64 container, root, minimal pinned
  image, **no network**. `uv sync --frozen` from a vendored/cached wheel set;
  then `ruff check`, `pytest --cov`.
- Conventional commits enforced by commitlint (`feat` → minor, `fix` → patch).
- Commit format: no Node in the offline image, so the `commit-format` MR job runs the
  Python-only `scripts/commit_lint.py` (mirrors `.commitlintrc.json`, which stays the
  reference for a Node-equipped checkout). Merge commits and history before the MR are exempt.
- `CHANGELOG.md` sections are generated by `scripts/changelog.py X.Y.Z --since vPREV --write`.
- Version bump: `uv version X.Y.Z` (updates `pyproject.toml` and `uv.lock`; commit both), then
  `python scripts/release_check.py vX.Y.Z` exits 1 naming both values if tag, pyproject or
  `uv.lock` disagree. The `release-check` MR job enforces pyproject/`uv.lock` alignment.
- Release = tag `vX.Y.Z` matching `pyproject.toml` version; install via
  `uv tool install`. No container image, no deployment target: the "deployment"
  is `lig serve` started by hand (or launchd/systemd later) on the Mac.

## Engines & Platforms

| Host | Engine (planned default) | Notes |
|---|---|---|
| `omarchy-xps13` (Arc 140V iGPU, 30 GB) | Remote on the M3 Max by default; local fallback sd.cpp Vulkan at 768², 30 steps (398 s). ncnn, SYCL, torch XPU rejected in Phase 0 | Vulkan works (sd.cpp, the only working engine). oneAPI + Level Zero installed, but SYCL is rejected: the driver under-reports free memory. |
| `macbook-pro-m3-max` | sd.cpp Metal (Phase 2) → mflux MLX `-q 8` (Phase 3) | Serves the XPS via `lig serve` over the tailnet. |
| `home-lab` (M1 Pro) | same as M3 Max | Always-on; secondary remote target. |

Sampling defaults: 40 steps, 1024×1024, PNG, sizes validated to multiples of 32;
Linux local runs default to 768×768, 30 steps (Story 02.1-004).
Engine-specific guidance defaults live in the adapter (guidance 1.0 for all engines,
Euler for sd.cpp; cfg 6.0 doubled sd.cpp's time on the XPS). Weights are never committed (`models/`, `*.gguf`,
`*.safetensors` are gitignored).

## Story Management Protocol

### Single Source of Truth
The `docs/stories/` directory and its epic files are the **single source of truth** for all story definitions, progress tracking, and acceptance criteria.

### Story File Hierarchy
```
docs/STORIES.md (overview and navigation)
└── docs/stories/
    ├── epic-01-foundation.md
    ├── epic-02-xps-engines.md
    ├── epic-03-model-management.md
    ├── epic-04-generation-commands.md
    ├── epic-05-release-docs.md
    ├── epic-06-remote-serving.md
    ├── epic-07-mlx-apple-silicon.md
    ├── epic-08-polish.md
    └── non-functional-requirements.md
```

### Progress Update Protocol
1. Update story completion checkboxes in epic files
2. Update sprint breakdown tables in each epic
3. Mark completed acceptance criteria
4. Update dependency tracking
5. Track completed story points in epic progress sections

### Development Workflow
- **Sprint Planning**: Use epic files for story selection
- **Code Reviews**: Link PRs to story IDs (e.g., "Implements Story 01.2-001")
- **Deployment**: Update story status in epic files post-deployment
- **Updates**: Maintain within 24 hours of story completion
- **Phase gate**: Story 02.1-004 (XPS bench decision) must close before any Epic-04 story that depends on a real engine starts

## Key Docs

- `REQUIREMENTS.md` — PRD: P0/P1/P2 requirements, phases, DoD, risks
- `docs/STORIES.md` — Epic overview, MVP scope, dependencies, sprint plan
- `docs/stories/` — Epic files with stories and acceptance criteria (source of truth)
- `PROJECT-SEED.md` — Project seed data from `/project-init`
- `docs/bench/` — Per-host engine benchmarks (created in Phase 0)
