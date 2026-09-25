"""Resumable, verified artifact download. The only module that opens a socket.

Bytes stream into ``<filename>.part`` while a sha256 is computed on the fly,
so a finished download is verified without a second pass over the file. A
match promotes the ``.part`` to ``<filename>`` and writes the marker; a
mismatch renames it ``<filename>.corrupt`` and writes no marker.
"""

import hashlib
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from lig.models.cache import artifact_status, marker_path
from lig.models.registry import Artifact

# Headroom on top of the download itself, so the disk is never filled to the brim.
DISK_MARGIN_BYTES = 2 * 1024**3
_CHUNK = 1024 * 1024

ProgressCallback = Callable[[int, int], None]  # (bytes on disk so far, expected total)


class DownloadError(RuntimeError):
    """A transfer failed; any ``.part`` file is kept so the next pull can resume."""


class ChecksumMismatch(DownloadError):
    def __init__(self, artifact: Artifact, actual: str, corrupt_path: Path) -> None:
        super().__init__(
            f"sha256 mismatch for {artifact.name}: expected {artifact.sha256.lower()}, "
            f"got {actual}; moved to {corrupt_path}"
        )
        self.expected = artifact.sha256.lower()
        self.actual = actual
        self.corrupt_path = corrupt_path


@dataclass
class PullOutcome:
    artifact: Artifact
    skipped: bool = False
    restarted: bool = False
    warnings: list[str] = field(default_factory=list)


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def remaining_bytes(models_dir: Path, artifacts: list[Artifact], force: bool) -> int:
    """Bytes still to fetch: registry size minus any resumable ``.part`` content."""
    total = 0
    for artifact in artifacts:
        if not force and artifact_status(models_dir, artifact) == "installed":
            continue
        part = models_dir / f"{artifact.filename}.part"
        already = part.stat().st_size if part.is_file() else 0
        total += max(artifact.size_bytes - already, 0)
    return total


def _hash_file(path: Path) -> "hashlib._Hash":
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest


def pull_artifact(
    artifact: Artifact,
    models_dir: Path,
    client: httpx.Client,
    *,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
) -> PullOutcome:
    outcome = PullOutcome(artifact)
    target = models_dir / artifact.filename
    part = models_dir / f"{artifact.filename}.part"
    marker = marker_path(models_dir, artifact)

    if artifact_status(models_dir, artifact) == "installed" and not force:
        outcome.skipped = True
        return outcome
    if force:
        marker.unlink(missing_ok=True)
        target.unlink(missing_ok=True)

    offset = part.stat().st_size if part.is_file() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    try:
        with client.stream("GET", artifact.url, headers=headers, follow_redirects=True) as resp:
            if resp.status_code == 416 and offset:
                # Stale or over-long part: the server cannot serve that range.
                outcome.warnings.append(
                    f"{artifact.name}: server rejected resume offset, restarting from zero"
                )
                part.unlink()
                return _retry_from_zero(artifact, models_dir, client, on_progress, outcome)
            resp.raise_for_status()
            if offset and resp.status_code != 206:
                outcome.warnings.append(
                    f"{artifact.name}: server ignored the Range header, restarting from zero"
                )
                outcome.restarted = True
                offset = 0
            digest = _hash_file(part) if offset else hashlib.sha256()
            done = offset
            with part.open("ab" if offset else "wb") as handle:
                for chunk in resp.iter_bytes(_CHUNK):
                    handle.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, artifact.size_bytes)
    except httpx.HTTPError as exc:
        raise DownloadError(f"download of {artifact.name} failed: {exc}") from exc

    actual = digest.hexdigest()
    if actual != artifact.sha256.lower():
        corrupt = models_dir / f"{artifact.filename}.corrupt"
        part.replace(corrupt)
        raise ChecksumMismatch(artifact, actual, corrupt)
    part.replace(target)
    marker.write_text("")
    return outcome


def _retry_from_zero(
    artifact: Artifact,
    models_dir: Path,
    client: httpx.Client,
    on_progress: ProgressCallback | None,
    outcome: PullOutcome,
) -> PullOutcome:
    retried = pull_artifact(artifact, models_dir, client, on_progress=on_progress)
    retried.warnings = outcome.warnings + retried.warnings
    retried.restarted = True
    return retried
