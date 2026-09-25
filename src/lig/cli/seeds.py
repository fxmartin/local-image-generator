"""`lig seeds`: render one prompt under N consecutive seeds to compare compositions."""

import secrets
import uuid
from functools import partial
from pathlib import Path

import typer

from lig.backends.base import EngineError
from lig.cli.generate import EXIT_USAGE, _fail, open_backend
from lig.cli.progress import generation_progress
from lig.core import config as cfg
from lig.core import run
from lig.core.models import SEED_BITS
from lig.core.output import write_result
from lig.core.sheet import build_sheet
from lig.models.registry import RegistryError, load_registry

MAX_COUNT = 8


def seeds(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="What to draw."),
    count: int = typer.Option(4, "--count", "-n", help=f"Images to render (1-{MAX_COUNT})."),
    seed_start: int | None = typer.Option(
        None, "--seed-start", help="First seed; random (and printed) if omitted."
    ),
    size: str | None = typer.Option(None, "--size", help="WIDTHxHEIGHT, multiples of 32."),
    steps: int | None = typer.Option(None, "--steps", help="Sampling steps."),
    engine: str | None = typer.Option(None, "--engine", help="Engine: auto, sdcpp, ncnn, fake."),
    out: Path | None = typer.Option(None, "--out", help="Output directory."),  # noqa: B008
    negative: str | None = typer.Option(None, "--negative", help="Negative prompt."),
    guidance: float | None = typer.Option(None, "--guidance", help="Guidance scale."),
    no_sheet: bool = typer.Option(False, "--no-sheet", help="Skip the contact sheet."),
    force: bool = typer.Option(False, "--force", help="Run even if memory looks too tight."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Print only the output paths."),
) -> None:
    """Render PROMPT under consecutive seeds, one after the other."""
    from lig.cli.app import memory_preflight  # late: app imports this module

    if not 1 <= count <= MAX_COUNT:
        raise _fail(
            f"invalid --count {count}: must be between 1 and {MAX_COUNT} (max {MAX_COUNT})",
            EXIT_USAGE,
        )
    seed_limit = 2**SEED_BITS
    if seed_start is None:
        seed_start = secrets.randbelow(seed_limit - count + 1)
        random_start = True
    else:
        random_start = False
    if seed_start < 0 or seed_start + count > seed_limit:
        raise _fail(
            f"seeds {seed_start}..{seed_start + count - 1} must lie in 0..{seed_limit - 1}",
            EXIT_USAGE,
        )

    try:
        resolved = cfg.load_settings({"engine": engine, "output_dir": out})
        requests = [
            run.build_request(
                prompt,
                resolved,
                size=size,
                steps=steps,
                seed=seed_start + i,
                negative=negative,
                guidance=guidance,
            )
            for i in range(count)
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
        figures = run.estimate_memory(load_registry(), engine_name, requests[0])
    except RegistryError as exc:
        raise _fail(str(exc), 1) from exc
    if figures is not None:
        memory_preflight(figures[0], figures[1], force)

    if random_start and not quiet:
        typer.echo(f"seed start: {seed_start}")
    batch_id = uuid.uuid4().hex
    writer = partial(write_result, batch_id=batch_id)
    members: list[tuple[Path, int]] = []
    indeterminate = bool(getattr(backend, "progress_indeterminate", False))
    for done, request in enumerate(requests):
        try:
            with generation_progress(quiet=quiet, indeterminate=indeterminate) as on_progress:
                path = run.run_generate(backend, request, settings.output_dir, on_progress, writer)
        except EngineError:
            typer.echo(
                f"error: seed {request.seed} failed; kept {done} of {count} images", err=True
            )
            raise
        members.append((path, request.seed))
        typer.echo(str(path))
    if not no_sheet:
        typer.echo(str(build_sheet(members, settings.output_dir, batch_id)))
