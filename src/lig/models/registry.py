"""Weight registry: every artifact an engine may need, validated on load.

The registry is data (``registry.yaml``), so adapters resolve weights by
role via :meth:`Registry.set_for` instead of hardcoding paths. Loading is
pure file I/O; nothing here touches the network.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

Role = Literal["transformer", "text_encoder", "vae", "mmproj", "bundle"]

DEFAULT_REGISTRY_PATH = Path(__file__).with_name("registry.yaml")
# A set is complete with a self-contained bundle, or with all of these roles.
_REQUIRED_ROLES = ("transformer", "text_encoder", "vae")


class RegistryError(ValueError):
    """The registry file is unreadable, invalid, or cannot satisfy a request."""


class Artifact(BaseModel):
    name: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    size_bytes: int = Field(ge=0)
    engines: list[str] = Field(min_length=1)
    role: Role
    license: str = Field(min_length=1)
    # Explicit rather than derived from repo/filename so non-HF mirrors work.
    url: str = Field(min_length=1)


class ArtifactSet(BaseModel):
    engine: str = Field(min_length=1)
    platforms: list[str] | None = None  # None: every platform
    artifacts: list[str] = Field(min_length=1)


class Registry(BaseModel):
    artifacts: list[Artifact]
    sets: dict[str, ArtifactSet] = {}

    def get(self, name: str) -> Artifact:
        for artifact in self.artifacts:
            if artifact.name == name:
                return artifact
        raise RegistryError(f"unknown artifact '{name}'")

    def set_for(self, engine: str, platform: str) -> list[Artifact]:
        """Ordered artifacts ``engine`` needs on ``platform``; raises if a role is missing."""
        for set_name, artifact_set in self.sets.items():
            if artifact_set.engine != engine:
                continue
            if artifact_set.platforms is not None and platform not in artifact_set.platforms:
                continue
            resolved = [self.get(name) for name in artifact_set.artifacts]
            roles = {a.role for a in resolved}
            if "bundle" not in roles:
                missing = [r for r in _REQUIRED_ROLES if r not in roles]
                if missing:
                    raise RegistryError(
                        f"set '{set_name}' for engine '{engine}' is missing role(s): "
                        + ", ".join(missing)
                    )
            return resolved
        raise RegistryError(f"no artifact set for engine '{engine}' on platform '{platform}'")


def _describe(errors: list, raw: dict) -> str:
    """Render pydantic errors naming the artifact and field that failed."""
    parts = []
    for err in errors:
        loc = err["loc"]
        if loc and loc[0] == "artifacts" and len(loc) >= 3:
            entry = raw["artifacts"][loc[1]]
            label = entry.get("name", f"#{loc[1]}") if isinstance(entry, dict) else f"#{loc[1]}"
            where = f"artifact '{label}' field '{'.'.join(map(str, loc[2:]))}'"
        else:
            where = ".".join(map(str, loc)) or "registry"
        parts.append(f"{where}: {err['msg']}")
    return "; ".join(parts)


def load_registry(path: Path | None = None) -> Registry:
    """Load and validate a registry file (the packaged one by default)."""
    path = path or DEFAULT_REGISTRY_PATH
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryError(f"cannot read registry {path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("artifacts"), list):
        raise RegistryError(f"registry {path} must be a mapping with an 'artifacts' list")
    try:
        registry = Registry.model_validate(raw)
    except ValidationError as exc:
        raise RegistryError(_describe(exc.errors(), raw)) from exc

    seen: set[str] = set()
    for artifact in registry.artifacts:
        if artifact.name in seen:
            raise RegistryError(f"duplicate artifact name '{artifact.name}'")
        seen.add(artifact.name)
    for set_name, artifact_set in registry.sets.items():
        for name in artifact_set.artifacts:
            if name not in seen:
                raise RegistryError(f"set '{set_name}' references unknown artifact '{name}'")
    return registry
