"""Engine log capture and the friendly failure report shown instead of a traceback."""

from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Self

from platformdirs import user_state_dir
from rich.console import Console
from rich.panel import Panel

MAX_LOG_FILES = 50
TAIL_LINES = 20


def default_log_dir() -> Path:
    return Path(user_state_dir("lig")) / "logs"


def prune_logs(log_dir: Path, keep: int = MAX_LOG_FILES) -> None:
    """Delete the oldest `*.log` files beyond `keep`; timestamped names sort chronologically."""
    logs = sorted(log_dir.glob("*.log"))
    for stale in logs[: max(len(logs) - keep, 0)]:
        stale.unlink(missing_ok=True)


class EngineLog:
    """Streams engine output to a timestamped file, echoing to the terminal when verbose."""

    def __init__(
        self,
        engine: str,
        *,
        verbose: bool = False,
        log_dir: Path | None = None,
        console: Console | None = None,
    ) -> None:
        directory = log_dir or default_log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        # Prune before creating so the new file makes the total at most `keep`.
        prune_logs(directory, MAX_LOG_FILES - 1)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        self.path = directory / f"{stamp}_{engine}.log"
        self.verbose = verbose
        self._console = console or Console(stderr=True)
        self._file = self.path.open("a", encoding="utf-8")

    def write(self, line: str) -> None:
        line = line.rstrip("\n")
        self._file.write(line + "\n")
        self._file.flush()  # keep the file current so a crash loses nothing
        if self.verbose:
            self._console.print(line, markup=False, highlight=False)

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def tail_lines(path: Path | None, count: int = TAIL_LINES) -> list[str]:
    """Last `count` lines of a log; empty if the log is absent or unreadable."""
    if path is None:
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-count:]
    except OSError:
        return []


def report_engine_error(error: Exception, log_path: Path | None, console: Console) -> None:
    """Print a one-line summary, the last log lines and the log path (plain text off a TTY)."""
    summary = (str(error).splitlines() or [type(error).__name__])[0]
    console.print(f"Error: {summary}", markup=False, highlight=False)
    tail = tail_lines(log_path)
    if tail:
        body = "\n".join(tail)
        if console.is_terminal:
            console.print(Panel(body, title=f"last {len(tail)} log lines", title_align="left"))
        else:
            console.print(f"--- last {len(tail)} log lines ---", markup=False)
            console.print(body, markup=False, highlight=False)
    if log_path is not None:
        console.print(f"Log: {log_path}", markup=False, highlight=False, soft_wrap=True)
