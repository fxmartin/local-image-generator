"""Story 09.1-004: one `gemma` call per photo writes that shot's title and scene."""

import time
from collections.abc import Iterator

from pydantic import BaseModel, ValidationError, field_validator

from lig.series import prompts
from lig.series.settings import (
    NonBlank,
    SeriesError,
    SeriesSettings,
    TextGenerator,
    extract_json_object,
)

SCENE_MIN_WORDS = 20
SCENE_MAX_WORDS = 80


class Shot(BaseModel):
    """`plan_seconds` is the wall time of the shot's gemma call(s), recorded in `series.json`.

    `prompt` is the composed image prompt (09.1-003), stored so a re-render needs no LLM call.
    """

    title: NonBlank
    scene: NonBlank
    plan_seconds: float = 0.0
    prompt: str = ""

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("title must not be empty")
        return value

    @field_validator("scene")
    @classmethod
    def _scene_length(cls, value: str) -> str:
        words = len(value.split())
        if not SCENE_MIN_WORDS <= words <= SCENE_MAX_WORDS:
            raise ValueError(
                f"scene must be {SCENE_MIN_WORDS} to {SCENE_MAX_WORDS} words, got {words}"
            )
        return value


def _parse(raw: str) -> Shot:
    data = extract_json_object(raw)
    return Shot.model_validate({"title": data.get("title"), "scene": data.get("scene")})


def plan_shot(
    client: TextGenerator,
    settings: SeriesSettings,
    index: int,
    previous: list[Shot],
    *,
    temperature: float = prompts.SHOT_TEMPERATURE,
) -> Shot:
    """Plan shot `index` (1-based); retry once with the error appended, then raise exit 1."""
    started = time.monotonic()
    message = prompts.shot_request(
        settings.model_dump_json(indent=2),
        index,
        settings.count,
        [(shot.title, shot.scene) for shot in previous],
    )

    def ask(user_message: str) -> str:
        return client.complete(
            prompts.SHOT_SYSTEM,
            user_message,
            temperature=temperature,
            max_tokens=prompts.SHOT_MAX_TOKENS,
        )

    raw = ask(message)
    try:
        shot = _parse(raw)
    except (ValueError, ValidationError) as first_error:
        raw = ask(prompts.retry_request(message, raw, str(first_error)))
        try:
            shot = _parse(raw)
        except (ValueError, ValidationError) as error:
            raise SeriesError(
                f"gemma's scene for shot {index} of {settings.count} is invalid:\n{error}", 1
            ) from error
    return shot.model_copy(update={"plan_seconds": round(time.monotonic() - started, 3)})


def plan_shots(
    client: TextGenerator,
    settings: SeriesSettings,
    *,
    temperature: float = prompts.SHOT_TEMPERATURE,
) -> Iterator[Shot]:
    """Yield shots 1..N lazily, so the caller can render each before the next call.

    A failing shot raises `SeriesError` after the earlier shots were already yielded.
    """
    planned: list[Shot] = []
    for index in range(1, settings.count + 1):
        shot = plan_shot(client, settings, index, planned, temperature=temperature)
        planned.append(shot)
        yield shot
