"""Build a single-image contact-sheet preview of a selected scene image set.

Used by the Task 6 Telegram approval gate so a human can see the full set of
images a weak-match run picked before deciding whether to approve it.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

CANVAS_MAX_WIDTH = 1080
TILE_ASPECT_RATIO = 16 / 9  # landscape tiles read better in a Telegram preview


def build_contact_sheet(image_paths: list[Path], output_path: Path, labels: list[str]) -> Path:
    """Compose `image_paths` into a single grid image with `labels` overlaid.

    Grid size scales with the number of images instead of capping at a fixed
    count, so a full 15-scene run still produces one complete preview.
    """
    paths = [Path(p) for p in image_paths]
    if not paths:
        raise ValueError("build_contact_sheet requires at least one image")

    count = len(paths)
    columns = max(1, math.ceil(math.sqrt(count)))
    rows = max(1, math.ceil(count / columns))

    tile_w = CANVAS_MAX_WIDTH // columns
    tile_h = max(1, int(tile_w / TILE_ASPECT_RATIO))

    canvas = Image.new("RGB", (tile_w * columns, tile_h * rows), "black")
    draw = ImageDraw.Draw(canvas)

    for index, image_path in enumerate(paths):
        label = labels[index] if index < len(labels) else f"Scene {index + 1}"
        x = (index % columns) * tile_w
        y = (index // columns) * tile_h
        try:
            with Image.open(image_path) as img:
                thumb = img.convert("RGB").resize((tile_w, tile_h))
                canvas.paste(thumb, (x, y))
        except Exception:
            # Missing/corrupt source image — leave the tile black so the
            # preview still renders and the gap is visible to the reviewer.
            pass
        draw.text((x + 12, y + 12), label, fill="white")
        draw.rectangle([x, y, x + tile_w - 1, y + tile_h - 1], outline="gray")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return output_path
