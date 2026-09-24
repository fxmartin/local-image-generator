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
