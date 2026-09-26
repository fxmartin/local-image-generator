"""Story 09.1-003: build each shot's final prompt in code, never with `gemma`."""

from lig.series.settings import SeriesSettings
from lig.series.shots import Shot


def compose_prompt(
    settings: SeriesSettings,
    scene: str,
    *,
    prefix: str | None = None,
    suffix: str | None = None,
) -> str:
    """`"{look} {scene} Style: {style}"`, with the optional prefix/suffix added verbatim.

    The look and style are copied word for word so the image model sees the same
    identity and style in every shot; the setting is left out because the scene places it.
    """
    core = f"{settings.character.look} {scene} Style: {settings.style}"
    return " ".join(part for part in (prefix, core, suffix) if part)


def with_prompt(
    shot: Shot,
    settings: SeriesSettings,
    *,
    prefix: str | None = None,
    suffix: str | None = None,
) -> Shot:
    """The shot with its composed prompt stored, so a re-render needs no LLM call."""
    return shot.model_copy(
        update={"prompt": compose_prompt(settings, shot.scene, prefix=prefix, suffix=suffix)}
    )
