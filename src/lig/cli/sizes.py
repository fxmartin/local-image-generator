"""`lig sizes`: render one prompt and seed at several sizes to pick a framing."""

import secrets
import uuid
from functools import partial
from pathlib import Path

import typer

from lig.backends.base import EngineError
from lig.cli import scripting
from lig.cli.generate import EXIT_USAGE, _fail, open_backend
from lig.cli.progress import generation_progress
from lig.core import config as cfg
from lig.core import run
from lig.core.models import SEED_BITS
from lig.core.output import write_result
from lig.core.sheet import build_sheet
from lig.models.registry import RegistryError, load_registry

MAX_SIZES = 8


def sizes(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="What to draw."),
    sizes_: str = typer.Option(
        ...,
        "--sizes",
        help=f"Comma-separated WIDTHxHEIGHT list (multiples of 32, up to {MAX_SIZES}), "
        "e.g. 1024x1024,1536x864,864x1536. Each tile is a fresh render at that size, "
        "not an upscale of another tile: a larger size yields a new composition.",
    ),
    seed: int | None = typer.Option(
        None, "--seed", help="Seed shared by every size; random (and printed) if omitted."
    ),
    steps: int | None = typer.Option(None, "--steps", help="Sampling steps."),
    engine: str | None = typer.Option(
        None,
        "--engine",
        help="Engine: auto, sdcpp, ncnn, mlx, fake or remote.",
        autocompletion=scripting.complete_engine,
    ),
    out: Path | None = typer.Option(None, "--out", help="Output directory."),  # noqa: B008
    negative: str | None = typer.Option(None, "--negative", help="Negative prompt."),
    guidance: float | None = typer.Option(None, "--guidance", help="Guidance scale."),
    no_sheet: bool = typer.Option(False, "--no-sheet", help="Skip the contact sheet."),
    force: bool = typer.Option(False, "--force", help="Run even if memory looks too tight."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Print only the output paths."),
    as_json: bool = typer.Option(False, "--json", help=scripting.JSON_HELP),
    open_: bool = typer.Option(False, "--open", help=scripting.OPEN_HELP),
) -> None:
    """Render PROMPT with one seed at several sizes, side by side in a sheet labelled by size.

    The tiles are not upscales of each other: each size is its own render, so a larger
    size gives a new composition rather than the same picture with more pixels.
    """
    from lig.cli.app import memory_preflight  # late: app imports this module

    size_list = [s.strip() for s in sizes_.split(",")]
    if not 1 <= len(size_list) <= MAX_SIZES or "" in size_list:
        raise _fail(
            f"invalid --sizes '{sizes_}': give 1-{MAX_SIZES} comma-separated WIDTHxHEIGHT values",
            EXIT_USAGE,
        )
    if len({s.lower() for s in size_list}) != len(size_list):
        raise _fail(f"invalid --sizes '{sizes_}': sizes must be distinct", EXIT_USAGE)
    seed_limit = 2**SEED_BITS
    random_seed = seed is None
    if seed is None:
        seed = secrets.randbelow(seed_limit)
    if not 0 <= seed < seed_limit:
        raise _fail(f"seed {seed} must lie in 0..{seed_limit - 1}", EXIT_USAGE)

    try:
        resolved = cfg.load_settings({"engine": engine, "output_dir": out})
        requests = [
            run.build_request(
                prompt,
                resolved,
                size=size,
                steps=steps,
                seed=seed,
                negative=negative,
                guidance=guidance,
            )
            for size in size_list
        ]
    except (cfg.ConfigError, run.UsageError) as exc:
        raise _fail(str(exc), EXIT_USAGE) from exc
    settings = resolved.settings
    for warning in resolved.warnings:
        typer.echo(f"warning: {warning}", err=True)
    if (warning := run.negative_prompt_warning(requests[0])) is not None:
        typer.echo(f"warning: {warning}", err=True)

    backend, engine_name = open_backend(ctx, settings)
    try:
        # the largest tile bounds the memory need
        largest = max(requests, key=lambda r: r.width * r.height)
        figures = run.estimate_memory(load_registry(), engine_name, largest)
    except RegistryError as exc:
        raise _fail(str(exc), 1) from exc
    if figures is not None:
        memory_preflight(figures[0], figures[1], force)

    if random_seed and not quiet and not as_json:
        typer.echo(f"seed: {seed}")
    batch_id = uuid.uuid4().hex
    writer = partial(write_result, batch_id=batch_id)
    members: list[tuple[Path, int]] = []
    tile_labels: dict[Path, str] = {}
    indeterminate = bool(getattr(backend, "progress_indeterminate", False))
    for done, request in enumerate(requests):
        label = f"{request.width}x{request.height}"
        try:
            with generation_progress(quiet=quiet, indeterminate=indeterminate) as on_progress:
                path = run.run_generate(backend, request, settings.output_dir, on_progress, writer)
        except EngineError:
            typer.echo(
                f"error: size {label} failed; kept {done} of {len(requests)} images", err=True
            )
            raise
        members.append((path, request.seed))
        tile_labels[path] = label
        if not as_json:
            typer.echo(str(path))
    sheet = (
        None
        if no_sheet
        else build_sheet(
            members, settings.output_dir, batch_id, label=lambda path, _seed: tile_labels[path]
        )
    )
    if as_json:
        scripting.emit_json(
            {
                "seed": seed,
                "images": [scripting.image_document(path) for path, _ in members],
                "sheet": str(sheet) if sheet else None,
            }
        )
    elif sheet:
        typer.echo(str(sheet))
    if open_:
        for path in [sheet] if sheet else [path for path, _ in members]:
            scripting.open_in_viewer(path)
