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

## GitHub Operations — Use `gh` CLI (NOT MCP)

Always use `gh` CLI for all GitHub operations (issues, PRs, releases, API calls).

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
- Release = tag `vX.Y.Z` matching `pyproject.toml` version; install via
  `uv tool install`. No container image, no deployment target: the "deployment"
  is `lig serve` started by hand (or launchd/systemd later) on the Mac.

## Engines & Platforms

| Host | Engine (planned default) | Notes |
|---|---|---|
| `omarchy-xps13` (Arc 140V iGPU, 30 GB) | sd.cpp Vulkan or ncnn-vulkan, decided by Phase 0 bench | Vulkan ICD present; no oneAPI/Level Zero installed. |
| `macbook-pro-m3-max` | sd.cpp Metal (Phase 2) → mflux MLX `-q 8` (Phase 3) | Serves the XPS via `lig serve` over the tailnet. |
| `home-lab` (M1 Pro) | same as M3 Max | Always-on; secondary remote target. |

Sampling defaults: 40 steps, 1024×1024, PNG, sizes validated to multiples of 32.
Engine-specific guidance defaults live in the adapter (sd.cpp cfg 6.0 Euler;
mflux guidance 1.0). Weights are never committed (`models/`, `*.gguf`,
`*.safetensors` are gitignored).

## Key Docs

- `REQUIREMENTS.md` — PRD: P0/P1/P2 requirements, phases, DoD, risks
- `PROJECT-SEED.md` — Project seed data from `/project-init`
- `docs/bench/` — Per-host engine benchmarks (created in Phase 0)
<!-- Epics/stories populated after /generate-epics -->
