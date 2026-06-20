#!/usr/bin/env python3
"""
QuickKick Morning Runner
========================
Runs automatically every morning via Windows Task Scheduler.

Workflow:
  1. Load credentials from Hermes .env (OPENAI_API_KEY etc.)
  2. Search Google Drive for today's Elvis topic/script file
  3. Run the full pipeline (script → images → TTS → ffmpeg → YouTube private)
  4. Notify via Telegram on success or failure
  5. Lock file prevents double-runs on the same day

Config (add to C:\\Users\\erick\\quickkick-bot\\.env):
  GDRIVE_TOPIC_FOLDER  = name of the Drive folder containing daily scripts
                         (e.g. "Elvis Daily Topics")  ← set this!
  GDRIVE_SEARCH_DAYS   = how many days back to look (default: 1)
  MORNING_RUN_HOUR     = earliest hour to run (default: 6, i.e. 6am)
  TELEGRAM_NOTIFY_CHAT = Telegram chat ID to notify (optional)
"""

import json
import logging
import os
import sys
import time
from html import escape
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from quickkick_bot.settings import load_settings
    from quickkick_bot.state import ApprovalState, load_approval_state, save_approval_state
except ImportError:  # pragma: no cover - direct script execution
    from settings import load_settings
    from state import ApprovalState, load_approval_state, save_approval_state

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FILE = Path(__file__).parent / "_runs" / "morning_runner.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
    ],
)
logger = logging.getLogger("morning_runner")

# ── Paths ─────────────────────────────────────────────────────────────────────
QUICKKICK_DIR = Path(__file__).resolve().parent
HERMES_HOME   = Path(r"C:\Users\erick\AppData\Local\hermes")
LOCK_FILE     = QUICKKICK_DIR / "_runs" / f"ran_{date.today().isoformat()}.lock"

# ── Load .env files ───────────────────────────────────────────────────────────
def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and val and key not in os.environ:
            os.environ[key] = val

# Load quickkick .env first — it has the API keys validated against this pipeline
_load_env(QUICKKICK_DIR / ".env")
# Hermes .env fills in anything else (Google auth env vars, etc.)
_load_env(HERMES_HOME / ".env")
SETTINGS = load_settings()

# ── Config from env ───────────────────────────────────────────────────────────
GDRIVE_TOPIC_FOLDER  = os.getenv("GDRIVE_TOPIC_FOLDER", "Elvis Daily Topics").strip()
GDRIVE_SEARCH_DAYS   = int(os.getenv("GDRIVE_SEARCH_DAYS", "1"))
TELEGRAM_NOTIFY_CHAT = os.getenv("TELEGRAM_NOTIFY_CHAT", "").strip()
BOT_TOKEN            = os.getenv("BOT_TOKEN", "").strip()
_TELEGRAM_DISABLED   = False

# ── Google auth (reuse Hermes credentials) ────────────────────────────────────
GOOGLE_TOKEN_PATH   = HERMES_HOME / "google_token.json"
GOOGLE_SECRET_PATH  = HERMES_HOME / "google_client_secret.json"
DRIVE_SCOPES        = ["https://www.googleapis.com/auth/drive.readonly"]

def _get_drive_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token_data = json.loads(GOOGLE_TOKEN_PATH.read_text())
    stored_scopes = token_data.get("scopes") or DRIVE_SCOPES
    creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_PATH), stored_scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        refreshed = json.loads(creds.to_json())
        if not refreshed.get("type"):
            refreshed["type"] = "authorized_user"
        GOOGLE_TOKEN_PATH.write_text(json.dumps(refreshed, indent=2))
    return build("drive", "v3", credentials=creds)

