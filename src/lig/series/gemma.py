"""Client for the `gemma` command: system instruction + request on stdin, answer on stdout."""

import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass

ENV_GEMMA = "LIG_SERIES_GEMMA"
DEFAULT_BINARY = "gemma"
# `gemma` starts the Mac's model server on demand, so the first call can be slow.
DEFAULT_PLAN_TIMEOUT_S = 600.0
STDERR_TAIL_LINES = 20
EXIT_FAILED = 1
EXIT_NOT_FOUND = 4
NOT_FOUND_MESSAGE = "gemma not found; install m3max-gemma or set --gemma"


class GemmaError(Exception):
    """Planning failed; `exit_code` is what `lig-series` should exit with."""

    exit_code = EXIT_FAILED


class GemmaNotFound(GemmaError):
    exit_code = EXIT_NOT_FOUND

    def __init__(self) -> None:
        super().__init__(NOT_FOUND_MESSAGE)


def _tail(text: str, lines: int = STDERR_TAIL_LINES) -> str:
    return "\n".join(text.splitlines()[-lines:])


@dataclass(frozen=True)
class GemmaClient:
    """`binary` is the `--gemma` flag value; None falls back to `LIG_SERIES_GEMMA`, then PATH."""

    binary: str | None = None
    timeout: float = DEFAULT_PLAN_TIMEOUT_S
    env: Mapping[str, str] | None = None

    def resolve(self) -> str:
        environ = os.environ if self.env is None else self.env
        name = self.binary or environ.get(ENV_GEMMA) or DEFAULT_BINARY
        found = shutil.which(name)
        if found is None:
            raise GemmaNotFound()
        return found

    def status(self) -> str | None:
        """The model `gemma --status` reports, for `series.json`; None if it cannot be read."""
        try:
            proc = subprocess.run(
                [self.resolve(), "--status"], capture_output=True, text=True, timeout=self.timeout
            )
        except (GemmaError, OSError, subprocess.TimeoutExpired):
            return None
        return proc.stdout.strip() or None if proc.returncode == 0 else None

    def complete(self, system: str, request: str, *, temperature: float, max_tokens: int) -> str:
        argv = [
            self.resolve(),
            "--system",
            system,
            "--temperature",
            str(temperature),
            "--max-tokens",
            str(max_tokens),
            "-",
        ]
        try:
            proc = subprocess.run(
                argv, input=request, capture_output=True, text=True, timeout=self.timeout
            )
        except subprocess.TimeoutExpired as error:
            stderr = (
                error.stderr.decode(errors="replace")
                if isinstance(error.stderr, bytes)
                else (error.stderr or "")
            )
            message = f"gemma timed out after {self.timeout:g} s (raise --plan-timeout)"
            raise GemmaError(f"{message}\n{_tail(stderr)}".rstrip()) from error
        except OSError as error:
            raise GemmaError(f"could not run gemma: {error}") from error
        if proc.returncode != 0:
            raise GemmaError(f"gemma exited {proc.returncode}\n{_tail(proc.stderr)}".rstrip())
        return proc.stdout.strip()
