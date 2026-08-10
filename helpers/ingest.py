#!/usr/bin/env python3
"""Turn a package zip + a folder of generated images into a ready project.

Two jobs, both of which were done by hand for the Colonel Parker video:

  package  read a FULL_PACKAGE zip (script + scene breakdown) and scaffold
           finals/<name>/ with script.txt, a manifest, and one prompt per
           scene ready to paste into Flow.

  images   match the newest images in Downloads to the scenes still missing
           a file, in generation order, and stage them under scenes/.

Nothing is overwritten without --apply, so you can always see the plan first.

    python helpers/ingest.py package --zip "C:/Users/erick/Downloads/X.zip"
    python helpers/ingest.py images  --project finals/colonel_parker
    python helpers/ingest.py images  --project finals/colonel_parker --apply
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS = Path.home() / "Downloads"
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}

# Flow names files after the prompt, and also emits junk from stray text in a
# pasted document. Anything matching these is never a scene image.
JUNK = re.compile(
    r"prompt|scene_prompts|google_flow|nano_banana|16_9|landscape|"
    r"reference_image|generate_|settings|additional_scene",
    re.I)


# ──────────────────────────────────────────────────────────
# images
# ──────────────────────────────────────────────────────────

def recent_images(src: Path, since: datetime | None, limit: int) -> list[Path]:
    files = [p for p in src.iterdir()
             if p.is_file() and p.suffix.lower() in IMG_EXT and not JUNK.search(p.name)]
    if since:
        files = [p for p in files if datetime.fromtimestamp(p.stat().st_mtime) >= since]
    files.sort(key=lambda p: p.stat().st_mtime)
    return files[-limit:] if limit else files


def dedupe_variants(files: list[Path]) -> list[Path]:
    """Flow writes 'name.jpeg' and 'name (1).jpeg' for x2 variants.
    Keep one per base name - the larger file, which is usually the better one."""
    groups: dict[str, list[Path]] = {}
    for p in files:
        base = re.sub(r"\s*\(\d+\)$", "", p.stem)
        base = re.sub(r"_\d{14}$", "", base)
        groups.setdefault(base, []).append(p)
    out = []
    for base, ps in groups.items():
        out.append(max(ps, key=lambda p: p.stat().st_size))
    out.sort(key=lambda p: p.stat().st_mtime)
    return out


def cmd_images(args) -> int:
    proj = args.project.resolve()
    mpath = proj / "manifest.json"
    if not mpath.exists():
        print(f"ERROR: no manifest at {mpath}", file=sys.stderr)
        return 1
    m = json.loads(mpath.read_text(encoding="utf-8"))

    missing = [s for s in m["scenes"] if not (proj / s["image"]).exists()]
    if not missing:
        print(f"All {len(m['scenes'])} scene images already present. Nothing to do.")
        return 0

    since = None
    if args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d %H:%M")

    src = args.source or DOWNLOADS
    found = recent_images(src, since, args.limit or 0)
    if args.dedupe:
        found = dedupe_variants(found)

    print(f"source   : {src}")
    print(f"missing  : {len(missing)} scene(s)")
    print(f"candidates: {len(found)} image(s)"
          + (f" since {args.since}" if args.since else "")
          + (" after variant de-dupe" if args.dedupe else ""))
    print()

    if len(found) < len(missing):
        print(f"WARNING: only {len(found)} image(s) for {len(missing)} missing "
              f"scene(s). Generate more, or narrow with --since / --limit.")
    pairs = list(zip(missing, found[-len(missing):] if len(found) >= len(missing) else found))

    print(f"{'scene':>5}  {'target':<34} source")
    print("-" * 96)
    for s, f in pairs:
        ts = datetime.fromtimestamp(f.stat().st_mtime).strftime("%H:%M")
        print(f"{s['n']:>5}  {s['image']:<34} {ts}  {f.name[:44]}")
    print()

    if not args.apply:
        print("Dry run. Add --apply to copy these into place.")
        print("Order is by generation time, so generate your prompts in scene order.")
        return 0

    for s, f in pairs:
        dest = proj / s["image"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
        print(f"  staged scene {s['n']:>2} <- {f.name}")
    print(f"\n{len(pairs)} image(s) staged. Now run:")
    print(f"  python helpers/make_video.py --project {args.project}")
    return 0


# ──────────────────────────────────────────────────────────
# package
# ──────────────────────────────────────────────────────────

def parse_script(text: str) -> str:
    body = text.split("SCRIPT:", 1)[-1]
    body = re.sub(r"\[[A-Z ]+\]", "\n\n", body)
    parts = [" ".join(p.split()) for p in body.split("\n\n")]
    return "\n\n".join(p for p in parts if p)


def parse_scenes(text: str) -> list[dict]:
    out = []
    chunks = re.split(r"\nIMAGE\s+(\d+)\s*\|", text)
    for i in range(1, len(chunks), 2):
        n, body = int(chunks[i]), chunks[i + 1]

        def grab(tag, nxt):
            mm = re.search(rf"{tag}:\s*(.*?)(?=\n\s*{nxt}:)", body, re.S)
            return " ".join(mm.group(1).split()) if mm else ""

        kb = re.search(r"KEN BURNS:\s*(.*)", body)
        out.append({
            "n": n,
            "era": grab("ERA", "PURPOSE"),
            "overlay": None,
            "prompt": grab("IMAGE PROMPT", "IMAGE SEARCH"),
            "ken_burns_hint": kb.group(1).strip() if kb else "",
        })
    return out


def cmd_package(args) -> int:
    z = args.zip.resolve()
    if not z.exists():
        print(f"ERROR: {z} not found", file=sys.stderr)
        return 1

    name = args.name or re.sub(r"[^a-z0-9]+", "_", z.stem.lower()).strip("_")
    proj = (args.into or (ROOT / "finals")) / name
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "scenes").mkdir(exist_ok=True)

    raw = proj / "_package"
    raw.mkdir(exist_ok=True)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(raw)
    files = [p for p in raw.rglob("*") if p.is_file()]
    print(f"package : {z.name}  ({len(files)} file(s))")

    script_src = next((p for p in files if "script" in p.name.lower()), None)
    scenes_src = next((p for p in files if "scene" in p.name.lower()
                       or "breakdown" in p.name.lower()), None)

    if script_src:
        txt = script_src.read_text(encoding="utf-8", errors="replace")
        body = parse_script(txt)
        (proj / "script.txt").write_text(body + "\n", encoding="utf-8")
        print(f"script  : {len(body.split())} words -> script.txt")
    else:
        print("WARNING: no script file found in the package")

    scenes = parse_scenes(scenes_src.read_text(encoding="utf-8", errors="replace")) \
        if scenes_src else []
    print(f"scenes  : {len(scenes)} parsed"
          + (f" from {scenes_src.name}" if scenes_src else ""))

    tmpl = json.loads((ROOT / "finals" / "colonel_parker" / "manifest.json")
                      .read_text(encoding="utf-8"))
    m = {k: tmpl[k] for k in ("format", "audio", "music", "transitions",
                              "text_overlay", "pronunciation_fixes", "captions")
         if k in tmpl}
    m = {"job_id": name, "title": args.title or name.replace("_", " ").title(),
         "channel": tmpl.get("channel", ""), "niche": tmpl.get("niche", ""), **m}
    m["scenes"] = [{
        "n": s["n"],
        "image": f"scenes/scene_{s['n']:02d}.jpg",
        "era": s["era"][:60],
        "ken_burns": "hold",
        "weight": 100,
        "prompt": s["prompt"],
    } for s in scenes]

    (proj / "manifest.json").write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    print(f"manifest: {proj/'manifest.json'}")

    if scenes:
        sheet = proj / "prompts.txt"
        sheet.write_text("\n\n".join(s["prompt"] for s in scenes if s["prompt"]) + "\n",
                         encoding="ascii", errors="ignore")
        print(f"prompts : {sheet}  ({len(scenes)} prompts, one per line)")

    print(f"\nNext:")
    print(f"  1. generate the prompts in {proj.name}/prompts.txt")
    print(f"  2. python helpers/ingest.py images --project {proj} --dedupe --apply")
    print(f"  3. python helpers/make_video.py --project {proj}")
    return 0


# ──────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("images", help="Stage generated images into a project")
    pi.add_argument("--project", required=True, type=Path)
    pi.add_argument("--source", type=Path, help=f"Default: {DOWNLOADS}")
    pi.add_argument("--since", help='Only images after "YYYY-MM-DD HH:MM"')
    pi.add_argument("--limit", type=int, help="Only the N newest candidates")
    pi.add_argument("--dedupe", action="store_true",
                    help="Collapse Flow x2 variants, keeping the larger file")
    pi.add_argument("--apply", action="store_true")
    pi.set_defaults(func=cmd_images)

    pp = sub.add_parser("package", help="Scaffold a project from a package zip")
    pp.add_argument("--zip", required=True, type=Path)
    pp.add_argument("--name")
    pp.add_argument("--title")
    pp.add_argument("--into", type=Path)
    pp.set_defaults(func=cmd_package)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
