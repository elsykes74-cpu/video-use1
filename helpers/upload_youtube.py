"""
Upload a finished video to YouTube using the YouTube Data API v3.

Usage:
    python helpers/upload_youtube.py --manifest finals/colonel_parker/manifest.json
    python helpers/upload_youtube.py --manifest finals/colonel_parker/manifest.json --confirm

First run opens a browser for Google OAuth consent and saves token.json next to
client_secrets.json.  Subsequent runs reuse the stored token.

Setup (one-time):
    1. Google Cloud Console → APIs & Services → Enable "YouTube Data API v3"
    2. Credentials → Create OAuth 2.0 Client ID (Desktop app)
    3. Download JSON → save as  helpers/client_secrets.json
    4. pip install google-auth-oauthlib google-api-python-client

Flags:
    --manifest PATH      required
    --title TEXT         override title from manifest
    --description TEXT   override auto-generated description
    --tags TAG,TAG,...   comma-separated tags (default: from manifest niche/channel)
    --privacy STATUS     public | unlisted | private  (default: private)
    --category ID        YouTube category ID (default: 27 = Education)
    --confirm            actually upload; without this flag it is a dry run
    --secrets PATH       path to client_secrets.json  (default: helpers/client_secrets.json)
    --token PATH         path to store/read token.json (default: alongside secrets)
"""

import argparse
import json
import os
import pathlib
import sys
import textwrap

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

SCRIPT_DIR = pathlib.Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent


def load_manifest(path: str) -> dict:
    p = pathlib.Path(path)
    if not p.is_absolute():
        p = pathlib.Path.cwd() / p
    with open(p, encoding="utf-8") as f:
        return json.load(f), p.parent


def find_video(proj_dir: pathlib.Path, job_id: str) -> pathlib.Path:
    candidate = proj_dir / f"{job_id}_FINAL.mp4"
    if candidate.exists():
        return candidate
    # fallback: any .mp4 in the project dir
    mp4s = sorted(proj_dir.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)
    if mp4s:
        return mp4s[0]
    return None


def build_description(manifest: dict, proj_dir: pathlib.Path) -> str:
    # First paragraph of script.txt (up to ~600 chars), then channel footer
    script_path = proj_dir / manifest["audio"].get("narration_script", "script.txt")
    teaser = ""
    if script_path.exists():
        text = script_path.read_text(encoding="utf-8").strip()
        # first sentence-ish block
        first_para = text.split("\n\n")[0] if "\n\n" in text else text
        teaser = textwrap.shorten(first_para, width=600, placeholder="…")

    channel = manifest.get("channel", "")
    lines = []
    if teaser:
        lines.append(teaser)
        lines.append("")
    if channel:
        lines.append(f"Subscribe to {channel} for more.")
    return "\n".join(lines)


def default_tags(manifest: dict) -> list[str]:
    tags = []
    niche = manifest.get("niche", "")
    channel = manifest.get("channel", "")
    title = manifest.get("title", "")
    if niche:
        tags.append(niche)
    if channel:
        tags.extend(channel.split())
    if title:
        tags.extend(w for w in title.split() if len(w) > 3)
    return list(dict.fromkeys(tags))  # dedupe, preserve order


# ---------------------------------------------------------------------------
# OAuth + upload
# ---------------------------------------------------------------------------

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
API_SERVICE = "youtube"
API_VERSION = "v3"


def get_authenticated_service(secrets_path: pathlib.Path, token_path: pathlib.Path):
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit(
            "Missing libraries.  Run:\n"
            "  pip install google-auth-oauthlib google-api-python-client"
        )

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not secrets_path.exists():
                sys.exit(
                    f"client_secrets.json not found at {secrets_path}\n"
                    "Download it from Google Cloud Console → Credentials → OAuth 2.0 Client IDs."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        print(f"Token saved to {token_path}")

    return build(API_SERVICE, API_VERSION, credentials=creds)


def upload_video(
    youtube,
    video_path: pathlib.Path,
    title: str,
    description: str,
    tags: list[str],
    category_id: str,
    privacy: str,
) -> str:
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        sys.exit("pip install google-api-python-client")

    size_mb = video_path.stat().st_size / 1_048_576
    print(f"Uploading {video_path.name} ({size_mb:.1f} MB) ...")

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=4 * 1024 * 1024,  # 4 MB chunks
    )

    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"  {pct}%", end="\r", flush=True)

    print()
    video_id = response.get("id", "?")
    print(f"Upload complete → https://www.youtube.com/watch?v={video_id}")
    return video_id


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True, help="Path to manifest.json")
    ap.add_argument("--title", default=None)
    ap.add_argument("--description", default=None)
    ap.add_argument("--tags", default=None, help="Comma-separated tags")
    ap.add_argument("--privacy", default="private", choices=["public", "unlisted", "private"])
    ap.add_argument("--category", default="27", help="YouTube category ID (27=Education)")
    ap.add_argument("--confirm", action="store_true", help="Actually upload; default is dry-run")
    ap.add_argument("--secrets", default=None, help="Path to client_secrets.json")
    ap.add_argument("--token", default=None, help="Path to token.json")
    args = ap.parse_args()

    manifest, proj_dir = load_manifest(args.manifest)

    job_id = manifest.get("job_id", proj_dir.name)
    title = args.title or manifest.get("title", job_id)
    description = args.description or build_description(manifest, proj_dir)
    tags = args.tags.split(",") if args.tags else default_tags(manifest)

    secrets_path = pathlib.Path(args.secrets) if args.secrets else SCRIPT_DIR / "client_secrets.json"
    token_path = pathlib.Path(args.token) if args.token else secrets_path.parent / "token.json"

    video_path = find_video(proj_dir, job_id)

    # --- dry-run summary ---
    print("=== YouTube Upload Plan ===")
    print(f"  Title      : {title}")
    print(f"  Privacy    : {args.privacy}")
    print(f"  Category   : {args.category}")
    print(f"  Tags       : {', '.join(tags)}")
    print(f"  Video file : {video_path or 'NOT FOUND'}")
    print(f"  Secrets    : {secrets_path}")
    print(f"  Token      : {token_path}")
    print()
    print("Description:")
    print(textwrap.indent(description, "  "))
    print()

    if not args.confirm:
        print("Dry run — pass --confirm to upload.")
        return

    if not video_path:
        sys.exit(f"No rendered .mp4 found in {proj_dir}")

    youtube = get_authenticated_service(secrets_path, token_path)
    upload_video(youtube, video_path, title, description, tags, args.category, args.privacy)


if __name__ == "__main__":
    main()
