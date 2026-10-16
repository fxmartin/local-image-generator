"""Contact sheet of a batch's renders, each tile labelled (by seed for `seeds`, size for `sizes`).

Same-size tiles go in a near-square grid; tiles of different sizes go in one row at a
common height, so landscape and portrait framings sit side by side without empty cells.
"""

import json
import math
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw

from lig.core.output import _atomic_write

SHEET_TILE_PX = 512  # long edge of each downscaled tile
LABEL_PAD = 4


def grid_shape(count: int) -> tuple[int, int]:
    """(rows, cols) of the smallest near-square grid holding `count` tiles."""
    cols = math.ceil(math.sqrt(count))
    return math.ceil(count / cols), cols


def seed_label(_path: Path, seed: int) -> str:
    return f"seed {seed}"


Layout = tuple[list[Image.Image], list[tuple[int, int]], tuple[int, int]]


def _grid(renders: list[Image.Image]) -> Layout:
    """Same-size tiles, long edge capped at SHEET_TILE_PX, in a near-square grid."""
    tiles = []
    for render in renders:
        tile = render.copy()
        tile.thumbnail((SHEET_TILE_PX, SHEET_TILE_PX))
        tiles.append(tile)
    rows, cols = grid_shape(len(tiles))
    cell_w, cell_h = tiles[0].size
    origins = [((i % cols) * cell_w, (i // cols) * cell_h) for i in range(len(tiles))]
    return tiles, origins, (cols * cell_w, rows * cell_h)


def _row(renders: list[Image.Image]) -> Layout:
    """Mixed sizes in one row at the shortest height, capped at SHEET_TILE_PX, never enlarged."""
    height = min(SHEET_TILE_PX, *(r.height for r in renders))
    tiles = [r.resize((round(r.width * height / r.height), height)) for r in renders]
    origins, x = [], 0
    for tile in tiles:
        origins.append((x, 0))
        x += tile.width
    return tiles, origins, (x, height)


def build_sheet(
    members: list[tuple[Path, int]],
    out_dir: Path,
    batch_id: str,
    label: Callable[[Path, int], str] = seed_label,
) -> Path:
    """Write `<batch_id>_sheet.png` plus a `.json` sidecar listing files, seeds and labels.

    `label(path, seed)` names each tile; `lig seeds` labels by seed, `lig sizes` by size.
    """
    renders: list[Image.Image] = []
    for path, _ in members:
        with Image.open(path) as img:
            renders.append(img.convert("RGB"))

    if len({r.size for r in renders}) == 1:
        tiles, origins, size = _grid(renders)
    else:
        tiles, origins, size = _row(renders)
    sheet = Image.new("RGB", size, "black")
    draw = ImageDraw.Draw(sheet)
    labels = [label(path, seed) for path, seed in members]
    for tile, (x, y), text in zip(tiles, origins, labels, strict=True):
        sheet.paste(tile, (x, y))
        left, top, right, bottom = draw.textbbox((x + LABEL_PAD, y + LABEL_PAD), text)
        draw.rectangle((left - 2, top - 2, right + 2, bottom + 2), fill="black")
        draw.text((x + LABEL_PAD, y + LABEL_PAD), text, fill="white")

    png_path = out_dir / f"{batch_id}_sheet.png"
    sheet.save(png_path, "PNG")
    sidecar = {
        "batch_id": batch_id,
        "members": [
            {"file": path.name, "seed": seed, "label": text}
            for (path, seed), text in zip(members, labels, strict=True)
        ],
    }
    _atomic_write(png_path.with_suffix(".json"), json.dumps(sidecar, indent=2).encode())
    return png_path
