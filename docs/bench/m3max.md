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

## Remote overhead (Story 06.3-002)

Overhead = the XPS's remote wall clock (`lig bench --host m3max`, includes the PNG transfer
and SSE stream) minus the Mac's local total for the same prompt, seed, size and steps.
Target: ≤ 10 s. Above that, open an issue with the numbers.

```sh
# on the M3 Max
lig bench --engines sdcpp --size 768x768 --steps 30
# on the XPS, with `lig serve` running on the Mac
lig bench --host m3max --size 768x768 --steps 30
lig bench overhead m3max-local.json xps-remote.json   # prints the line to paste below
```

The remote JSON records `client_host` and `server_host`.

| Date | Client → server | Local total | Remote wall | Overhead | Result |
|---|---|---|---|---|---|
| pending | xps → m3max | pending | pending | pending | to be measured on the two machines |
