"""Download YouTube videos for reference material.

Downloads to reference/<slug>/ with metadata JSON alongside the video.
Supports single URLs, playlists, and search queries.

Usage:
    python helpers/download_reference.py "https://youtu.be/xxxxx"
    python helpers/download_reference.py "MJ HIStory tour fan stage" --search
    python helpers/download_reference.py "https://youtu.be/xxxxx" --audio-only
    python helpers/download_reference.py "https://youtube.com/playlist?list=xxx" --max 5
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
REF_DIR = ROOT / "reference"


def _load_env() -> None:
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:50]


def _check_ytdlp() -> str:
    for candidate in ["yt-dlp", "yt_dlp"]:
        try:
            subprocess.run([candidate, "--version"], capture_output=True, check=True)
            return candidate
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    # Try installing
    print("[download] yt-dlp not found — installing...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "yt-dlp"], check=True)
    return "yt-dlp"


def download(
    url_or_query: str,
    search: bool = False,
    audio_only: bool = False,
    max_results: int = 1,
    quality: str = "best[height<=1080]",
) -> list[dict]:
    """Download video(s) and return list of metadata dicts."""

    ytdlp = _check_ytdlp()
    REF_DIR.mkdir(exist_ok=True)

    if search:
        source = f"ytsearch{max_results}:{url_or_query}"
        out_slug = _slug(url_or_query)
    else:
        source = url_or_query
        out_slug = _slug(url_or_query.split("?")[0].split("/")[-1])

    out_dir = REF_DIR / out_slug
    out_dir.mkdir(exist_ok=True)

    # Output template
    outtmpl = str(out_dir / "%(title)s [%(id)s].%(ext)s")

    cmd = [
        ytdlp,
        source,
        "--output", outtmpl,
        "--write-info-json",
        "--write-thumbnail",
        "--no-playlist" if not search and "playlist" not in url_or_query else "--yes-playlist",
        "--max-downloads", str(max_results),
    ]

    if audio_only:
        cmd += [
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
        ]
    else:
        cmd += [
            "--format", quality,
            "--merge-output-format", "mp4",
        ]

    print(f"[download] Source: {source}")
    print(f"[download] Output: {out_dir}/")
    print(f"[download] Mode: {'audio only' if audio_only else 'video'}")

    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode not in (0, 101):  # 101 = max downloads reached
        print(f"[download] Warning: yt-dlp exited with code {result.returncode}")

    # Collect metadata from .info.json files
    metadata = []
    for info_file in sorted(out_dir.glob("*.info.json")):
        try:
            data = json.loads(info_file.read_text())
            entry = {
                "title": data.get("title", ""),
                "uploader": data.get("uploader", ""),
                "duration": data.get("duration", 0),
                "view_count": data.get("view_count", 0),
                "upload_date": data.get("upload_date", ""),
                "url": data.get("webpage_url", ""),
                "description": (data.get("description", "") or "")[:500],
                "local_path": str(next(out_dir.glob(f"*{data.get('id', '')}*.mp4"), info_file)),
            }
            metadata.append(entry)
            print(f"  ✓ {entry['title']} ({entry['duration']//60}:{entry['duration']%60:02d})")
        except Exception:
            pass

    # Write summary JSON
    summary_path = out_dir / "_summary.json"
    summary_path.write_text(json.dumps({
        "query": url_or_query,
        "search_mode": search,
        "downloads": metadata,
    }, indent=2))

    return metadata


def main() -> None:
    _load_env()

    ap = argparse.ArgumentParser(description="Download YouTube videos for MJ reference material")
    ap.add_argument("url_or_query", help="YouTube URL or search query (with --search)")
    ap.add_argument("--search", action="store_true", help="Treat input as search query")
    ap.add_argument("--audio-only", action="store_true", help="Extract audio as MP3 only")
    ap.add_argument("--max", type=int, default=1, help="Max videos to download (default 1)")
    ap.add_argument("--quality", default="best[height<=1080]", help="yt-dlp format string")
    args = ap.parse_args()

    results = download(
        args.url_or_query,
        search=args.search,
        audio_only=args.audio_only,
        max_results=args.max,
        quality=args.quality,
    )

    print(f"\n✓ Downloaded {len(results)} file(s) to reference/")
    for r in results:
        print(f"  {r['title']}")
        print(f"    {r['local_path']}")


if __name__ == "__main__":
    main()
