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

CLI tool with a pluggable backend interface: `generate`/`edit` commands resolve to
one backend (local MLX, local sd.cpp, or remote) chosen by config or flag. The
same engine code can be served over HTTP so one machine acts as the art
department for the others.

## Repository Structure

```
local-image-generator/
├── src/local_image_generator/
│   ├── cli/          # Typer commands (generate, edit, models, serve)
│   ├── backends/     # Backend protocol + mlx / sdcpp / remote implementations
│   ├── models/       # Registry, download, cache, checksum, quant selection
│   └── server/       # Optional HTTP daemon exposing a local backend
├── tests/
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

## Key Docs

<!-- Populated after /brainstorm and /generate-epics -->
- `PROJECT-SEED.md` — Project seed data for downstream skills
