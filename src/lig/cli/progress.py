"""Progress display for a generation: Rich bar on a TTY, sparse plain lines otherwise."""

import os
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import IO

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    Task,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.text import Text

from lig.backends.base import ProgressCallback

PLAIN_STEP_PERCENT = 10


class StepColumn(ProgressColumn):
    """Renders `step 12/40`."""

    def render(self, task: Task) -> Text:
        return Text(f"step {int(task.completed)}/{int(task.total or 0)}")


def use_rich(stream: IO[str] | None = None) -> bool:
    """Rich only on a real terminal with colour allowed; anything else gets plain lines."""
    stream = stream if stream is not None else sys.stdout
    return stream.isatty() and not os.environ.get("NO_COLOR")


def format_summary(load_s: float, total_s: float) -> str:
    return f"loaded in {load_s:.1f}s, total {total_s:.1f}s"


@contextmanager
def generation_progress(
    *,
    quiet: bool = False,
    indeterminate: bool = False,
    rich: bool | None = None,
    err: IO[str] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[ProgressCallback | None]:
    """Yield the `on_progress` callback (None when quiet); print a load/total summary on success.

    Load time is the wait until the first step lands: model load plus engine start-up.
    Progress goes to stderr so stdout stays a clean final path.
    """
    if quiet:
        yield None
        return
    err = err if err is not None else sys.stderr
    started = clock()
    first_step_at: list[float] = []
    interactive = use_rich() if rich is None else rich
    console = Console(file=err, force_terminal=interactive, no_color=not interactive)

    def note_step() -> None:
        if not first_step_at:
            first_step_at.append(clock())

    def summarize() -> None:
        end = clock()
        load_s = (first_step_at[0] if first_step_at else end) - started
        console.print(format_summary(load_s, end - started), markup=False, highlight=False)

    if not interactive:
        last_bucket = [0]  # first line at 10 %, not at the first step
        console.print("generating...", markup=False, highlight=False)

        def plain(step: int, total: int) -> None:
            note_step()
            if total <= 0:
                return
            bucket = step * 100 // total // PLAIN_STEP_PERCENT
            if bucket > last_bucket[0]:
                last_bucket[0] = bucket
                console.print(
                    f"step {step}/{total} ({step * 100 // total}%)", markup=False, highlight=False
                )

        yield plain
        summarize()
        return

    columns: list[ProgressColumn] = (
        [SpinnerColumn(), TextColumn("generating"), TimeElapsedColumn()]
        if indeterminate
        else [
            TextColumn("generating"),
            BarColumn(),
            StepColumn(),
            TimeElapsedColumn(),
            TextColumn("ETA"),
            TimeRemainingColumn(),
        ]
    )
    with Progress(*columns, console=console, transient=False) as progress:
        task = progress.add_task("generate", total=None if indeterminate else 1)

        def rich_cb(step: int, total: int) -> None:
            note_step()
            if not indeterminate:
                progress.update(task, completed=step, total=total)

        yield rich_cb
    summarize()
