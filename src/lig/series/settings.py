"""Story 09.1-002: the global `gemma` call that fixes what every photo of a series shares."""

import json
import re
from pathlib import Path
from typing import Annotated, Protocol

from pydantic import BaseModel, BeforeValidator, ValidationError, field_validator

from lig.series import prompts
from lig.series.gemma import GemmaError

DEFAULT_MAX_SHOTS = 20
EXIT_USAGE = 2
LOOK_MIN_WORDS = 25
LOOK_MAX_WORDS = 80
INVALID_ANSWER_FILE = "settings.invalid.txt"

_NUMBER_WORDS = {
    word: value
    for value, word in enumerate(
        "one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen twenty".split(),
        start=1,
    )
}
_COUNT_RE = re.compile(
    rf"\b(\d+|{'|'.join(_NUMBER_WORDS)})\s+(?:\w+\s+){{0,2}}?(?:photos?|images?|pictures?|shots?)\b",
    re.IGNORECASE,
)


class SeriesError(GemmaError):
    """A planning failure with the exit code `lig-series` should use."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class TextGenerator(Protocol):
    def complete(
        self, system: str, request: str, *, temperature: float, max_tokens: int
    ) -> str: ...


def _strip(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


NonBlank = Annotated[str, BeforeValidator(_strip)]


class Character(BaseModel):
    name: NonBlank
    look: NonBlank

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("look")
    @classmethod
    def _look_length(cls, value: str) -> str:
        words = len(value.split())
        if not LOOK_MIN_WORDS <= words <= LOOK_MAX_WORDS:
            raise ValueError(
                f"look must be {LOOK_MIN_WORDS} to {LOOK_MAX_WORDS} words, got {words}"
            )
        return value


class SeriesSettings(BaseModel):
    count: int
    character: Character
    style: NonBlank
    setting: NonBlank
    arc: NonBlank

    @field_validator("count")
    @classmethod
    def _count_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("count must be at least 1")
        return value

    @field_validator("style", "setting", "arc")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be empty")
        return value


def extract_json_object(text: str) -> dict:
    """First balanced JSON object in `text`, ignoring code fences and surrounding prose."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    raise ValueError("no JSON object found in the answer")


def requested_count(request: str) -> int | None:
    """The photo count a request names ("10 photos", "three images"), or None."""
    match = _COUNT_RE.search(request)
    if match is None:
        return None
    token = match.group(1).lower()
    return int(token) if token.isdigit() else _NUMBER_WORDS[token]


def _parse(raw: str, *, count: int | None, max_shots: int) -> SeriesSettings:
    data = extract_json_object(raw)
    if count is not None:
        data["count"] = count
    settings = SeriesSettings.model_validate(data)
    if settings.count > max_shots:
        raise ValueError(f"count {settings.count} is above --max-shots {max_shots}")
    return settings


def plan_settings(
    client: TextGenerator,
    request: str,
    *,
    series_dir: Path | None = None,
    count: int | None = None,
    max_shots: int = DEFAULT_MAX_SHOTS,
    style: str | None = None,
    setting: str | None = None,
    character: Character | None = None,
    temperature: float = prompts.GLOBAL_TEMPERATURE,
) -> SeriesSettings:
    """Run the global call; retry once with the error appended, then save the raw answer.

    `count` (the `--count` flag) beats a number named in the request; either one is
    enforced in code, so Gemma cannot drift from it. So is a saved `character`, which
    replaces whatever look the model returns.
    """
    if count is None:
        count = requested_count(request)
    if count is not None and not 1 <= count <= max_shots:
        raise SeriesError(f"count {count} is outside 1 to --max-shots {max_shots}", EXIT_USAGE)

    message = prompts.global_request(
        request,
        count=count,
        style=style,
        setting=setting,
        character=(character.name, character.look) if character else None,
    )

    def ask(user_message: str) -> str:
        return client.complete(
            prompts.GLOBAL_SYSTEM,
            user_message,
            temperature=temperature,
            max_tokens=prompts.GLOBAL_MAX_TOKENS,
        )

    def parse(raw: str) -> SeriesSettings:
        settings = _parse(raw, count=count, max_shots=max_shots)
        # Fixed fields are enforced in code as well as told to the model.
        fixed = {
            k: v
            for k, v in (("style", style), ("setting", setting), ("character", character))
            if v is not None
        }
        return settings.model_copy(update=fixed)

    raw = ask(message)
    try:
        return parse(raw)
    except (ValueError, ValidationError) as first_error:
        raw = ask(prompts.retry_request(message, raw, str(first_error)))
    try:
        return parse(raw)
    except (ValueError, ValidationError) as error:
        detail = str(error)
        if series_dir is not None:
            series_dir.mkdir(parents=True, exist_ok=True)
            (series_dir / INVALID_ANSWER_FILE).write_text(raw)
            detail += f"\nraw answer saved to {series_dir / INVALID_ANSWER_FILE}"
        raise SeriesError(f"gemma's series settings are invalid:\n{detail}", 1) from error
