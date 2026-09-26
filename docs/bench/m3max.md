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
| sd.cpp Metal | 1024², 40 steps, cfg 1.0 | pending | pending | to be recorded on the M3 Max (toolchain, sd.cpp commit, lig version) |
