"""Story 09.2-003: `plan.json`, the reviewable plan a series is rendered from."""

from pathlib import Path

from pydantic import BaseModel, ValidationError, model_validator

from lig.series import compose
from lig.series.settings import EXIT_USAGE, SeriesError, SeriesSettings
from lig.series.shots import Shot

PLAN_FILE = "plan.json"


class SeriesPlan(BaseModel):
    """The global settings plus every shot, so editing a scene needs no `gemma` call."""

    request: str = ""
    settings: SeriesSettings
    shots: list[Shot]

    @model_validator(mode="after")
    def _count_matches(self) -> "SeriesPlan":
        if len(self.shots) != self.settings.count:
            raise ValueError(
                f"settings.count is {self.settings.count} but the plan has {len(self.shots)} shots"
            )
        return self

    def recomposed(self) -> "SeriesPlan":
        """Rebuild every prompt from its fields, so an edited look or scene takes effect."""
        shots = [compose.with_prompt(shot, self.settings) for shot in self.shots]
        return self.model_copy(update={"shots": shots})


def write_plan(out_dir: Path, plan: SeriesPlan) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / PLAN_FILE
    target.write_text(plan.model_dump_json(indent=2))
    return target


def read_plan(path: Path) -> SeriesPlan:
    """Load and validate; a bad file raises `SeriesError` with the usage exit code."""
    try:
        return SeriesPlan.model_validate_json(path.read_text()).recomposed()
    except OSError as error:
        raise SeriesError(f"cannot read plan {path}: {error}", EXIT_USAGE) from error
    except ValidationError as error:
        raise SeriesError(f"invalid plan {path}:\n{error}", EXIT_USAGE) from error


def format_plan(plan: SeriesPlan) -> str:
    """Settings first, then one line per shot with its final prompt."""
    settings = plan.settings
    lines = [
        f"count:     {settings.count}",
        f"character: {settings.character.name}: {settings.character.look}",
        f"style:     {settings.style}",
        f"setting:   {settings.setting}",
    ]
    lines += [f"{n}. {shot.title}: {shot.prompt}" for n, shot in enumerate(plan.shots, start=1)]
    return "\n".join(lines)
