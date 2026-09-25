"""Deterministic output naming, JSON sidecar and PNG text chunks."""

import io
import os
import re
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo
from pydantic import BaseModel

from lig import __version__
from lig.core.models import EditRequest, ImageResult, Timings, WeightsUsed

DEFAULT_OUTPUT_DIR = Path("outputs")
MAX_SLUG_LEN = 40


class SidecarSchema(BaseModel):
    """Everything needed to tell, later, how an image was made."""

    prompt: str
    negative_prompt: str | None
    seed: int
    steps: int
    size: tuple[int, int]
    guidance: float | None
    engine: str
    engine_version: str
    weights: list[WeightsUsed]
    timings: Timings
    host: str
    lig_version: str
    created_at: str
    source_path: str | None = None
    source_sha256: str | None = None


def slugify(prompt: str) -> str:
    """ASCII, lowercase, hyphen-separated, at most MAX_SLUG_LEN chars."""
    ascii_text = unicodedata.normalize("NFKD", prompt).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower())[:MAX_SLUG_LEN].strip("-")
    return slug or "image"


def _sidecar_for(result: ImageResult, created_at: datetime) -> SidecarSchema:
    req = result.request
    source = isinstance(req, EditRequest)
    return SidecarSchema(
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        seed=req.seed,
        steps=req.steps,
        size=(req.width, req.height),
        guidance=req.guidance,
        engine=result.engine,
        engine_version=result.engine_version,
        weights=result.weights,
        timings=result.timings,
        host=result.host,
        lig_version=__version__,
        created_at=created_at.isoformat(),
        source_path=str(req.reference_image) if source else None,
        source_sha256=req.reference_sha256 if source else None,
    )


def _free_stem(out_dir: Path, stem: str) -> str:
    candidate, n = stem, 1
    while (out_dir / f"{candidate}.png").exists() or (out_dir / f"{candidate}.json").exists():
        n += 1
        candidate = f"{stem}-{n}"
    return candidate


def _atomic_write(target: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _png_with_metadata(png: bytes, sidecar: SidecarSchema, sidecar_name: str) -> bytes:
    info = PngInfo()
    info.add_text("lig:prompt", sidecar.prompt)
    info.add_text("lig:seed", str(sidecar.seed))
    info.add_text("lig:engine", sidecar.engine)
    info.add_text("lig:sidecar", sidecar_name)
    try:
        with Image.open(io.BytesIO(png)) as img:
            img.load()
            buf = io.BytesIO()
            img.save(buf, "PNG", pnginfo=info)
    except OSError as exc:
        raise ValueError(f"engine returned invalid PNG data: {exc}") from exc
    return buf.getvalue()


def write_result(
    result: ImageResult, out_dir: Path | None = None, *, now: datetime | None = None
) -> Path:
    """Write PNG + sidecar into out_dir (created if missing); return the PNG path.

    The sidecar lands first and the PNG last, atomically, so an interrupted run
    never leaves a truncated image next to (or without) its sidecar.
    """
    out_dir = out_dir or DEFAULT_OUTPUT_DIR
    created_at = now or datetime.now()  # local time, per spec
    sidecar = _sidecar_for(result, created_at)
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = f"{created_at:%Y%m%d-%H%M%S}_{slugify(sidecar.prompt)}_s{sidecar.seed}"
    stem = _free_stem(out_dir, stem)
    png_path, json_path = out_dir / f"{stem}.png", out_dir / f"{stem}.json"

    png = _png_with_metadata(result.png, sidecar, json_path.name)
    _atomic_write(json_path, sidecar.model_dump_json(indent=2).encode())
    try:
        _atomic_write(png_path, png)
    except BaseException:
        json_path.unlink(missing_ok=True)
        raise
    return png_path
