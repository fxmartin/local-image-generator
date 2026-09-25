"""Weight cache: where artifacts live on disk and what state each one is in.

Status is derived from files alone: a ``<filename>.part`` means a download
is in flight or was interrupted; a ``<filename>.sha256.ok`` marker (written by
verification) means the checksum was confirmed.
"""

import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from lig.models.registry import Artifact, Registry

CHUNK = 1024 * 1024

Status = Literal["installed", "missing", "partial", "unverified"]


def ensure_models_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def marker_path(models_dir: Path, artifact: Artifact) -> Path:
    return models_dir / f"{artifact.filename}.sha256.ok"


def artifact_status(models_dir: Path, artifact: Artifact) -> Status:
    if (models_dir / f"{artifact.filename}.part").exists():
        return "partial"
    if not (models_dir / artifact.filename).is_file():
        return "missing"
    return "installed" if marker_path(models_dir, artifact).exists() else "unverified"


def _dir_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def build_report(registry: Registry, models_dir: Path, engine: str | None = None) -> dict[str, Any]:
    artifacts = [a for a in registry.artifacts if engine is None or engine in a.engines]
    return {
        "models_dir": str(models_dir),
        "artifacts": [
            {
                "name": a.name,
                "role": a.role,
                "engines": a.engines,
                "size_bytes": a.size_bytes,
                "license": a.license,
                "status": artifact_status(models_dir, a),
            }
            for a in artifacts
        ],
        "cache_bytes": _dir_bytes(models_dir),
        "free_bytes": shutil.disk_usage(models_dir).free,
    }


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def hash_file(path: Path, on_progress: Callable[[int], None] | None = None) -> "hashlib._Hash":
    """sha256 of ``path``, shared by ``pull`` (resume) and ``verify``."""
    digest = hashlib.sha256()
    done = 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done)
    return digest


def verify_artifact(
    models_dir: Path, artifact: Artifact, on_progress: Callable[[int], None] | None = None
) -> str | None:
    """Re-hash an installed file. Returns the actual digest on mismatch, else None.

    A mismatch removes the ``.ok`` marker so the file no longer reads as installed;
    a match (re)writes it.
    """
    actual = hash_file(models_dir / artifact.filename, on_progress).hexdigest()
    marker = marker_path(models_dir, artifact)
    if actual == artifact.sha256.lower():
        marker.write_text("")
        return None
    marker.unlink(missing_ok=True)
    return actual


def artifact_files(models_dir: Path, artifact: Artifact) -> list[Path]:
    """Every on-disk file belonging to ``artifact`` (weights, marker, partial/corrupt leftovers)."""
    candidates = [
        models_dir / artifact.filename,
        marker_path(models_dir, artifact),
        models_dir / f"{artifact.filename}.part",
        models_dir / f"{artifact.filename}.corrupt",
    ]
    return [p for p in candidates if p.is_file()]
