# Changelog

Sections are generated per release from conventional commits
(`python scripts/changelog.py X.Y.Z --since vPREV --write`).

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
