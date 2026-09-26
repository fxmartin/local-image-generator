# local-image-generator (`lig`)

A CLI that generates and edits images with
[Qwen-Image-2.1](https://huggingface.co/Qwen/Qwen-Image-2.1) on your own machines. No cloud.
It runs locally (stable-diffusion.cpp on Vulkan/Metal, `qwenimage-ncnn-vulkan`) or drives a
remote engine served by another of your hosts over the tailnet.

Inspired by Hao Yu's
[Qwen-Image-2.1 Turned My Two Little Computers Into an Art Department](https://medium.com/generative-ai/qwen-image-2-1-turned-my-two-little-computers-into-an-art-department-no-cloud-required-29494e26f340).

Status: pre-alpha. Local engines work; MLX and generating through `lig serve` are later phases. Design docs:
[`REQUIREMENTS.md`](./REQUIREMENTS.md), [`docs/STORIES.md`](./docs/STORIES.md),
[`CLAUDE.md`](./CLAUDE.md). Full flag and config reference: [`docs/reference.md`](./docs/reference.md).

## 1. Install `lig`

Needs [uv](https://docs.astral.sh/uv/) and Python 3.12+. From a checkout:

```sh
uv tool install .              # puts `lig` on PATH
uv tool install ".[serve]"     # adds FastAPI/uvicorn for `lig serve`
lig --version
```

Nothing works yet without an engine (section 2) and weights (section 3), but
`lig generate "a fox" --engine fake` renders a gradient with neither: a quick sanity check.

## 2. Install an engine

`lig` shells out to the engine binary, so it must be on `PATH` (or configured). Run
`lig doctor` after each install. Weights are pinned per engine in the registry; the
engine pin below is the build they were measured with.

### stable-diffusion.cpp, Vulkan (Linux, the XPS)

Pinned commit `b167b942f77ecb17e7f78e163a8c32ff7ac95c10` (`master-913-b167b94`). On Arch:

```sh
sudo pacman -S --needed git cmake ninja vulkan-headers spirv-headers shaderc vulkan-icd-loader
git clone https://github.com/leejet/stable-diffusion.cpp
cd stable-diffusion.cpp
git checkout b167b942f77ecb17e7f78e163a8c32ff7ac95c10
git submodule update --init --recursive
cmake -B build -G Ninja -DSD_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
install -Dm755 build/bin/sd-cli ~/.local/bin/sd-cli
```

Expected `lig doctor` row once weights are pulled (section 3):

```
sdcpp   4 file(s), <size> GiB   available
```

Before the pull it reads `unavailable: qwen-image-2.1-q4-transformer not installed`; with
no binary, `unavailable: sd-cli not found on PATH`.

### stable-diffusion.cpp, Metal (macOS, Apple Silicon)

Same pin, Metal backend:

```sh
brew install cmake ninja      # or provided by your nix-darwin config
git clone https://github.com/leejet/stable-diffusion.cpp
cd stable-diffusion.cpp
git checkout b167b942f77ecb17e7f78e163a8c32ff7ac95c10
git submodule update --init --recursive
cmake -B build -G Ninja -DSD_METAL=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
install -Dm755 build/bin/sd-cli ~/.local/bin/sd-cli
```

Built with `cmake` and `ninja` from Homebrew, or from your nix-darwin toolchain if it provides
them. Expected `lig doctor` row: `sdcpp ... available`, and `Metal  yes` in the platform table.
Then `lig generate "a fox"` renders 1024x1024 by default. Record timings with
`lig bench --engines sdcpp`; they land in `docs/bench/m3max.md`. sd.cpp's Metal path is known
to be slow on large matrices, so correctness, not speed, is the bar for this engine.

### qwenimage-ncnn-vulkan (Linux, release binary)

Pinned release [`20260924`](https://github.com/nihui/qwenimage-ncnn-vulkan/releases/tag/20260924).
No build step. Note: it does not start on the XPS (Vulkan memory budget, see
[`docs/bench/xps13.md`](./docs/bench/xps13.md)); use it on hosts with more GPU memory.

```sh
curl -LO https://github.com/nihui/qwenimage-ncnn-vulkan/releases/download/20260924/qwenimage-ncnn-vulkan-20260924-linux.zip
echo "1278d9fdaeb615c7dca6c37212a3d92e36d9834c9f1f35661e2ec11bfc56c8f5  qwenimage-ncnn-vulkan-20260924-linux.zip" | sha256sum -c
unzip qwenimage-ncnn-vulkan-20260924-linux.zip
install -Dm755 qwenimage-ncnn-vulkan-20260924-linux/qwenimage-ncnn-vulkan ~/.local/bin/qwenimage-ncnn-vulkan
```

Its ~31 GB model folder is pulled with `lig models pull --engine ncnn`; point `lig` at it with
`ncnn_model_dir` (or `LIG_NCNN_MODEL_DIR`) set to the `qwenimage21/` folder inside your models
cache. Expected `lig doctor` row: `ncnn   ...   available`.

## 3. First run: pull weights

```sh
lig models list                    # what exists, sizes, licenses, cache size, free disk
lig models pull --engine sdcpp     # Q4_K transformer, Qwen3-VL text encoder, VAE, mmproj
lig doctor                         # the sdcpp row should now read `available`
```

Downloads resume after an interruption and are sha256-verified. Weights land in
`~/.cache/lig/models` (override with `LIG_MODELS_DIR`). The transformer, VAE and ncnn files
are under the Qwen Research License (research/evaluation use only).

## 4. The five commands

Every command that renders writes a PNG plus a JSON sidecar (seed, prompt, engine, timings)
to `./outputs` (or `--out DIR`) and prints the PNG path as its last line.
Exit codes shared by the rendering commands: **0** ok, **1** engine error, **2** usage error
(bad size, unknown engine, invalid config), **3** memory pre-flight refusal (`--force`
overrides), **4** engine unavailable (missing binary or weights; the message says which).

### `lig generate`

```sh
lig generate "a lovely cat holding a sign that says 'qwen'" --size 768x768 --steps 30 --seed 42
```

Defaults on Linux are 768x768, 30 steps; on macOS 1024x1024, 40 steps. Sizes are multiples of
32. `-q` prints only the path. Exit codes: 0, 1, 2, 3, 4.

### `lig edit`

```sh
lig edit outputs/cat.png "make the cat orange" --strength 0.8
```

Needs the `mmproj` weight (pulled with the sdcpp set). Exit codes: 0, 1, 2 (unreadable image),
3, 4 (engine cannot edit).

### `lig seeds`

```sh
lig seeds "a lighthouse at dusk" --count 4 --seed-start 100 --size 512x512
```

Renders `--count` images (default 4, max 8) with consecutive seeds and a labelled contact
sheet (`--no-sheet` to skip). Exit codes: 0, 1 (a seed failed; earlier images are kept),
2 (`--count` outside 1-8), 3, 4.

### `lig bench`

```sh
lig bench --engines sdcpp --size 768x768 --steps 30 --runs 3
lig bench render bench/<file>.json     # Markdown table for docs/bench/
```

Fixed prompt and seed per engine; prints load time, s/step, total and peak RSS, and writes
`bench/<date>_<host>.json`. Exit codes: 0, 2 (bad `--runs`, size or engine), 4 (no engine ran),
1 (`compare`/`render` cannot read their input).

### `lig models`

```sh
lig models list
lig models pull --engine sdcpp     # or: lig models pull qwen-image-2.1-q8-transformer
lig models verify                  # re-hash everything installed
lig models rm qwen-image-2.1-q8-transformer --yes
lig models path qwen-image-2.1-vae
```

Exit codes: 0 ok; 1 on a sha256 mismatch, a failed or refused download (not enough disk), or
`path` for an artifact that is not installed; 2 if `pull` gets neither or both of NAME and
`--engine`.

### Also: `lig doctor`, `lig config`, `lig serve`

`lig doctor [--json]` reports platform facts and one row per engine.
`lig config show|init` prints effective settings or writes a commented `config.toml`.
Settings resolve as flag > `LIG_*` env > `~/.config/lig/config.toml` > defaults.
`lig serve [--engine E] [--bind HOST:PORT]` starts a daemon (default bind `serve.bind`,
`127.0.0.1:8765`) wrapping one local engine. It needs the `serve` extra (exit 2 with an install
hint otherwise). `GET /v1/health` returns engine, engine version, weights, `loaded`, host,
`lig` version and uptime; `GET /v1/models` returns the artifact state for that engine.
Generation endpoints come with the remote client.

## Troubleshooting

- **Exit 3, "would not fit in memory".** The pre-flight estimate exceeds available RAM. Lower
  `--size` (e.g. `768x768`) or `--steps`, close other apps, or pass `--force` to try anyway.
- **Exit 4, weights or binary missing.** Run `lig doctor`; the engine row names the missing
  piece (`... not installed`, `sd-cli not found on PATH`). Fix with `lig models pull --engine
  sdcpp` or by installing the engine (section 2). `lig models verify` catches corrupt files.
- **Exit 1, engine failed.** `lig` prints the last lines of the engine output and the path of the
  full log. Add `-v` to echo engine output live, or `--debug` for the Python traceback.
- **Where logs are.** One timestamped file per run under the platform state dir:
  `~/.local/state/lig/logs/` on Linux, `~/Library/Application Support/lig/logs/` on macOS
  (the newest 50 are kept).

## Development

```sh
uv sync                # runtime + dev dependencies
uv run ruff check .
uv run ruff format --check .
uv run pytest          # offline, no weights or GPU; coverage gate 85 %
```

Engines are never run in CI; per-host measurements live in [`docs/bench/`](./docs/bench/).

CI (`.gitlab-ci.yml`) runs the same checks in an offline, root, Linux/arm64
container: `uv sync --frozen` with `UV_OFFLINE=1`, from the project's uv cache on
the CI host. After any `uv.lock` change, re-warm that cache before pushing (recipe in
the `.gitlab-ci.yml` header), or the install step fails. Tests therefore:

- cannot open sockets (an autouse guard in `tests/conftest.py` raises; opt out with
  `@pytest.mark.network`, unused in v1);
- must not rely on filesystem permissions, which no-op as root. If unavoidable, mark
  the test `@requires_non_root` (skips with an explicit `euid == 0` reason).
