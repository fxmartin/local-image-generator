# local-image-generator (`lig`)

A CLI that generates and edits images with [Qwen-Image-2.1](https://huggingface.co/Qwen/Qwen-Image-2.1) on your own machines. No cloud. Runs locally (stable-diffusion.cpp on Vulkan/Metal, `qwenimage-ncnn-vulkan`, MLX on Apple Silicon) or against a remote engine served by another of your hosts over the tailnet.

## Inspiration

This project started from Hao Yu's article
[Qwen-Image-2.1 Turned My Two Little Computers Into an Art Department. No Cloud Required.](https://medium.com/generative-ai/qwen-image-2-1-turned-my-two-little-computers-into-an-art-department-no-cloud-required-29494e26f340)
(Medium, September 2026): one box generates, another calls it as a tool, everything stays on the desk.

## Status

Pre-alpha. Phase 0 (engine benchmark on the Dell XPS 13) has not started. See:

- [`REQUIREMENTS.md`](./REQUIREMENTS.md) — product requirements, phases, definition of done
- [`docs/STORIES.md`](./docs/STORIES.md) — epics, stories, sprint plan
- [`CLAUDE.md`](./CLAUDE.md) — architecture, stack, engineering conventions

Installation and usage docs land with story 05.1-001.

## Install

```
uv tool install .                # from a checkout; puts `lig` on PATH
uv tool install ".[serve]"       # adds FastAPI/uvicorn for `lig serve`
uv tool install ".[mlx]"         # adds mflux (Apple Silicon only)
lig --version
```

Without the `serve` extra, `lig serve` exits with a one-line hint to install it.

## Development

```
uv sync            # install runtime + dev dependencies
uv run lig --help  # list subcommands (all stubs for now)
uv run ruff check .
uv run ruff format --check .
uv run pytest      # coverage gate: 85 % on core, models, cli
```

CI (`.gitlab-ci.yml`) runs the same three checks in an offline, root, Linux/arm64
container with `uv sync --frozen` from the executor's project uv cache volume
(re-warm it on home-lab after any `uv.lock` change; recipe in `.gitlab-ci.yml`).
Tests therefore:

- cannot reach non-loopback addresses (an autouse guard in `tests/conftest.py` raises;
  in-process loopback servers are fine; opt out with `@pytest.mark.network`, unused in v1);
- must not rely on filesystem permissions, which no-op as root. If unavoidable, mark
  the test `@requires_non_root` (skips with an explicit `euid == 0` reason).

Optional extras: `lig[serve]` (FastAPI daemon), `lig[mlx]` (mflux on Apple Silicon).

## Configuration

Settings resolve in this order: command-line flag > `LIG_*` environment variable >
`~/.config/lig/config.toml` (platform config dir) > built-in default. Nested keys use `__` in
env vars, e.g. `LIG_SERVE__BIND`.

- `lig config show` prints every effective value, which layer it came from
  (`flag`, `env`, `file` or `default`) and the config file path used.
- `lig config init` writes a commented `config.toml`; it refuses if one already exists.
- Unknown keys in the file produce a warning naming the key and line; the run continues.
- `output_dir` and `models_dir` expand a leading `~` to your home directory.

Model weights are cached under the platform cache dir (`~/.cache/lig/models` on Linux);
override with `LIG_MODELS_DIR` or `models_dir`. The directory is created on first use.

`lig models list [--engine sdcpp] [--json]` shows each artifact's name, role, engines, size,
license and status (`installed`, `missing`, `partial` = a `.part` file exists, `unverified` =
present without a `.sha256.ok` marker), plus total cache size and free disk.

`lig models pull [NAME | --engine E] [--force]` downloads weights into the cache. It prints the
total bytes to fetch and the free disk first, and refuses if free disk is under total + 2 GB
(`--force` overrides). Interrupted downloads resume from the `.part` file with an HTTP `Range`
request (a server that ignores it triggers a warning and a restart from zero). The sha256 is
checked on completion: a mismatch renames the file `.corrupt`, prints expected and actual
hashes, exits 1 and writes no marker. Verified artifacts are skipped as `already installed`;
`--force` re-downloads them.

`lig models verify [NAME]` re-hashes installed artifacts (all of them by default) with a progress
bar. Healthy files print `NAME: ok`; a mismatch is reported, its `.sha256.ok` marker removed
and the command exits 1. `lig models rm NAME [--yes]` deletes the artifact and any `.part` /
`.corrupt` leftovers after a confirmation showing the size, and warns first if the configured
default engine needs it. `lig models path NAME` prints the absolute path of an installed
artifact; if it is not installed it prints nothing and exits 1.

Keys: `engine`, `output_dir`, `models_dir`, `default_host`, `steps`, `size`, `serve.bind`.

## Diagnostics

`lig doctor` prints platform facts (OS, arch, Vulkan ICD, Metal, oneAPI, RAM total/available,
models dir, disk free) and a table of every known engine with `available` or
`unavailable: <reason>` plus the weights cached for it. `lig doctor --json` emits the same data
for scripting.
