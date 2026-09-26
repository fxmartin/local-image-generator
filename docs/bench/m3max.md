# M3 Max engine bench

Host `macbook-pro-m3-max`: MacBook Pro M3 Max, Apple Silicon, Metal. Numbers here are
recorded by hand; CI cannot run engines. Exit criterion for Story 06.1-001 is correctness,
not speed: sd.cpp's Metal backend is known to perform poorly on large matrices, and slow
timings are recorded as such rather than treated as a failure.

## Build

- Engine: stable-diffusion.cpp at the pinned commit `b167b942f77ecb17e7f78e163a8c32ff7ac95c10`,
  `-DSD_METAL=ON -DCMAKE_BUILD_TYPE=Release`.
- Toolchain: `cmake` + `ninja` (Homebrew, or the nix-darwin toolchain if it provides them).
  Record which one was used in the first row below.
- Verify: `lig doctor` shows `sdcpp: available` and `Metal  yes`; `lig generate` at 1024²
  produces a PNG.

## Runs

Produced with `lig bench --engines sdcpp` (see `docs/bench/xps13.md` for the format).

| Engine | Setting | Result | Total | Notes |
|---|---|---|---|---|
| sd.cpp Metal | 1024², 40 steps, cfg 1.0 | **pass** | **615.2 s** | 2026-09-26, `lig bench`: load 21.7 s, 14.84 s/step, peak RSS 10.1 GB, image `6a78d4b00424…` |

Recorded 2026-09-26 on `macbook-pro-m3-max` (48 GB; `platform.node()` reports
`fxmartins-MacBook-Pro`, which is the host name in the JSON files), `lig` 0.1.0 at
`ff9112d`:

- **Toolchain**: `cmake` and `ninja` from a throwaway `nix shell nixpkgs#cmake nixpkgs#ninja`
  (neither is in the nix-darwin config; nothing was installed with Homebrew). Build took
  under 2 minutes.
- **Engine**: sd.cpp `b167b942f77ecb17e7f78e163a8c32ff7ac95c10`, `-DSD_METAL=ON`, Metal
  backend on `MTL0 (Apple M3 Max)`, GPU at 99 % during sampling.
- **`lig doctor`**: `Metal  yes`, `sdcpp   4 file(s), 10.3 GiB  available`.
- **`lig generate "a lovely cat holding a sign that says qwen" --seed 42`** (macOS defaults,
  1024², 40 steps): PNG written, 625.3 s (load 27.1 s). The sign reads `qwen` followed by an
  extra invented word; the prompt lost its quotes around `qwen` in the shell script, and the
  quoted form is what anchors sign text (the XPS runs used it).

Metal is slow for this model, as expected: 14.8 s/step at 1024² is only about 2× the XPS's
Vulkan iGPU (28.6 s/step) and roughly 10× the ~1.5 s/step published for MLX on Apple
Silicon. Speed on the Mac is Epic-07's job.

## Remote overhead (Story 06.3-002)

Overhead = the XPS's wall clock for one remote run (`lig bench --host m3max`, includes the
request, the SSE stream and the PNG transfer) minus the Mac's own total for **that same run**.
Target: ≤ 10 s. `lig bench overhead` also prints the gap to a separate local bench on the Mac;
that gap is run-to-run engine variance, not overhead (issue #59).

```sh
# on the M3 Max
lig bench --engines sdcpp --size 1024x1024 --steps 40
# on the XPS, with `lig serve` running on the Mac
lig bench --host m3max            # remote runs default to 1024², 40 steps
lig bench overhead m3max-local.json xps-remote.json   # prints the line to paste below
```

The remote JSON records `client_host` and `server_host`.

| Date | Client → server | Local total | Remote wall | Overhead | Result |
|---|---|---|---|---|---|
| 2026-09-26 | omarchy-xps13 → m3max | 615.17 s (separate run) | 661.81 s (server total 661.51 s) | **+0.30 s** | **PASS** |

```
Remote overhead omarchy-xps13 -> fxmartins-MacBook-Pro: 661.81 s wall - 661.51 s on the server = +0.30 s (limit 10 s): PASS
Server run vs local bench: 661.51 s - 615.17 s = +46.34 s (engine variance between runs, not overhead)
```

The remote run rendered the same image as the local bench (`6a78d4b00424…`), so the
server path changes nothing about the output. In that run the Mac sampled at 16.0 s/step
against 14.8 s/step in its local bench; that difference, not the network, is the +46 s.

Setup: `uv tool install ".[serve]"` and `lig serve --engine sdcpp` on the Mac, which bound
its tailnet address `100.84.13.82:7860` by default (Story 06.2-005). On the XPS a
`[hosts]` entry `m3max = "http://100.84.13.82:7860"` in `config.toml`; `lig doctor` then
listed `m3max  http://100.84.13.82:7860  reachable  sdcpp`.

The first remote bench exposed four defects, fixed in MR !45 before this record: remote
benches used the Linux local defaults of 768², 30 steps (#56; that run took 259.6 s at
8.18 s/step), recorded the client's build `vulkan` instead of `metal` (#57), overwrote the
day's local bench file (#58), and scored overhead against a separate run (#59). The
recorded 1024² JSON predates the #57 fix, so its build column still reads `vulkan`.
