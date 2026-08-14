"""Download photos and videos from an iCloud shared album link.

Works with public iCloud shared album URLs:
    https://share.icloud.com/photos/<token>
    https://www.icloud.com/photos/#<token>

Downloads all media into <output_dir>/ (defaults to ./icloud_download/).
HEIC photos are optionally converted to JPEG with ffmpeg.

Usage:
    python helpers/download_icloud.py https://share.icloud.com/photos/TOKEN
    python helpers/download_icloud.py https://share.icloud.com/photos/TOKEN -o /path/to/folder
    python helpers/download_icloud.py https://share.icloud.com/photos/TOKEN --no-convert-heic
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# iCloud shared-streams partitions to probe. Apple assigns albums to a partition
# based on the user's Apple ID hash; we don't know which one in advance so we
# probe a range starting at the common ones (41 is default, then 1-50).
PARTITIONS = [41] + list(range(1, 51))

HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://www.icloud.com",
    "Referer": "https://www.icloud.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


def extract_token(url: str) -> str:
    """Parse token from share.icloud.com or www.icloud.com/photos/#... URLs."""
    url = url.strip()
    # https://share.icloud.com/photos/TOKEN
    m = re.search(r"share\.icloud\.com/photos/([A-Za-z0-9_\-]+)", url)
    if m:
        return m.group(1)
    # https://www.icloud.com/photos/#TOKEN
    m = re.search(r"icloud\.com/photos/#([A-Za-z0-9_\-]+)", url)
    if m:
        return m.group(1)
    # Bare token
    if re.fullmatch(r"[A-Za-z0-9_\-]{20,}", url):
        return url
    raise ValueError(f"Cannot extract iCloud album token from: {url!r}")


def _post_json(url: str, payload: dict, timeout: int = 15) -> dict | None:
    """POST JSON payload, return parsed response or None on 404/error."""
    body = json.dumps(payload).encode()
    req = Request(url, data=body, headers=HEADERS, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        if e.code in (404, 421):
            return None
        raise
    except (URLError, OSError):
        return None


def fetch_stream(token: str) -> tuple[dict, str] | None:
    """Try all partitions and return (stream_data, base_url) for the first hit."""
    for p in PARTITIONS:
        pad = f"{p:02d}" if p < 10 else str(p)
        base = f"https://p{pad}-sharedstreams.icloud.com/{token}"
        url = f"{base}/sharedstreams/webstream"
        print(f"  probing partition {pad}…", end=" ", flush=True)
        data = _post_json(url, {"streamCtag": None})
        if data is not None:
            print("✓")
            return data, base
        print("404")
    return None


def fetch_assets(base_url: str, photo_guids: list[str]) -> dict | None:
    """Fetch download URLs for a list of photo GUIDs."""
    url = f"{base_url}/sharedstreams/webassets"
    return _post_json(url, {"photoGuids": photo_guids})


def download_file(url: str, dest: Path, timeout: int = 120) -> bool:
    """Download a single file. Returns True on success."""
    req = Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
    try:
        with urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"    ERROR downloading {dest.name}: {e}")
        dest.unlink(missing_ok=True)
        return False