# ── Find today's topic file in Drive ─────────────────────────────────────────
def _find_todays_topic() -> tuple[str, str]:
    """Returns (topic_text, raw_content). topic_text is the first line or Topic: field."""
    svc = _get_drive_service()

    # Find the folder
    folder_q = f"name = '{GDRIVE_TOPIC_FOLDER}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    folders = svc.files().list(q=folder_q, fields="files(id, name)").execute().get("files", [])

    if not folders:
        # Folder not found — fall back to searching entire Drive for recent files
        logger.warning(f"Drive folder '{GDRIVE_TOPIC_FOLDER}' not found. Searching all Drive for recent files.")
        cutoff = (datetime.utcnow() - timedelta(days=GDRIVE_SEARCH_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        q = (
            f"modifiedTime >= '{cutoff}' and trashed = false "
            f"and (name contains 'Elvis' or name contains 'Script' or name contains 'Topic')"
        )
        files = svc.files().list(q=q, orderBy="modifiedTime desc", pageSize=5,
                                  fields="files(id, name, mimeType)").execute().get("files", [])
    else:
        folder_id = folders[0]["id"]
        cutoff = (datetime.utcnow() - timedelta(days=GDRIVE_SEARCH_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        q = f"'{folder_id}' in parents and modifiedTime >= '{cutoff}' and trashed = false"
        files = svc.files().list(q=q, orderBy="modifiedTime desc", pageSize=10,
                                  fields="files(id, name, mimeType)").execute().get("files", [])

    if not files:
        raise RuntimeError(
            f"No topic files found in Drive folder '{GDRIVE_TOPIC_FOLDER}' from the last {GDRIVE_SEARCH_DAYS} day(s). "
            "Check GDRIVE_TOPIC_FOLDER in .env."
        )

    target = files[0]
    logger.info(f"Found Drive file: {target['name']} (id={target['id']})")

    # Download content
    import io
    from googleapiclient.http import MediaIoBaseDownload

    mime = target.get("mimeType", "")
    buf = io.BytesIO()

    if "google-apps.document" in mime:
        req = svc.files().export_media(fileId=target["id"], mimeType="text/plain")
    else:
        req = svc.files().get_media(fileId=target["id"])

    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()

    raw = buf.getvalue().decode("utf-8", errors="replace").strip()

    # Extract topic
    import re
    m = re.search(r"(?im)^Topic:\s*(.+?)\s*$", raw)
    topic = m.group(1).strip() if m else raw.splitlines()[0].strip()
    return topic, raw

# ── Telegram notification ─────────────────────────────────────────────────────
def _telegram_notify(msg: str, parse_mode: str | None = None) -> None:
    global _TELEGRAM_DISABLED

    if _TELEGRAM_DISABLED:
        return
    if not BOT_TOKEN or not TELEGRAM_NOTIFY_CHAT:
        return
    try:
        import urllib.error
        import urllib.request

        payload = {"chat_id": TELEGRAM_NOTIFY_CHAT, "text": msg}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code in (400, 403) and any(
            text in body.lower()
            for text in ("chat not found", "bot was blocked by the user", "user is deactivated")
        ):
            _TELEGRAM_DISABLED = True
            logger.warning(f"Telegram notifications disabled: {body}")
            return
        logger.warning(f"Telegram notify failed: HTTP {e.code}: {body}")
    except Exception as e:
        logger.warning(f"Telegram notify failed: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    today = date.today().isoformat()

    logger.info(f"Configured morning run time: {SETTINGS.morning_run_time}")

    # Lock file: only run once per day
    if LOCK_FILE.exists():
        logger.info(f"Already ran today ({today}). Delete {LOCK_FILE} to force a re-run.")
        return

    logger.info(f"=== Morning Runner starting — {today} ===")
    _telegram_notify(
        f"🎬 <b>QuickKick Morning Runner</b> starting for {escape(today)}...",
        parse_mode="HTML",
    )

    try:
        # Step 1: Get today's topic from Drive
        logger.info(f"Fetching today's topic from Drive folder: '{GDRIVE_TOPIC_FOLDER}'")
        topic, raw_content = _find_todays_topic()
        logger.info(f"Topic: {topic}")

        # Step 2: Import and run pipeline
        sys.path.insert(0, str(QUICKKICK_DIR))
        from quickkick_bot.pipeline import _run_pipeline_sync, _is_production_doc
        import uuid

        run_id = f"{today}_{uuid.uuid4().hex[:8]}"
        # Use local _runs dir (same as manual runs) to avoid OneDrive/Desktop path issues
        out_dir = QUICKKICK_DIR / "_runs" / run_id

        # Pass raw content if it's a full production doc, otherwise just topic
        initial_script = raw_content if _is_production_doc(raw_content) else ""

        logger.info(f"Starting pipeline | run_id={run_id} | production_doc={bool(initial_script)}")
        result = _run_pipeline_sync(topic, out_dir, initial_script=initial_script)

        # Step 3: Write lock file on success
        LOCK_FILE.write_text(json.dumps(result, indent=2), encoding="utf-8")

        yt_url = result.get("youtube_url", "(no URL)")
        logger.info(f"Pipeline complete: {yt_url}")
        _telegram_notify(
            f"✅ <b>Video done!</b>\n"
            f"Topic: {escape(topic)}\n"
            f"YouTube: {escape(yt_url)}\n"
            f"Run: {escape(run_id)}",
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"Morning runner FAILED: {e}", exc_info=True)
        is_approval_cancel = "not approved" in str(e) or "weak scene matches" in str(e)
        header = "🛑 <b>Run cancelled (weak-match approval)</b>" if is_approval_cancel else "❌ <b>Morning runner failed</b>"
        _telegram_notify(
            f"{header} ({escape(today)})\n"
            f"Error: {escape(str(e))}\n"
            f"Check: {escape(str(LOG_FILE))}",
            parse_mode="HTML",
        )
        sys.exit(1)

if __name__ == "__main__":
    main()
