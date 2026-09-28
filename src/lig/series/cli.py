"""`lig-series`: plan a photo series with `gemma`, render each shot with `lig generate`."""

import random
import sys
from datetime import datetime
from functools import partial
from pathlib import Path

import typer
from pydantic import ValidationError
from typer.core import TyperGroup

from lig.core.output import slugify
from lig.series import characters, compose, prompts
from lig.series.gemma import GemmaClient, GemmaError
from lig.series.manifest import ShotRecord, read_manifest
from lig.series.plan import SeriesPlan, format_plan, read_plan, write_plan
from lig.series.runner import LigFlags, run_series
from lig.series.settings import (
    DEFAULT_MAX_SHOTS,
    EXIT_USAGE,
    Character,
    SeriesError,
    plan_settings,
)
from lig.series.shots import Shot, plan_shots

MAX_SEED = 2**32


class _RequestGroup(TyperGroup):
    """`lig-series "request" ...` keeps working: anything that is not a subcommand is a run.

    Routed before the group parses its own options, so `--help` shows the run flags and
    options placed before the request reach `run` instead of being rejected by the group.
    """

    def parse_args(self, ctx: typer.Context, args: list[str]) -> list[str]:
        if not args or args[0] not in self.commands:
            args = ["run", *args]
        return super().parse_args(ctx, args)


app = typer.Typer(add_completion=False, help=__doc__, cls=_RequestGroup)
characters_app = typer.Typer(help="List, show or delete saved characters.")
app.add_typer(characters_app, name="characters")


def _plan(client: GemmaClient, settings, known: list[Shot] | None = None):
    for shot in plan_shots(client, settings, known=known or []):
        yield compose.with_prompt(shot, settings)


def _usage(message: str) -> None:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(EXIT_USAGE)


def _flags(options: dict) -> LigFlags:
    names = ("size", "steps", "engine", "host", "negative", "guidance")
    return LigFlags(**{name: options[name] for name in names})


def _plan_only(client: GemmaClient, settings, request: str, series_dir: Path) -> None:
    """Run every per-shot call, print and save the plan; no `lig` process starts."""
    try:
        shots = list(_plan(client, settings))
    except GemmaError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(error.exit_code) from error
    plan = SeriesPlan(request=request, settings=settings, shots=shots)
    path = write_plan(series_dir, plan)
    typer.echo(format_plan(plan))
    typer.echo(f"plan written to {path}", err=True)
    raise typer.Exit(0)


def _render_plan(
    from_plan: Path,
    out: Path | None,
    resume: bool,
    seed: int | None,
    flags: LigFlags,
    keep_going: bool,
    sheet: bool,
) -> None:
    """Render a saved plan without `gemma`; with `resume`, only shots lacking an image."""
    try:
        plan = read_plan(from_plan)
    except SeriesError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(error.exit_code) from error
    series_dir = out or Path("series") / f"{datetime.now():%Y%m%d-%H%M%S}_{slugify(plan.request)}"
    done: dict[int, ShotRecord] = {}
    previous_seed = None
    if resume:
        try:
            manifest = read_manifest(series_dir)
        except (OSError, ValueError) as error:
            _usage(f"cannot resume, no readable series.json in {series_dir}: {error}")
        previous_seed = manifest.seed
        done = {
            r.index: r
            for r in manifest.shots
            if r.status == "done" and r.png and Path(r.png).exists()
        }
    if seed is None:
        seed = (
            previous_seed
            if previous_seed is not None
            else random.SystemRandom().randrange(MAX_SEED)
        )
    typer.echo(f"series of {plan.settings.count} in {series_dir} (seed {seed})", err=True)
    result = run_series(
        plan.settings,
        lambda _settings: iter(plan.shots),
        out_dir=series_dir,
        seed=seed,
        flags=flags,
        keep_going=keep_going,
        request=plan.request,
        done=done,
        sheet=sheet,
    )
    raise typer.Exit(result.exit_code)


def _resume_live(
    series_dir: Path,
    client: GemmaClient,
    seed: int | None,
    flags: LigFlags,
    keep_going: bool,
    sheet: bool,
) -> None:
    """Finish a series run without --plan-only: gemma plans only the shots never planned."""
    try:
        manifest = read_manifest(series_dir)
    except (OSError, ValueError) as error:
        _usage(f"cannot resume, no readable series.json in {series_dir}: {error}")
    # Shots are planned in order, so the planned ones are a prefix; a failed shot keeps its
    # scene and is re-rendered as planned.
    known: list[Shot] = []
    for record in sorted(manifest.shots, key=lambda r: r.index):
        try:
            known.append(Shot(title=record.title, scene=record.scene))
        except ValidationError:
            break
    done = {
        r.index: r for r in manifest.shots if r.status == "done" and r.png and Path(r.png).exists()
    }
    seed = manifest.seed if seed is None else seed
    count = manifest.plan.count
    typer.echo(f"resuming series of {count} in {series_dir} (seed {seed})", err=True)
    result = run_series(
        manifest.plan,
        partial(_plan, client, known=known),
        out_dir=series_dir,
        seed=seed,
        flags=flags,
        keep_going=keep_going,
        request=manifest.request,
        gemma_model=manifest.gemma_model,
        sheet=sheet,
        done=done,
    )
    raise typer.Exit(result.exit_code)


