#!/usr/bin/env python3
"""Regenerate a single scene image via Nano Banana (Gemini 2.5 Flash Image).

Unlike helpers/generate_image.py (text prompt only), this passes era-matched
reference photos from the reference library so real-person likeness holds.
Nano Banana is used deliberately: gpt-image-1's /v1/images/edits endpoint
rejects real-person reference photos on safety grounds and is rate-limited
to 5 input-image requests/min.

Usage:
    python helpers/regen_scene.py --prompt "..." -o out.png \
        --refs reference_library/elvis/1955 --variants 2 --aspect 16:9

    # no references (objects/locations)
    python helpers/regen_scene.py --prompt "..." -o out.png --variants 2
"""

from __future__ import annotations

import argparse
import base64
import random
import sys
import time
from pathlib import Path

import requests

MODEL_URL = (
    "https://generativelanguage.googleapis.com/v1beta"
    "/models/gemini-2.5-flash-image:generateContent"
)
EXTS = {".jpg", ".jpeg", ".png", ".webp"}
ROOT = Path(__file__).resolve().parent.parent


def load_key(name: str = "GEMINI_API_KEY") -> str:
    for candidate in [ROOT / ".env", Path(".env")]:
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == name:
                    v = v.strip().strip('"').strip("'")
                    if v:
                        return v
    import os
    v = os.environ.get(name, "")
    if not v:
        sys.exit(f"{name} not found in .env or environment")
    return v


def collect_refs(paths: list[str], limit: int = 4) -> list[Path]:
    """Expand dirs/files into a capped list of reference image paths."""
    out: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            out.extend(sorted(f for f in path.iterdir()
                              if f.is_file() and f.suffix.lower() in EXTS))
        elif path.is_file() and path.suffix.lower() in EXTS:
            out.append(path)
        else:
            print(f"  warn: no usable reference at {p}", file=sys.stderr)
    random.shuffle(out)
    return out[:limit]


def generate(prompt: str, out_path: Path, api_key: str,
             refs: list[Path] | None = None, timeout: int = 120) -> None:
    parts: list[dict] = []
    if refs:
        for ref in refs:
            mime = "image/png" if ref.suffix.lower() == ".png" else "image/jpeg"
            parts.append({"inlineData": {
                "mimeType": mime,
                "data": base64.b64encode(ref.read_bytes()).decode("ascii"),
            }})
        parts.append({"text":
            "The attached reference photographs show the real person who must appear "
            "in this image. Match his facial structure, hairline, jawline, eyes and "
            "period-correct grooming as closely as possible. Do not stylize the face. "
            f"Now generate this scene: {prompt}"
        })
    else:
        parts.append({"text": f"Generate an image: {prompt}"})

    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}}

    r = requests.post(MODEL_URL, json=body, timeout=timeout,
                      headers={"Content-Type": "application/json",
                               "x-goog-api-key": api_key})
    if r.status_code != 200:
        try:
            detail = r.json().get("error", {}).get("message", r.text[:200])
        except Exception:
            detail = r.text[:200]
        raise RuntimeError(f"Gemini API {r.status_code}: {detail}")

    cand = r.json().get("candidates", [{}])[0]
    for part in cand.get("content", {}).get("parts", []):
        if "inlineData" in part:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(base64.b64decode(part["inlineData"]["data"]))
            return
    finish = cand.get("finishReason", "unknown")
    texts = [p["text"] for p in cand.get("content", {}).get("parts", []) if "text" in p]
    raise RuntimeError(
        f"No image returned (finishReason={finish}"
        + (f", text={' '.join(texts)[:200]!r}" if texts else "") + ")"
    )


def fit_aspect(path: Path, aspect: str) -> None:
    """Center-crop to the target aspect ratio in place."""
    if not aspect:
        return
    try:
        from PIL import Image
    except ImportError:
        return
    w_r, h_r = (int(x) for x in aspect.split(":"))
    target = w_r / h_r
    im = Image.open(path).convert("RGB")
    w, h = im.size
    cur = w / h
    if abs(cur - target) < 0.01:
        return
    if cur > target:                      # too wide -> trim sides
        new_w = int(h * target)
        left = (w - new_w) // 2
        im = im.crop((left, 0, left + new_w, h))
    else:                                 # too tall -> trim top/bottom
        new_h = int(w / target)
        top = (h - new_h) // 2
        im = im.crop((0, top, w, top + new_h))
    im.save(path, quality=95)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("-o", "--output", required=True, type=Path,
                    help="Output path. With --variants>1, _v1/_v2 are appended.")
    ap.add_argument("--refs", nargs="*", default=[],
                    help="Reference image files and/or directories")
    ap.add_argument("--max-refs", type=int, default=4)
    ap.add_argument("--variants", type=int, default=1)
    ap.add_argument("--aspect", default="", help='e.g. "16:9" — center-crops output')
    args = ap.parse_args()

    key = load_key()
    refs = collect_refs(args.refs, args.max_refs) if args.refs else []
    if args.refs:
        print(f"references ({len(refs)}):")
        for r in refs:
            print(f"  {r}")
        if not refs:
            print("  WARNING: none found — likeness will be unconditioned")

    ok = 0
    for i in range(1, args.variants + 1):
        out = (args.output if args.variants == 1
               else args.output.with_name(f"{args.output.stem}_v{i}{args.output.suffix}"))
        try:
            generate(args.prompt, out, key, refs)
            fit_aspect(out, args.aspect)
            from PIL import Image
            print(f"  saved {out.name}  {Image.open(out).size}")
            ok += 1
        except Exception as e:
            print(f"  FAILED variant {i}: {e}", file=sys.stderr)
        if i < args.variants:
            time.sleep(2)

    print(f"{ok}/{args.variants} generated")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
