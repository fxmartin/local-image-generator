# Changelog

Sections are generated per release from conventional commits
(`python scripts/changelog.py X.Y.Z --since vPREV --write`).

## [0.3.1] - 2026-09-28

### Bug fixes

- **mlx:** pin model calls to one thread for lig serve

## [0.3.0] - 2026-09-28

### Features

- **mlx-apple-silicon:** default to mlx on apple silicon (#07.1-003)
- **mlx-apple-silicon:** mlx edit support (#07.1-002)
- **mlx-apple-silicon:** mflux `qwenimage21` in-process (#07.1-001)
- **photo-series:** review the plan before rendering (#09.2-003)
- **photo-series:** reusable characters across series (#09.3-003)
- **photo-series:** `lig-series` entry point and docs (#09.4-001)
- **photo-series:** series contact sheet (#09.2-004)
- **photo-series:** series manifest (#09.2-002)
- **photo-series:** series runner calling `lig generate` (#09.2-001)
- **photo-series:** deterministic prompt composition (#09.1-003)
- **photo-series:** per-shot scene (one `gemma` call per (#09.1-004)
- **photo-series:** global series settings (first `gemma` (#09.1-002)
- **photo-series:** gemma client (#09.1-001)

### Bug fixes

- **mlx-apple-silicon:** mlx edit support (#07.1-002)
- **mlx-apple-silicon:** mflux `qwenimage21` in-process (#07.1-001)
- **mlx-apple-silicon:** `lig models pull --for engine` (#07.2-002)
- **mlx-apple-silicon:** `--transparent` rgba output (#07.2-001)
- **photo-series:** label sheet tiles with each shot's title
- **photo-series:** reusable characters across series (#09.3-003)
- **photo-series:** pass sheet parameter to _render_plan

## [0.2.0] - 2026-09-26

### Features

- **remote-serving:** remote overhead measured and (#06.3-002)
- **remote-serving:** `remotebackend` and `--host` (#06.3-001)
- **remote-serving:** tailnet-only bind by default (#06.2-005)
- **remote-serving:** progress streaming over sse (#06.2-003)
- **remote-serving:** idle-unload ttl (#06.2-004)
- **remote-serving:** `post /v1/generate` and `post (#06.2-002)
- **remote-serving:** stable-diffusion.cpp metal on the m3 (#06.1-001)
- **remote-serving:** `lig serve` skeleton with health and (#06.2-001)

### Bug fixes

- **remote-serving:** use the serve port 7860 in config examples
- **remote-serving:** correct four remote bench defects

## [0.1.0] - 2026-09-26

### Features

- **release-docs:** conventional commits, changelog and (#05.1-002)
- **foundation:** offline ci pipeline on the local gitlab (#01.1-002)
- **release-docs:** readme with install, engine setup and (#05.1-001)
- **generation-commands:** contact sheet with seed labels (#04.3-002)
- **generation-commands:** `lig bench` engine comparison (#04.4-001)
- **generation-commands:** `lig seeds prompt --count n` (#04.3-001)
- **generation-commands:** `lig edit image prompt` (#04.2-001)
- **generation-commands:** rich progress output (#04.1-002)
- **generation-commands:** `lig generate` end to end (#04.1-001)
- **model-management:** pre-flight memory estimate and (#03.3-001)
- **model-management:** seed the registry with the (#03.1-002)
- **xps-engines:** qwenimage-ncnn-vulkan backend adapter (#02.2-003)
- **xps-engines:** stable-diffusion.cpp backend adapter (#02.2-002)
- **model-management:** `lig models verify`, `rm` and `path` (#03.2-003)
- **model-management:** `lig models pull` with resume and (#03.2-002)
- **model-management:** cache directory and `lig models (#03.2-001)
- **xps-engines:** generic subprocess engine runner (#02.2-001)
- **foundation:** `lig doctor` platform and engine (#01.3-002)
- **foundation:** engine log capture and friendly error (#01.3-003)
- **release-docs:** `uv tool install` packaging validated (#05.1-003)
- **model-management:** registry schema and loader (#03.1-001)
- **foundation:** layered configuration with provenance (#01.3-001)
- **foundation:** deterministic output naming with sidecar (#01.2-003)
- **foundation:** backend protocol and fakebackend (#01.2-002)
- **xps-engines:** stub engine binaries for the test suite (#02.2-004)
- **foundation:** request and result models with size (#01.2-001)
- **foundation:** project scaffold with uv, typer and (#01.1-001)

### Bug fixes

- **xps-engines:** measure sd.cpp load time to the first step
- **generation:** show step progress during lig edit
- **model-management:** count the gpu page pool as available memory
- **xps-engines:** ignore sd.cpp tensor-loading bars in progress
- **foundation:** count cached weights in the flat models dir
- **foundation:** let the socket guard allow loopback (#01.1-002)
- **foundation:** offline ci pipeline on the local gitlab (#01.1-002)
- **foundation:** layered configuration with provenance (#01.3-001)
- **foundation:** project scaffold with uv, typer and (#01.1-001)