@app.command("run", epilog="Manage saved characters with `lig-series characters --help`.")
def main(
    request: str | None = typer.Argument(
        None, help='e.g. "Create 10 photos black and white of a woman".'
    ),
    count: int | None = typer.Option(None, "--count", help="Number of photos."),
    max_shots: int = typer.Option(DEFAULT_MAX_SHOTS, "--max-shots", help="Upper bound on count."),
    style: str | None = typer.Option(None, "--style", help="Fix the shared style."),
    setting: str | None = typer.Option(None, "--setting", help="Fix the shared location."),
    seed: int | None = typer.Option(None, "--seed", help="Base seed for every shot; random."),
    size: str | None = typer.Option(None, "--size", help="lig --size (WIDTHxHEIGHT)."),
    steps: int | None = typer.Option(None, "--steps", help="lig --steps."),
    engine: str | None = typer.Option(None, "--engine", help="lig --engine."),
    host: str | None = typer.Option(None, "--host", help="lig --host."),
    negative: str | None = typer.Option(None, "--negative", help="lig --negative."),
    guidance: float | None = typer.Option(None, "--guidance", help="lig --guidance."),
    character: str | None = typer.Option(
        None, "--character", help="Save this series' character under NAME, or reuse it if saved."
    ),
    out: Path | None = typer.Option(  # noqa: B008
        None, "--out", help="Series directory; default series/YYYYMMDD-HHMMSS_<slug>."
    ),
    keep_going: bool = typer.Option(False, "--keep-going", help="Render the rest after a failure."),
    no_sheet: bool = typer.Option(False, "--no-sheet", help="Skip the sheet.png contact sheet."),
    plan_only: bool = typer.Option(
        False, "--plan-only", help="Plan every shot, write plan.json, render nothing."
    ),
    from_plan: Path | None = typer.Option(  # noqa: B008
        None, "--from-plan", help="Render an edited plan.json; gemma is not called."
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="With --out: finish an interrupted series, rendering only shots without an image "
        "(add --from-plan to render a saved plan).",
    ),
    gemma: str | None = typer.Option(None, "--gemma", help="The gemma command to call."),
    plan_timeout: float = typer.Option(600.0, "--plan-timeout", help="Seconds per gemma call."),
) -> None:
    """Run the global call, then plan and render each shot in turn."""
    if from_plan is not None:
        if plan_only or request is not None:
            _usage("--from-plan cannot be combined with --plan-only or a request")
        if resume and out is None:
            _usage("--resume needs --out, the interrupted series directory")
    elif resume:
        if request is not None or out is None:
            _usage("--resume needs --out, the interrupted series directory, and no request")
        client = GemmaClient(binary=gemma, timeout=plan_timeout)
        _resume_live(out, client, seed, _flags(locals()), keep_going, not no_sheet)
    elif request is None:
        _usage("a request is required unless --from-plan is given")
    if from_plan is not None:
        _render_plan(from_plan, out, resume, seed, _flags(locals()), keep_going, False)
    assert request is not None
    series_dir = out or Path("series") / f"{datetime.now():%Y%m%d-%H%M%S}_{slugify(request)}"
    client = GemmaClient(binary=gemma, timeout=plan_timeout)
    try:
        saved = characters.load(character) if character else None
    except SeriesError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(error.exit_code) from error
    try:
        settings = plan_settings(
            client,
            request,
            series_dir=series_dir,
            count=count,
            max_shots=max_shots,
            style=style,
            setting=setting,
            character=Character(name=saved.name, look=saved.look) if saved else None,
            temperature=prompts.GLOBAL_TEMPERATURE,
        )
    except GemmaError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(error.exit_code) from error
    if plan_only:
        _plan_only(client, settings, request, series_dir)
    if seed is not None:
        base_seed = seed
    elif saved:
        base_seed = saved.seed
    else:
        base_seed = random.SystemRandom().randrange(MAX_SEED)
    typer.echo(f"series of {settings.count} in {series_dir} (seed {base_seed})", err=True)
    flags = _flags(locals())
    result = run_series(
        settings,
        partial(_plan, client),
        out_dir=series_dir,
        seed=base_seed,
        flags=flags,
        keep_going=keep_going,
        request=request,
        gemma_model=client.status(),
        sheet=not no_sheet,
    )
    if character and saved is None and result.exit_code == 0:
        where = characters.save(
            character,
            settings.character,
            style=settings.style,
            seed=base_seed,
            source_series=str(series_dir),
        )
        typer.echo(f"saved character {character} in {where}", err=True)
    raise typer.Exit(result.exit_code)


@characters_app.command("list")
def characters_list() -> None:
    """Print the saved character names."""
    for name in characters.list_names():
        typer.echo(name)


@characters_app.command("show")
def characters_show(name: str = typer.Argument(...)) -> None:
    """Print a saved character."""
    try:
        saved = characters.load(name)
    except SeriesError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(error.exit_code) from error
    if saved is None:
        typer.echo(f"error: no saved character {name!r}", err=True)
        raise typer.Exit(1)
    typer.echo(saved.model_dump_json(indent=2))
    reference = characters.reference_path(name)
    if reference:
        typer.echo(f"reference: {reference}")


@characters_app.command("rm")
def characters_rm(
    name: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", help="Do not ask for confirmation."),
) -> None:
    """Delete a saved character."""
    try:
        exists = characters.load(name) is not None
    except SeriesError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(error.exit_code) from error
    if not exists:
        typer.echo(f"error: no saved character {name!r}", err=True)
        raise typer.Exit(1)
    if not yes:
        typer.confirm(f"Delete character {name!r}?", abort=True)
    characters.remove(name)


if __name__ == "__main__":
    sys.exit(app())
