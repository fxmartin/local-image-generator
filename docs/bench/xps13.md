# XPS 13 engine bench (Phase 0 spike)

Host `omarchy-xps13`: Dell XPS 13 9350, Intel Arc 140V iGPU (Lunar Lake), 30 GB
shared RAM. Numbers here are recorded by hand; CI cannot run engines.

## Environment

| Item | Value |
|---|---|
| Kernel | `7.2.5-3-omarchy` |
| Vulkan device | `Intel(R) Graphics (LNL)`, integrated, UMA, fp16/bf16, `KHR_coopmat` |
| Driver | Intel open-source Mesa driver, Mesa 26.2.2-arch1.1 (`vulkan-intel 1:26.2.2-1`) |
| Vulkan API | 1.4.354 |
| Toolchain | cmake 4.4.3, ninja 1.13.2, gcc 16.2.1 |

## stable-diffusion.cpp, Vulkan (Story 02.1-001): works, 21 min at 1024²

### Build

Pinned commit `b167b942f77ecb17e7f78e163a8c32ff7ac95c10`
(`master-913-b167b94`, 2026-09-25, "fix: align Qwen Image 2.1 flow schedule
with official defaults (#2048)").

The system has no `vulkan-headers` / `spirv-headers` packages and no
passwordless sudo, so both were built from source into a local prefix
(Vulkan-Headers `b0c3dd68`, SPIRV-Headers `cb42dec3`):

```sh
S=~/.cache/lig/spike
git clone --depth 1 --recurse-submodules --shallow-submodules \
  https://github.com/leejet/stable-diffusion.cpp $S/sdcpp
git clone --depth 1 https://github.com/KhronosGroup/Vulkan-Headers $S/vulkan-headers
git clone --depth 1 https://github.com/KhronosGroup/SPIRV-Headers  $S/spirv-headers
for d in spirv-headers vulkan-headers; do
  cmake -S $S/$d -B $S/$d/build -G Ninja -DCMAKE_INSTALL_PREFIX=$S/prefix
  cmake --install $S/$d/build
done
cmake -S $S/sdcpp -B $S/sdcpp/build -G Ninja -DSD_VULKAN=ON \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=$S/prefix
cmake --build $S/sdcpp/build -j6
$S/sdcpp/build/bin/sd-cli --help
```

On a fresh machine, `pacman -S vulkan-headers spirv-headers shaderc` replaces
the local-prefix step.

### Weights

Downloaded by hand to `~/.cache/lig/spike/sdcpp-models/`. Epic-03 reuses
these hashes.

| File | Source | Bytes | SHA-256 |
|---|---|---|---|
| `qwen_image_2.1-Q4_K.gguf` | `leejet/Qwen-Image-2.1-GGUF` | 4197494816 | `29f9c83c249ff0292fb2943fceddfa2319b446601866c82a4f8be062abea72c2` |
| `Qwen3VL-8B-Instruct-Q4_K_M.gguf` | `Qwen/Qwen3-VL-8B-Instruct-GGUF` | 5027784800 | `67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2` |
| `mmproj-Qwen3VL-8B-Instruct-F16.gguf` | `Qwen/Qwen3-VL-8B-Instruct-GGUF` | 1159029824 | `ca524100ebf825c9a870db1c580d03879e0da0ab2541697e2458e64891cf9d38` |
| `qwen_image_2.1_vae_bf16.safetensors` | `Comfy-Org/Qwen-Image-2.1` (`vae/`) | 675509688 | `bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9` |

### Timing method

GNU `time` is not installed on the XPS, so [`timev.py`](timev.py) stands in
for `/usr/bin/time -v`: it prints wall time and `ru_maxrss` of the child in
the same "Maximum resident set size (kbytes)" form.

Peak RSS undercounts memory on this UMA iGPU. sd.cpp keeps the weights in
`Vulkan_Host` buffers, which are driver allocations and do not appear in the
process RSS. The engine's own figure ("total params memory size") is the
better number for weights.

### Text-to-image, 1024², 40 steps, `--cfg-scale 6.0`

```sh
M=~/.cache/lig/spike/sdcpp-models
python3 docs/bench/timev.py ~/.cache/lig/spike/sdcpp/build/bin/sd-cli \
  --diffusion-model $M/qwen_image_2.1-Q4_K.gguf \
  --vae $M/qwen_image_2.1_vae_bf16.safetensors \
  --llm $M/Qwen3VL-8B-Instruct-Q4_K_M.gguf \
  -p "a lovely cat holding a sign says 'qwen2.1.cpp'" \
  -H 1024 -W 1024 --steps 40 --seed 42 --cfg-scale 6.0 \
  --sampling-method euler --offload-to-cpu --fa -v -o out/t2i.png
```

| Metric | Value |
|---|---|
| Status | **PASS**, PNG written (`out/t2i.png`, sha256 `a0ee8a65…0d63`) |
| Weights in memory | 8949.76 MB (text encoder 4302 MB, diffusion 4003 MB, VAE 644 MB) |
| Load (tensor read + stage to Vulkan0, all three models) | ≈ 6 s |
| Text conditioning | 3.80 s |
| Sampling | 2649.16 s. Steps 1–11 took 75–90 s/it; from step 13 on it held at ≈ 60.3 s/it |
| VAE decode | 51.12 s |
| Total (`generate_image`) | 2704.12 s |
| Wall clock (timev) | 2704.69 s (≈ 45 min) |
| Peak RSS (timev) | 895864 kB (≈ 0.85 GB, see the UMA note above) |
| Quality | Sharp photographic cat; the sign reads `qwen2.1.cpp` correctly with no artifacts |


### Text-to-image, 1024², 40 steps, `--cfg-scale 1.0`

Qwen-Image-2.1 is designed for guidance-free sampling at scale 1.0 (the
default of mflux and ncnn, and what the reference article used). Above 1.0,
every step runs the model twice: once with the prompt and once without. This
run is identical to the one above except for `--cfg-scale 1.0`, `-o
out/t2i-cfg1.png`, and a freshly rebooted XPS (driver GPU cache empty,
`GPUReclaim` 42 MB, 21 GB available).

| Metric | Value |
|---|---|
| Status | **PASS**, PNG written (`out/t2i-cfg1.png`, sha256 `4f55abb6…`) |
| Text conditioning | 2.50 s |
| Sampling | 1219.04 s. Steps 1–2 took 44–47 s/it; from step 13 on it held at ≈ 28.6 s/it |
| VAE decode | 26.73 s |
| Total (`generate_image`) | 1248.29 s |
| Wall clock (timev) | 1248.78 s (≈ 21 min) |
| Peak RSS (timev) | 479792 kB (see the UMA note above) |
| Quality | Sharp photographic tabby cat; the sign reads `qwen2.1.cpp` correctly with no artifacts. Different composition from the cfg 6.0 image, as expected when guidance changes. |

### Guidance comparison

| `--cfg-scale` | Steady s/it | Total at 1024², 40 steps | vs P0-1 target (600 s) |
|---|---|---|---|
| 6.0 | ≈ 60.3 | 2704 s (45 min) | 4.5× over |
| 1.0 | ≈ 28.6 | 1248 s (21 min) | 2.1× over |

Guidance 1.0 halves the time with no visible quality loss, so it should be
the sd.cpp adapter default (Story 02.2-002 currently says 6.0). It still
misses the 10-minute target at 1024² by about 2×. Story 02.1-004 owns the
decision: a smaller default size, fewer steps, or the XPS as a remote-only
client.

The two runs were not on identical memory conditions: the cfg 6.0 run shared
the machine with the build agents and the driver's GPU cache, the cfg 1.0 run
followed a reboot. The per-step ratio (2.1×) matches the doubled work, so
guidance explains most of the gap.

### Edit, 1024², 40 steps, `--cfg-scale 6.0`: failed at VAE decode

```sh
python3 docs/bench/timev.py ~/.cache/lig/spike/sdcpp/build/bin/sd-cli \
  --diffusion-model $M/qwen_image_2.1-Q4_K.gguf \
  --vae $M/qwen_image_2.1_vae_bf16.safetensors \
  --llm $M/Qwen3VL-8B-Instruct-Q4_K_M.gguf \
  --llm_vision $M/mmproj-Qwen3VL-8B-Instruct-F16.gguf \
  -r out/t2i.png -p "change 'qwen2.1.cpp' to 'sd.cpp'" \
  --steps 40 --seed 42 --cfg-scale 6.0 \
  --sampling-method euler --offload-to-cpu --fa -v -o out/edit.png
```

| Metric | Value |
|---|---|
| Status | **FAIL**, no image. Sampling completed; VAE decode ran out of device memory |
| Weights in memory | 10055.07 MB (the vision tower adds ≈ 1.1 GB to the text encoder) |
| VAE encode of the reference | 9.72 s |
| Sampling | 4031.26 s (≈ 96 s/it steady; step 1 took 168.6 s) |
| VAE decode | Failed: needed 3551 MB of device memory, 3106 MB available; the automatic retry with spatial tiling also failed |
| Wall clock (timev) | 4065.18 s (≈ 68 min), exit status 1 |
| Peak RSS (timev) | 641356 kB |

```
[WARN ] model manager cannot make enough memory available on Vulkan0: need 3551.06 MB device / 3039.06 MB budget, available 3106.00 MB device
[ERROR] vae decode compute failed
[ERROR] decode_first_stage failed for latent 1
```

At the time, the `xe` driver held about 9.7 GB of freed GPU buffers
(`GPUReclaim` in `/proc/meminfo`) cached from the earlier run, which the
kernel does not count as available. The edit was not rerun after the reboot.
A rerun at `--cfg-scale 1.0` on a clean boot should both fit and take roughly
half the time; it is left for Epic-04's manual edit acceptance (Story
04.2-001) rather than repeated here.

### Not yet run

- Second run with `--model-args qwen_image_2_1_prefix_cache=false`, to measure
  the prefix-cache trade-off (technical note on the story).

## qwenimage-ncnn-vulkan (Story 02.1-002): rejected on this hardware

**Status: rejected.** The engine refuses to start on the XPS: its
full-precision transformer needs more Vulkan memory than the iGPU driver
offers under normal desktop load. No image and no timings exist, so there is
no side-by-side comparison with stable-diffusion.cpp.

### Pinned versions

| Item | Value |
|---|---|
| Release | [`20260924`](https://github.com/nihui/qwenimage-ncnn-vulkan/releases/tag/20260924), `qwenimage-ncnn-vulkan-20260924-linux.zip` |
| Zip SHA-256 | `1278d9fdaeb615c7dca6c37212a3d92e36d9834c9f1f35661e2ec11bfc56c8f5` |
| Binary SHA-256 | `591d87466f6ab06c5e4957782ea03dac1ed6682ec2591569069a551c952627bf` |
| Model | [`nihui-szyl/qwen-image-ncnn`](https://huggingface.co/nihui-szyl/qwen-image-ncnn), folder `qwenimage21/`, revision `d92a054c94217b72dd8bfd6c2fe687e990f35fc6` |
| Model size | 31.19 GB (BF16: text encoder 15.14 GB, transformer blocks 13.96 GB, vision 1.15 GB, VAE 0.67 GB) |

Every model file's byte size was checked against the Hugging Face manifest
for that revision after download.

### Command

Same prompt, size, steps and seed as the sd.cpp run in Story 02.1-001.
`timev.py` stands in for GNU `time -v`, which is not installed on the XPS.

```sh
S=~/.cache/lig/spike
python3 $S/timev.py $S/ncnn/qwenimage-ncnn-vulkan-20260924-linux/qwenimage-ncnn-vulkan \
  -m $S/ncnn/models/qwenimage21 -g 0 \
  -p "a lovely cat holding a sign says 'qwen2.1.cpp'" \
  -s 1024,1024 -l 40 -r 42 -o $S/out-ncnn/t2i.png
```

### Result

Run on 2026-09-25 11:18 CEST, with no other engine running:

```
[0 Intel(R) Graphics (LNL)]  fp16-cm=8x16x16  int8-cm=8x16x32  bf16-cm=8x16x16
guidance-scale = 1
low_vram = 1 (heap=12135 MB, estimated transformer=14864 MB, prefix cache=12 MB)
transformer prefix cache = host (estimated working memory=14864 MB)
insufficient Vulkan memory for transformer: estimated 14864 MB, budget 12135 MB; reduce output size or reference image count/size
text-to-image generation failed
	Exit status: 1
```

| Metric | Value |
|---|---|
| Vulkan budget offered by the driver | 12,135 MB |
| Transformer working memory ncnn needs | 14,864 MB |
| Shortfall | 2,729 MB |
| Low-VRAM mode | Already on, chosen automatically; it still does not fit |

The requirement comes from the BF16 transformer weights, not from the output
size, so a smaller image would not help. The edit run was not attempted: it
needs the same transformer.

### Why the budget is low

On this UMA iGPU the Vulkan budget is carved out of system RAM. At the time of
the run, `/proc/meminfo` showed `GPUReclaim: 9734016 kB`: about 9.7 GB of
freed GPU buffers the `xe` driver keeps cached after the sd.cpp runs. The
kernel does not count this cache as available and only releases it under
heavy memory pressure. A brief 11 GB allocation released just 0.7 GB of it;
the kernel moved other pages to zram swap first.

The same squeeze hit sd.cpp: its edit run (above) finished sampling, then
failed at VAE decode because only about 3.1 GB of device memory was available
against the 3.6 GB it needed.

### What would change the decision

- **A fresh boot with nothing else open.** An empty driver cache should lift
  the budget above 15 GB. This was deliberately not tried: the XPS is FX's
  daily machine, and an engine that only runs after a reboot is not a usable
  default.
- **A quantized ncnn model.** The published package is BF16 only. An int8 or
  fp8 transformer would roughly halve the 14.9 GB.
- **A machine with more memory.** On the M3 Max the same binary and model are
  expected to fit; that is a Phase 2 or 3 candidate, not an XPS option.

### Consequence for Story 02.1-004

ncnn drops out of the XPS default-engine decision. The decision is between
stable-diffusion.cpp on Vulkan (Story 02.1-001) and the Intel-specific paths
(Story 02.1-003).

The sd.cpp guidance 1.0 measurement above (21 min at 1024²) is the current
baseline for that decision.
