#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


FINAL_SIZE = (1080, 1920)


def _enhance_foreground(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGB")
    image = ImageOps.autocontrast(image, cutoff=1)
    image = ImageEnhance.Sharpness(image).enhance(1.25)
    image = ImageEnhance.Contrast(image).enhance(1.08)
    if image.getbands() == ("R", "G", "B"):
        image = ImageEnhance.Color(image).enhance(1.05)
    return image.filter(ImageFilter.UnsharpMask(radius=1.6, percent=120, threshold=2))


def prepare_photo(src_path: Path, dest_path: Path) -> None:
    with Image.open(src_path) as raw_image:
        foreground = _enhance_foreground(raw_image)

    background = ImageOps.fit(
        foreground,
        FINAL_SIZE,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    ).filter(ImageFilter.GaussianBlur(radius=22))

    contained = ImageOps.contain(
        foreground,
        FINAL_SIZE,
        method=Image.Resampling.LANCZOS,
    )

    canvas = background.copy()
    offset = (
        (FINAL_SIZE[0] - contained.width) // 2,
        (FINAL_SIZE[1] - contained.height) // 2,
    )
    canvas.paste(contained, offset)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest_path, format="PNG", optimize=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upscale and resize local photos to 1080x1920 vertical assets.")
    parser.add_argument("images", nargs="+", help="Input image paths.")
    parser.add_argument("--output-dir", required=True, help="Destination directory for processed PNG files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()

    for index, image_arg in enumerate(args.images, start=1):
        src_path = Path(image_arg).resolve()
        if not src_path.exists():
            raise FileNotFoundError(src_path)
        dest_name = f"{index:02d}_{src_path.stem}.png"
        dest_path = output_dir / dest_name
        prepare_photo(src_path, dest_path)
        print(dest_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
