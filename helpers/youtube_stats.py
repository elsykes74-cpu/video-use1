"""YouTube channel analytics helper.

Fetches channel-level stats and per-video stats for recent uploads.

Usage:
    python helpers/youtube_stats.py
    python helpers/youtube_stats.py --max-videos 10
    python helpers/youtube_stats.py --api-key KEY --channel-id UCxxxxxx
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent


def _load_env() -> None:
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def channel_stats(api_key: str, channel_id: str) -> dict:
    """Return channel-level stats: name, subscribers, total_views, video_count."""
    r = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "statistics,snippet", "id": channel_id, "key": api_key},
        timeout=10,
    )
    r.raise_for_status()
    item = r.json()["items"][0]
    s = item["statistics"]
    return {
        "name": item["snippet"]["title"],
        "subscribers": int(s.get("subscriberCount", 0)),
        "total_views": int(s.get("viewCount", 0)),
        "video_count": int(s.get("videoCount", 0)),
    }


def recent_videos(api_key: str, channel_id: str, max_results: int = 5) -> list[dict]:
    """Return recent videos with views, likes, comments. Sorted newest-first."""
    rs = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "part": "snippet",
            "channelId": channel_id,
            "order": "date",
            "maxResults": max_results,
            "type": "video",
            "key": api_key,
        },
        timeout=10,
    )
    rs.raise_for_status()
    items = rs.json().get("items", [])
    if not items:
        return []

    video_ids = ",".join(i["id"]["videoId"] for i in items)
    snippets = {i["id"]["videoId"]: i["snippet"] for i in items}

    rv = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={"part": "statistics", "id": video_ids, "key": api_key},
        timeout=10,
    )
    rv.raise_for_status()

    videos = []
    for item in rv.json().get("items", []):
        vid_id = item["id"]
        s = item["statistics"]
        snip = snippets.get(vid_id, {})
        videos.append({
            "id": vid_id,
            "title": snip.get("title", "Unknown"),
            "published": snip.get("publishedAt", "")[:10],
            "url": f"https://youtu.be/{vid_id}",
            "views": int(s.get("viewCount", 0)),
            "likes": int(s.get("likeCount", 0)),
            "comments": int(s.get("commentCount", 0)),
        })

    videos.sort(key=lambda v: v["published"], reverse=True)
    return videos


def format_report(ch: dict, videos: list[dict]) -> str:
    """Plain-text report for terminal output."""
    lines = [
        f"{ch['name']}",
        f"Subscribers: {ch['subscribers']:,}  |  Total views: {ch['total_views']:,}  |  Videos: {ch['video_count']:,}",
        "",
    ]
    if not videos:
        lines.append("No recent videos found.")
        return "\n".join(lines)

    top_id = max(videos, key=lambda v: v["views"])["id"]
    for v in videos:
        star = " [TOP]" if v["id"] == top_id else ""
        lines += [
            f"{v['published']}  {v['title']}{star}",
            f"  Views: {v['views']:,}  Likes: {v['likes']:,}  Comments: {v['comments']:,}",
            f"  {v['url']}",
            "",
        ]
    return "\n".join(lines)


def main() -> None:
    _load_env()
    ap = argparse.ArgumentParser(description="YouTube channel analytics")
    ap.add_argument("--api-key", default=os.environ.get("YOUTUBE_API_KEY", ""))
    ap.add_argument("--channel-id", default=os.environ.get("YOUTUBE_CHANNEL_ID", ""))
    ap.add_argument("--max-videos", type=int, default=5)
    args = ap.parse_args()

    if not args.api_key:
        sys.exit("Set YOUTUBE_API_KEY in .env or pass --api-key")
    if not args.channel_id:
        sys.exit("Set YOUTUBE_CHANNEL_ID in .env or pass --channel-id")

    try:
        ch = channel_stats(args.api_key, args.channel_id)
        vids = recent_videos(args.api_key, args.channel_id, args.max_videos)
        print(format_report(ch, vids))
    except requests.RequestException as e:
        sys.exit(f"YouTube API error: {e}")


if __name__ == "__main__":
    main()
