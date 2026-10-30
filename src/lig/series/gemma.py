"""Client for the `gemma` command: system instruction + request on stdin, answer on stdout."""

import os
import re
import shutil
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass

from lig.core import llm_key

ENV_GEMMA = "LIG_SERIES_GEMMA"
DEFAULT_BINARY = "gemma"
# `gemma` asks the larm gateway on the Mac, which may first have to load the model.
DEFAULT_PLAN_TIMEOUT_S = 600.0
# The gateway answers 429 (rate limit) or 503 (model busy loading) when it cannot take a call
# now; `gemma` reports the status in its error line. One retry spares the whole series.
BUSY_ERROR = re.compile(r"\(HTTP (429|503)\)")
RETRY_WAIT_S = 10.0
ENV_GATEWAY_KEY = "LARM_API_KEY"  # what the `gemma` CLI reads before its own key file
STDERR_TAIL_LINES = 20
EXIT_FAILED = 1
EXIT_NOT_FOUND = 4
NOT_FOUND_MESSAGE = "gemma not found; install m3max-gemma or set --gemma"


_sleep = time.sleep  # seam: tests record the wait instead of sleeping


class GemmaError(Exception):
    """Planning failed; `exit_code` is what `lig-series` should exit with."""

    exit_code = EXIT_FAILED


class GemmaNotFound(GemmaError):
    exit_code = EXIT_NOT_FOUND

    def __init__(self) -> None:
        super().__init__(NOT_FOUND_MESSAGE)


def _tail(text: str, lines: int = STDERR_TAIL_LINES) -> str:
    return "\n".join(text.splitlines()[-lines:])


def _gateway_env() -> dict[str, str] | None:
    """lig's own gateway key for `gemma`, so the gateway counts these calls as lig's."""
    key = llm_key.read_api_key()
    return {**os.environ, ENV_GATEWAY_KEY: key} if key else None


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
                [self.resolve(), "--status"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=_gateway_env(),
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
        proc = self._run(argv, request)
        if proc.returncode != 0 and BUSY_ERROR.search(proc.stderr):
            _sleep(RETRY_WAIT_S)
            proc = self._run(argv, request)
        if proc.returncode != 0:
            raise GemmaError(f"gemma exited {proc.returncode}\n{_tail(proc.stderr)}".rstrip())
        return proc.stdout.strip()

    def _run(self, argv: list[str], request: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                argv,
                input=request,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=_gateway_env(),
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
