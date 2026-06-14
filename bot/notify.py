"""Send a Telegram notification from the terminal or video render pipeline.

Usage:
    python bot/notify.py "Your Elvis video is ready!"
    python bot/notify.py "Render done: final.mp4 (142 MB)"

The bot must be running and you must have sent /start at least once.
Reads TELEGRAM_BOT_TOKEN from .env and the saved chat_id from bot/.state.json.

Tip — call this at the end of a render script:
    python helpers/render.py edl.json -o edit/final.mp4 && \
    python bot/notify.py "Render done! final.mp4 is ready."
"""

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
STATE_FILE = Path(__file__).parent / ".state.json"

# Load .env
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if not TOKEN:
    sys.exit("TELEGRAM_BOT_TOKEN not set in .env")

if not STATE_FILE.exists():
    sys.exit("No saved chat. Open Telegram and send /start to the bot first.")

try:
    state = json.loads(STATE_FILE.read_text())
    chat_id = state["chat_id"]
    assert chat_id
except (json.JSONDecodeError, KeyError, AssertionError):
    sys.exit("No registered chat_id. Open Telegram and send /start to the bot first.")

message = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else "Notification from video-use."

resp = requests.post(
    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
    json={"chat_id": chat_id, "text": message},
    timeout=10,
)

if resp.ok:
    print(f"Sent to chat {chat_id}: {message}")
else:
    sys.exit(f"Telegram API error {resp.status_code}: {resp.text}")
