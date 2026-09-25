"""Contact sheet: a near-square grid of a batch's renders, each labelled with its seed."""

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

from lig.core.output import _atomic_write

SHEET_TILE_PX = 512  # long edge of each downscaled tile
LABEL_PAD = 4


def grid_shape(count: int) -> tuple[int, int]:
    """(rows, cols) of the smallest near-square grid holding `count` tiles."""
    cols = math.ceil(math.sqrt(count))
    return math.ceil(count / cols), cols


def build_sheet(members: list[tuple[Path, int]], out_dir: Path, batch_id: str) -> Path:
    """Write `<batch_id>_sheet.png` plus a `.json` sidecar listing files and seeds."""
    tiles: list[Image.Image] = []
    for path, _ in members:
        with Image.open(path) as img:
            tile = img.convert("RGB")
        tile.thumbnail((SHEET_TILE_PX, SHEET_TILE_PX))
        tiles.append(tile)

    rows, cols = grid_shape(len(tiles))
    cell_w = max(t.width for t in tiles)
    cell_h = max(t.height for t in tiles)
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "black")
    draw = ImageDraw.Draw(sheet)
    for i, (tile, (_, seed)) in enumerate(zip(tiles, members, strict=True)):
        x, y = (i % cols) * cell_w, (i // cols) * cell_h
        sheet.paste(tile, (x, y))
        label = f"seed {seed}"
        left, top, right, bottom = draw.textbbox((x + LABEL_PAD, y + LABEL_PAD), label)
        draw.rectangle((left - 2, top - 2, right + 2, bottom + 2), fill="black")
        draw.text((x + LABEL_PAD, y + LABEL_PAD), label, fill="white")

    png_path = out_dir / f"{batch_id}_sheet.png"
    sheet.save(png_path, "PNG")
    sidecar = {
        "batch_id": batch_id,
        "members": [{"file": path.name, "seed": seed} for path, seed in members],
    }
    _atomic_write(png_path.with_suffix(".json"), json.dumps(sidecar, indent=2).encode())
    return png_path
