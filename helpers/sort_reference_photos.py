#!/usr/bin/env python3
"""Sort reference photos into reference_library/<niche>/<year>/ folders by filename.

Reads year hints from filenames and fans each photo out into every year folder
it covers, so bot.py's Tier-1 exact-year lookup hits as often as possible.

Filename patterns understood (first match wins):
    elvis_1968_1969_priscilla_hug.jpg   -> 1968, 1969        (range)
    elvis_1956_1960_montage.jpg         -> 1956 ... 1960     (range)
    elvis_1960_gi_blues_army.jpg        -> 1960              (single year)
    elvis_1970s_limo_sunroof.jpg        -> 1970s/            (decade bucket)
    elvis_age_progression_guide.jpg     -> <niche>/ root     (no year -> flat)

Flat files and the 1970s/ bucket still get picked up:
  - "1970s" matches bot.py Tier-2 decade lookup (subfolder starting "197")
  - flat root files are included in Tier-3 fallback

Usage:
    python helpers/sort_reference_photos.py --niche elvis --inbox reference_library/elvis/_inbox
    python helpers/sort_reference_photos.py --niche elvis --inbox ~/Downloads/elvis_reference_pool
    python helpers/sort_reference_photos.py --niche elvis --inbox ... --dry-run
    python helpers/sort_reference_photos.py --niche elvis --inbox ... --move
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}

# bot.py's _detect_year only matches 1950-2009, but we still file older photos
# into their own year folders so they are organised and reachable via Tier 3.
MIN_YEAR, MAX_YEAR = 1930, 2029

RANGE_RE = re.compile(r"(?<!\d)(19\d{2}|20[0-2]\d)[_\-](19\d{2}|20[0-2]\d)(?!\d)")
DECADE_RE = re.compile(r"(?<!\d)(19\d0|20[0-2]0)s(?!\d)")
SINGLE_RE = re.compile(r"(?<!\d)(19\d{2}|20[0-2]\d)(?!\d)")

# Filenames containing any of these are skipped entirely.
SKIP_TOKENS = ("low_confidence", "do_not_use")


def targets_for(name: str) -> list[str]:
    """Return the list of subfolder names this file should land in.

    An empty list means 'leave flat in the niche root'.
    """
    stem = Path(name).stem.lower()

    m = RANGE_RE.search(stem)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > b:
            a, b = b, a
        if MIN_YEAR <= a <= MAX_YEAR and MIN_YEAR <= b <= MAX_YEAR and b - a <= 12:
            return [str(y) for y in range(a, b + 1)]

    m = DECADE_RE.search(stem)
    if m:
        return [f"{m.group(1)}s"]

    m = SINGLE_RE.search(stem)
    if m:
        y = int(m.group(1))
        if MIN_YEAR <= y <= MAX_YEAR:
            return [str(y)]

    return []


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--niche", required=True, help="Niche name, e.g. elvis or mj")
    ap.add_argument("--inbox", required=True, type=Path, help="Folder of unsorted photos")
    ap.add_argument("--library", type=Path, default=root / "reference_library",
                    help="Reference library root (default: reference_library/ beside this repo)")
    ap.add_argument("--move", action="store_true",
                    help="Move instead of copy (only valid when a file has exactly one target)")
    ap.add_argument("--dry-run", action="store_true", help="Print the plan, change nothing")
    args = ap.parse_args()

    inbox = args.inbox.expanduser().resolve()
    if not inbox.is_dir():
        print(f"ERROR: inbox not found: {inbox}", file=sys.stderr)
        return 1

    niche_dir = (args.library / args.niche.strip().lower()).resolve()
    niche_dir.mkdir(parents=True, exist_ok=True)

    photos = sorted(p for p in inbox.rglob("*") if p.is_file() and p.suffix.lower() in EXTS)
    if not photos:
        print(f"No images found in {inbox}")
        return 0

    placed = skipped = flat = 0
    for src in photos:
        if any(tok in src.name.lower() for tok in SKIP_TOKENS) or \
           any(tok in str(src.parent).lower() for tok in SKIP_TOKENS):
            print(f"  skip (low confidence)  {src.name}")
            skipped += 1
            continue

        years = targets_for(src.name)
        dests = [niche_dir / y / src.name for y in years] or [niche_dir / src.name]
        if not years:
            flat += 1

        label = ", ".join(years) if years else "(flat root)"
        print(f"  {src.name}  ->  {label}")

        if args.dry_run:
            placed += 1
            continue

        for i, dest in enumerate(dests):
            dest.parent.mkdir(parents=True, exist_ok=True)
            if args.move and len(dests) == 1:
                shutil.move(str(src), str(dest))
            else:
                shutil.copy2(src, dest)
        placed += 1

    verb = "would place" if args.dry_run else "placed"
    print(f"\n{verb} {placed} photo(s) into {niche_dir}"
          f"  ({flat} flat, {skipped} skipped)")

    if not args.dry_run:
        print("\nLibrary now holds:")
        for sub in sorted(niche_dir.iterdir()):
            if sub.is_dir():
                n = sum(1 for p in sub.iterdir() if p.is_file() and p.suffix.lower() in EXTS)
                if n:
                    print(f"  {sub.name:<8} {n} photo(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
