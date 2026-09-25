# XPS 13 engine bench (Phase 0 spike)

Host `omarchy-xps13`: Dell XPS 13 9350, Intel Arc 140V iGPU (Lunar Lake), 30 GB
shared RAM. Numbers here are recorded by hand; CI cannot run engines.

## Environment

| Item | Value |
|---|---|
| Kernel | `7.2.5-3-omarchy` |
| GPU driver | `xe` kernel driver; Mesa `vulkan-intel 1:26.2.2-1` |
| Vulkan device | `Intel(R) Graphics (LNL)`, integrated, UMA, fp16/bf16, cooperative matrix |

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

The same squeeze hit sd.cpp: its edit run (Story 02.1-002's comparison
partner, recorded under Story 02.1-001) finished sampling, then failed at VAE
decode because only about 3.1 GB of device memory was available against the
3.6 GB it needed.

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

Note for that decision: the sd.cpp text-to-image run used `--cfg-scale 6.0`,
as sd.cpp's Qwen-Image-2.1 docs suggest. Qwen-Image-2.1 is designed for
guidance-free sampling at scale 1.0, which is ncnn's and mflux's default and
what the reference article used. With guidance above 1.0 each step runs the
model twice, so an sd.cpp run at `--cfg-scale 1.0` should be measured before
concluding the XPS cannot reach the 10-minute target.
