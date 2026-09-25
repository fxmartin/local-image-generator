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

## Benchmarking

```
lig bench [--engines sdcpp,ncnn] [--size 768x768] [--steps 30] [--runs 3]
lig bench compare bench/A.json bench/B.json   # same host only; prints a delta table
lig bench render bench/<date>_<host>.json     # Markdown table for docs/bench/
```

`lig bench` runs a fixed prompt and seed on each engine, prints load s, s/step, total s,
peak RSS and the image hash, and writes `bench/<date>_<host>.json` (all runs kept, median
reported). Unavailable engines are listed as skipped with the reason.

## Development

```
uv sync            # install runtime + dev dependencies
uv run lig --help  # list subcommands (`seeds` is still a stub)
uv run ruff check .
uv run pytest      # coverage gate: 85 % on core, models, cli
```

Optional extras: `lig[serve]` (FastAPI daemon), `lig[mlx]` (mflux on Apple Silicon).

## Configuration

Settings resolve in this order: command-line flag > `LIG_*` environment variable >
`~/.config/lig/config.toml` (platform config dir) > built-in default. Nested keys use `__` in
env vars, e.g. `LIG_SERVE__BIND`.

- `lig config show` prints every effective value, which layer it came from
  (`flag`, `env`, `file` or `default`) and the config file path used.
- `lig config init` writes a commented `config.toml`; it refuses if one already exists.
- Unknown keys in the file produce a warning naming the key and line; the run continues.
- `engines.sdcpp.extra_args` (list of strings; env `LIG_ENGINES__SDCPP__EXTRA_ARGS`, split
  shell-style) is appended verbatim to the `sd-cli` command line, e.g.
  `["--model-args", "qwen_image_2_1_prefix_cache=false"]`.
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

The shipped registry seeds three sets: `sdcpp-q4` (default: Q4_K transformer, Qwen3-VL-8B Q4_K_M
text encoder, 2.1 VAE, mmproj), `sdcpp-q8` (Q8_0 transformer instead; opt-in alternative) and
`ncnn-bf16` (the ~31 GB BF16 model folder, stored under `qwenimage21/` in the cache). Each
entry records its license and the engine build it was measured with (`pinned_engine`). The
transformer, VAE and ncnn files are under the Qwen Research License (research/evaluation use
only), not Apache-2.0. The 2.1 VAE is not interchangeable with earlier Qwen-Image VAEs.

Keys: `engine`, `output_dir`, `models_dir`, `default_host`, `ncnn_binary`, `ncnn_model_dir`, `steps`, `size`, `serve.bind`.
The `ncnn` engine needs `ncnn_binary` (or `qwenimage-ncnn-vulkan` on `PATH`) and `ncnn_model_dir` (the `qwenimage21/` folder); it prints no per-step progress, so expect a spinner with elapsed time.

## Editing

`lig edit IMAGE PROMPT [--size WxH] [--steps N] [--seed S] [--engine E] [--strength 0..1] [--out DIR] [--force]`
applies an instruction edit ("make the teapot blue") to an existing image and writes a new PNG plus
sidecar; the sidecar records the source's `source_path` and `source_sha256`. With no `--size`, the
output is the source size rounded down to multiples of 32, and the command says so. Exit 4 if the
engine cannot edit (e.g. the sdcpp `mmproj` weight is missing), 2 if IMAGE is not a readable image.

## Generating

`lig generate PROMPT [--size WxH] [--steps N] [--seed S] [--engine E] [--out DIR] [--negative TEXT] [--guidance G] [--force] [--quiet]`
writes a PNG and a JSON sidecar to `./outputs` (or `--out` / `output_dir`) and prints the PNG path
as its last line. Flags override `LIG_*` env, which overrides `config.toml`. On Linux, with no
`--size`/`--steps` flag or config value, it uses 768x768 and 30 steps (the XPS local fallback).
`--engine fake` renders a seeded gradient without weights.

Progress goes to stderr: on a terminal, a bar with `step 12/40`, elapsed and ETA (a spinner with
elapsed time for `ncnn`, which reports no steps), then load and total times. When stdout is not a
TTY or `NO_COLOR` is set, it prints plain lines at most once per 10 % with no ANSI codes.
`--quiet`/`-q` suppresses progress and prints only the final path.

Exit codes: 0 ok, 1 engine error, 2 usage (bad size, unknown engine, invalid config), 3 memory
pre-flight refusal (`--force` overrides), 4 engine unavailable (the message carries the reason;
run `lig doctor`). A negative prompt does nothing at guidance 1, so `lig` warns and suggests `--guidance`.

## Comparing seeds

`lig seeds PROMPT [--count N] [--seed-start S]` (plus the `generate` flags except `--seed`) renders
N images (default 4, max 8) one after another with consecutive seeds, so you can compare
compositions before a long render. Each PNG and sidecar carries the same `batch_id`. Without
`--seed-start` a random start is chosen and printed as `seed start: S`. If a seed fails, the images
already written are kept, the error names the seed, and the exit code is 1. `--count` outside 1-8
exits 2.

Unless `--no-sheet` is given, the run also writes `<batch_id>_sheet.png`: a near-square grid of
the renders (2×2 for 4, 3×3 for up to 8), each tile downscaled to 512 px on its long edge and
labelled with its seed. Its `.json` sidecar lists the member files and seeds.

## Diagnostics

`lig doctor` prints platform facts (OS, arch, Vulkan ICD, Metal, oneAPI, RAM total/available,
models dir, disk free) and a table of every known engine with `available` or
`unavailable: <reason>` plus the weights cached for it. `lig doctor --json` emits the same data
for scripting.
