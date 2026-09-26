"""`lig-series`: plan a photo series with `gemma`, render each shot with `lig generate`."""

import random
import sys
from datetime import datetime
from functools import partial
from pathlib import Path

import typer
from typer.core import TyperGroup

from lig.core.output import slugify
from lig.series import characters, compose, prompts
from lig.series.gemma import GemmaClient, GemmaError
from lig.series.runner import LigFlags, run_series
from lig.series.settings import DEFAULT_MAX_SHOTS, Character, SeriesError, plan_settings
from lig.series.shots import plan_shots

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


def _plan(client: GemmaClient, settings):
    for shot in plan_shots(client, settings):
        yield compose.with_prompt(shot, settings)


@app.command("run", epilog="Manage saved characters with `lig-series characters --help`.")
def main(
    request: str = typer.Argument(..., help='e.g. "Create 10 photos black and white of a woman".'),
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
    gemma: str | None = typer.Option(None, "--gemma", help="The gemma command to call."),
    plan_timeout: float = typer.Option(600.0, "--plan-timeout", help="Seconds per gemma call."),
) -> None:
    """Run the global call, then plan and render each shot in turn."""
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
    if seed is not None:
        base_seed = seed
    elif saved:
        base_seed = saved.seed
    else:
        base_seed = random.SystemRandom().randrange(MAX_SEED)
    typer.echo(f"series of {settings.count} in {series_dir} (seed {base_seed})", err=True)
    flags = LigFlags(
        size=size, steps=steps, engine=engine, host=host, negative=negative, guidance=guidance
    )
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
