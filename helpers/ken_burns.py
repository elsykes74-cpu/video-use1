"""Convert a still image to a video clip with Ken Burns zoom/pan effect.

Useful for turning photos into cinematic video clips compatible with the
video-use EDL pipeline. Output MP4 includes a silent audio track so it
can be used as a video source in edl.json without modification.

Usage:
    python helpers/ken_burns.py photo.jpg -o clip.mp4
    python helpers/ken_burns.py photo.jpg -o clip.mp4 --duration 7 --effect zoom_in
    python helpers/ken_burns.py photo.jpg -o clip.mp4 --effect ken_burns --size 1080x1920
    python helpers/ken_burns.py photos/ -o clips/ --batch --effect zoom_in

Effects:
    zoom_in     Slow zoom into center (default). Classic talking-head or portrait reveal.
    zoom_out    Start zoomed in, pull back to wide. Good for establishing shots.
    pan_right   Pan left to right at fixed zoom. Good for wide landscape photos.
    pan_left    Pan right to left at fixed zoom.
    pan_up      Pan bottom to top (reveal style). Good for tall portraits.
    ken_burns   Zoom in + subtle rightward drift. Classic PBS documentary feel.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}

# Effect definitions. Variables available in FFmpeg zoompan expressions:
#   on   = output frame number (0-indexed)
#   zoom = current frame's zoom factor (the z expression result)
#   iw/ih = input width/height (of the scaled/cropped source)
#   {n}  = substituted as int(duration * fps) - 1
EFFECTS: dict[str, dict[str, str]] = {
    "zoom_in": {
        "z": "1+on*0.25/{n}",           # 1.0 → 1.25
        "x": "iw/2-(iw/zoom/2)",
        "y": "ih/2-(ih/zoom/2)",
    },
    "zoom_out": {
        "z": "1.25-on*0.25/{n}",        # 1.25 → 1.0
        "x": "iw/2-(iw/zoom/2)",
        "y": "ih/2-(ih/zoom/2)",
    },
    "pan_right": {
        "z": "1.15",
        "x": "on*(iw-iw/zoom)/{n}",     # left edge → right edge
        "y": "ih/2-(ih/zoom/2)",
    },
    "pan_left": {
        "z": "1.15",
        "x": "(iw-iw/zoom)*(1-on/{n})", # right edge → left edge
        "y": "ih/2-(ih/zoom/2)",
    },
    "pan_up": {
        "z": "1.15",
        "x": "iw/2-(iw/zoom/2)",
        "y": "(ih-ih/zoom)*(1-on/{n})", # bottom → top
    },
    "ken_burns": {
        # Start slightly zoomed, zoom in more with a subtle rightward drift.
        # Mirrors the signature PBS documentary look.
        "z": "1.1+on*0.15/{n}",         # 1.1 → 1.25
        "x": "(iw-iw/zoom)/2+on*iw*0.02/{n}",
        "y": "ih/2-(ih/zoom/2)",
    },
}


def build_clip(
    image_path: Path,
    output_path: Path,
    effect: str = "zoom_in",
    duration: float = 6.0,
    fps: int = 24,
    width: int = 1920,
    height: int = 1080,
) -> None:
    if effect not in EFFECTS:
        raise ValueError(f"Unknown effect '{effect}'. Choose: {', '.join(sorted(EFFECTS))}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    n = max(1, int(duration * fps) - 1)
    e = EFFECTS[effect]
    z = e["z"].replace("{n}", str(n))
    x = e["x"].replace("{n}", str(n))
    y = e["y"].replace("{n}", str(n))

    # Scale to fill output size (upscale if needed), then center-crop.
    scale_crop = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )
    zoompan = (
        f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps}"
    )
    vf = f"{scale_crop},{zoompan},format=yuv420p"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(fps), "-i", str(image_path),
        "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo",
        "-map", "0:v", "-map", "1:a",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "64k", "-ar", "48000",
        "-t", str(duration),
        "-movflags", "+faststart",
        str(output_path),
    ]
    print(f"  {image_path.name} → {output_path.name}  ({effect}, {duration}s, {width}×{height})")
    subprocess.run(cmd, check=True, stderr=subprocess.PIPE)


def batch_process(
    input_dir: Path,
    output_dir: Path,
    effect: str,
    duration: float,
    fps: int,
    width: int,
    height: int,
) -> list[Path]:
    images = sorted(
        p for p in input_dir.iterdir()
        if p.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not images:
        print(f"no images found in {input_dir}")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    print(f"batch: {len(images)} image(s) → {output_dir}/")
    for img in images:
        out = output_dir / (img.stem + ".mp4")
        build_clip(img, out, effect=effect, duration=duration, fps=fps, width=width, height=height)
        outputs.append(out)
    return outputs


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Convert a still image to a Ken Burns video clip",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(f"  {k}" for k in sorted(EFFECTS)),
    )
    ap.add_argument("input", type=Path, nargs="?", help="Image file or directory (with --batch)")
    ap.add_argument("-o", "--output", type=Path, help="Output MP4 or directory (with --batch)")
    ap.add_argument("--effect", choices=sorted(EFFECTS), default="zoom_in", help="Motion effect (default: zoom_in)")
    ap.add_argument("--duration", type=float, default=6.0, help="Clip duration in seconds (default: 6.0)")
    ap.add_argument("--fps", type=int, default=24, help="Frame rate (default: 24)")
    ap.add_argument("--size", default="1920x1080", help="Output size WxH (default: 1920x1080, use 1080x1920 for TikTok/Reels)")
    ap.add_argument("--batch", action="store_true", help="Process all images in input directory → output directory")
    ap.add_argument("--list-effects", action="store_true", help="List available effects and exit")
    args = ap.parse_args()

    if args.list_effects:
        for name in sorted(EFFECTS):
            print(name)
        return

    if not args.input or not args.output:
        ap.error("input and -o/--output are required unless using --list-effects")

    try:
        w_str, h_str = args.size.lower().split("x")
        width, height = int(w_str), int(h_str)
    except (ValueError, AttributeError):
        sys.exit(f"invalid --size '{args.size}': expected WxH, e.g. 1920x1080")

    if args.batch:
        if not args.input.is_dir():
            sys.exit(f"--batch requires a directory as input, got: {args.input}")
        batch_process(args.input, args.output, args.effect, args.duration, args.fps, width, height)
    else:
        if not args.input.exists():
            sys.exit(f"image not found: {args.input}")
        if args.input.suffix.lower() not in IMAGE_EXTENSIONS:
            print(f"warning: '{args.input.suffix}' may not be a supported image format")
        build_clip(args.input, args.output, effect=args.effect, duration=args.duration,
                   fps=args.fps, width=width, height=height)

    print("done")


if __name__ == "__main__":
    main()
