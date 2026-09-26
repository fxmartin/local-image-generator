"""`lig-series`: plan a photo series with `gemma`, render each shot with `lig generate`."""

import random
import sys
from datetime import datetime
from functools import partial
from pathlib import Path

import typer

from lig.core.output import slugify
from lig.series import compose, prompts
from lig.series.gemma import GemmaClient, GemmaError
from lig.series.runner import LigFlags, run_series
from lig.series.settings import DEFAULT_MAX_SHOTS, plan_settings
from lig.series.shots import plan_shots

MAX_SEED = 2**32

app = typer.Typer(add_completion=False, help=__doc__)


def _plan(client: GemmaClient, settings):
    for shot in plan_shots(client, settings):
        yield compose.with_prompt(shot, settings)


@app.command()
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
        settings = plan_settings(
            client,
            request,
            series_dir=series_dir,
            count=count,
            max_shots=max_shots,
            style=style,
            setting=setting,
            temperature=prompts.GLOBAL_TEMPERATURE,
        )
    except GemmaError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(error.exit_code) from error
    base_seed = seed if seed is not None else random.SystemRandom().randrange(MAX_SEED)
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
    raise typer.Exit(result.exit_code)


if __name__ == "__main__":
    sys.exit(app())
