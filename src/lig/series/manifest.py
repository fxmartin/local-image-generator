"""Story 09.2-002: `series.json`, the record that lets a series be reproduced or resumed."""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from lig.series.settings import SeriesSettings

SERIES_FILE = "series.json"
CONTINUITY_PROMPT = "prompt"  # shared look text + one base seed; the only mode so far

ShotStatus = Literal["done", "failed", "skipped"]


class ShotRecord(BaseModel):
    """One shot. `failed` and `skipped` shots keep whatever was known when the series stopped."""

    index: int
    status: ShotStatus
    title: str = ""
    scene: str = ""
    prompt: str = ""
    png: str | None = None
    sidecar: str | None = None
    exit_code: int | None = None
    wall_seconds: float | None = None


class SeriesManifest(BaseModel):
    request: str
    gemma_model: str | None = None
    plan: SeriesSettings
    continuity: str = CONTINUITY_PROMPT
    seed: int
    lig_version: str
    shots: list[ShotRecord] = Field(default_factory=list)


def sidecar_path(png: str) -> str:
    """`lig` writes `<stem>.json` next to `<stem>.png`."""
    return str(Path(png).with_suffix(".json"))


def write_manifest(out_dir: Path, manifest: SeriesManifest) -> None:
    """Atomic, so an interrupted run never leaves a truncated file for the resume step."""
    target = out_dir / SERIES_FILE
    partial = target.with_name(target.name + ".tmp")
    partial.write_text(manifest.model_dump_json(indent=2))
    os.replace(partial, target)


def read_manifest(out_dir: Path) -> SeriesManifest:
    return SeriesManifest.model_validate_json((out_dir / SERIES_FILE).read_text())
