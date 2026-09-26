"""Story 09.3-003: characters saved once and reused by every later series."""

import os
import re
import shutil
from pathlib import Path

from platformdirs import user_data_dir
from pydantic import BaseModel, ValidationError

from lig.series.settings import EXIT_USAGE, Character, SeriesError

CHARACTER_FILE = "character.json"
REFERENCE_FILE = "reference.png"
_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")


class SavedCharacter(BaseModel):
    """What `character.json` holds: the look to reuse, its style and seed, and where it began."""

    name: str
    look: str
    style: str
    seed: int
    source_series: str


def characters_dir() -> Path:
    """`<data dir>/lig/characters`; honours XDG_DATA_HOME on every OS so tests can redirect it."""
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) / "lig" if xdg else Path(user_data_dir("lig"))
    return base / "characters"


def normalize(key: str) -> str:
    """The directory name for a `--character` value; lower-case, no path characters."""
    name = key.strip().lower()
    if not _NAME_RE.fullmatch(name):
        raise SeriesError(
            f"invalid character name {key!r}: use letters, digits, '-' and '_'", EXIT_USAGE
        )
    return name


def _dir(key: str) -> Path:
    return characters_dir() / normalize(key)


def load(key: str) -> SavedCharacter | None:
    """The saved character, or None when there is none under that name."""
    path = _dir(key) / CHARACTER_FILE
    if not path.is_file():
        return None
    try:
        return SavedCharacter.model_validate_json(path.read_text())
    except (ValidationError, ValueError) as error:
        raise SeriesError(f"saved character {path} is unreadable: {error}", 1) from error


def reference_path(key: str) -> Path | None:
    """The saved reference image (anchor mode), when there is one."""
    path = _dir(key) / REFERENCE_FILE
    return path if path.is_file() else None


def save(
    key: str,
    character: Character,
    *,
    style: str,
    seed: int,
    source_series: str,
    reference: Path | None = None,
) -> Path:
    """Write `character.json` (and `reference.png` if given); returns the directory."""
    target = _dir(key)
    target.mkdir(parents=True, exist_ok=True)
    saved = SavedCharacter(
        name=character.name,
        look=character.look,
        style=style,
        seed=seed,
        source_series=source_series,
    )
    (target / CHARACTER_FILE).write_text(saved.model_dump_json(indent=2) + "\n")
    if reference is not None:
        shutil.copyfile(reference, target / REFERENCE_FILE)
    return target


def list_names() -> list[str]:
    root = characters_dir()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / CHARACTER_FILE).is_file())


def remove(key: str) -> bool:
    """Delete a saved character; False when there was none."""
    target = _dir(key)
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True
