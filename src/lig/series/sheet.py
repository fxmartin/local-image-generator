"""Story 09.2-004: contact sheet of the rendered shots, labelled `N. Title`.

Pillow only, like `lig`'s seed sheet; deliberately no `lig` imports.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SHEET_FILE = "sheet.png"
MIN_SHOTS = 2
TILE_PX = 384
LABEL_H = 28
LABEL_PAD = 6
FONT_PX = 16


def grid_shape(count: int) -> tuple[int, int]:
    """(rows, cols) of the smallest near-square grid: 10 -> 3 rows x 4 cols."""
    cols = math.ceil(math.sqrt(count))
    return math.ceil(count / cols), cols


def build_sheet(shots: list[tuple[int, str, Path]], out_dir: Path) -> Path:
    """Write `sheet.png` from (shot number, title, image path) tuples, in the given order."""
    rows, cols = grid_shape(len(shots))
    cell_h = TILE_PX + LABEL_H
    sheet = Image.new("RGB", (cols * TILE_PX, rows * cell_h), "black")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(FONT_PX)
    for i, (number, title, path) in enumerate(shots):
        x, y = (i % cols) * TILE_PX, (i // cols) * cell_h
        with Image.open(path) as img:
            tile = img.convert("RGB")
        tile.thumbnail((TILE_PX, TILE_PX))
        sheet.paste(tile, (x + (TILE_PX - tile.width) // 2, y + (TILE_PX - tile.height) // 2))
        draw.text((x + LABEL_PAD, y + TILE_PX + LABEL_PAD), f"{number}. {title}", "white", font)
    target = out_dir / SHEET_FILE
    sheet.save(target, "PNG")
    return target