def heic_to_jpeg(src: Path, dst: Path) -> bool:
    """Convert HEIC → JPEG using ffmpeg. Returns True on success."""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), "-q:v", "2", str(dst)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Download an iCloud shared album")
    ap.add_argument("url", help="iCloud share URL or token")
    ap.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("icloud_download"),
        help="Output directory (default: ./icloud_download)",
    )
    ap.add_argument(
        "--no-convert-heic",
        action="store_true",
        help="Keep HEIC files instead of converting to JPEG",
    )
    ap.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of GUIDs per webassets request (default: 50)",
    )
    args = ap.parse_args()

    try:
        token = extract_token(args.url)
    except ValueError as e:
        sys.exit(str(e))

    print(f"token: {token}")
    print(f"output: {args.output.resolve()}")
    print()

    # ── 1. Fetch stream index ─────────────────────────────────────────────────
    print("Fetching album index…")
    result = fetch_stream(token)
    if result is None:
        print()
        print("ERROR: Album not found on any partition (all returned 404).")
        print()
        print("Possible causes:")
        print("  • The shared link requires you to be signed in to iCloud")
        print("  • The album was set to 'Private' or deleted by the owner")
        print("  • Apple has rotated this link's token")
        print()
        print("Workaround — download locally on a Mac or iPhone:")
        print("  1. Open the share link in Safari on a Mac/iPhone")
        print("  2. Select All  →  Download  (Mac: ⌘A then the download button)")
        print("  3. Copy the downloaded folder to this machine and run:")
        print("     python helpers/ken_burns.py <photos_folder>/ -o clips/ --batch")
        sys.exit(1)

    stream, base_url = result
    photos: list[dict] = stream.get("photos", [])
    print(f"found {len(photos)} item(s) in album")
    if not photos:
        print("Album is empty.")
        return

    args.output.mkdir(parents=True, exist_ok=True)

    # ── 2. Batch-fetch download URLs ─────────────────────────────────────────
    guids = [p["photoGuid"] for p in photos]
    guid_to_photo = {p["photoGuid"]: p for p in photos}
    all_assets: dict[str, dict] = {}

    for i in range(0, len(guids), args.batch_size):
        batch = guids[i : i + args.batch_size]
        print(f"fetching download URLs for items {i+1}–{i+len(batch)}…")
        assets_resp = fetch_assets(base_url, batch)
        if assets_resp is None:
            print("  WARNING: webassets request failed for this batch, skipping")
            continue
        for guid, asset_info in (assets_resp.get("items") or {}).items():
            all_assets[guid] = asset_info

    # ── 3. Download each item ─────────────────────────────────────────────────
    ok = 0
    skip = 0
    for idx, photo in enumerate(photos, start=1):
        guid = photo["photoGuid"]
        asset = all_assets.get(guid)
        if asset is None:
            print(f"[{idx}/{len(photos)}] no download URL for {guid[:12]}… — skipping")
            skip += 1
            continue

        # Prefer original > medium derivative; fall back to first available
        url: str | None = None
        ext = "jpg"
        for deriv_key in ("original", "medium", "thumb"):
            deriv = (asset.get("derivatives") or {}).get(deriv_key)
            if deriv and deriv.get("url"):
                url = deriv["url"]
                cs = deriv.get("checksum", "")
                if cs.endswith(".MOV"):
                    ext = "mov"
                elif cs.endswith(".MP4"):
                    ext = "mp4"
                elif cs.lower().endswith(".heic"):
                    ext = "heic"
                break

        if url is None:
            print(f"[{idx}/{len(photos)}] no usable URL — skipping")
            skip += 1
            continue

        filename = f"{idx:04d}_{guid[:8]}.{ext}"
        dest = args.output / filename
        if dest.exists():
            print(f"[{idx}/{len(photos)}] already exists: {filename}")
            ok += 1
            continue

        print(f"[{idx}/{len(photos)}] {filename}…", end=" ", flush=True)
        if download_file(url, dest):
            print("ok")
            ok += 1

            # Convert HEIC → JPEG unless suppressed
            if ext == "heic" and not args.no_convert_heic:
                jpeg_dest = dest.with_suffix(".jpg")
                if heic_to_jpeg(dest, jpeg_dest):
                    dest.unlink()
                    print(f"         → converted to {jpeg_dest.name}")
        else:
            skip += 1

        # Be gentle with Apple's servers
        time.sleep(0.1)

    print()
    print(f"done: {ok} downloaded, {skip} skipped → {args.output.resolve()}")
    if ok > 0:
        print()
        print("Next steps:")
        print(f"  # Convert photos to Ken Burns clips (if any photos):")
        print(f"  python helpers/ken_burns.py {args.output}/ -o {args.output}/clips/ --batch --effect ken_burns")
        print(f"  # Then edit as usual with the video-use workflow")


if __name__ == "__main__":
    main()
