"""Elvis & MJ Telegram Content Bot

Features:
  - Send a photo → receive a Ken Burns video clip
  - Daily content reminders (persistent across restarts)
  - YouTube channel stats (/status)
  - Render notifications (call bot/notify.py from the terminal or pipeline)

Setup:
    pip install -r bot/requirements.txt
    Add TELEGRAM_BOT_TOKEN to your .env file
    python bot/bot.py

Commands:
    /start              Register this chat for notifications
    /help               Show all commands
    /effects            List Ken Burns photo effects
    /remind HH:MM       Add a daily reminder (24h, e.g. /remind 09:00)
    /reminders          List active reminders
    /forget HH:MM       Remove a reminder
    /status             Latest YouTube video stats (needs YOUTUBE_API_KEY)

Photo messages:
    Send any photo to receive a Ken Burns video clip.
    Caption: [effect] [duration_secs]  e.g. "pan_right 8"  or just send with no caption.
    Default: ken_burns effect, 6 seconds.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from datetime import time as dt_time
from pathlib import Path

import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Paths & config
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent.parent
HELPERS = ROOT / "helpers"
STATE_FILE = Path(__file__).parent / ".state.json"

# Load .env from repo root
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
YT_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YT_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")

if not TOKEN:
    sys.exit("TELEGRAM_BOT_TOKEN not set. Add it to your .env file.")

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State (chat registration + reminder list)
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"chat_id": None, "reminders": []}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _register_chat(chat_id: int) -> None:
    state = _load_state()
    state["chat_id"] = chat_id
    _save_state(state)


# ---------------------------------------------------------------------------
# Ken Burns photo → clip
# ---------------------------------------------------------------------------

VALID_EFFECTS = {"zoom_in", "zoom_out", "pan_right", "pan_left", "pan_up", "ken_burns"}
DEFAULT_EFFECT = "ken_burns"
DEFAULT_DURATION = 6.0


def _parse_caption(caption: str | None) -> tuple[str, float]:
    effect, duration = DEFAULT_EFFECT, DEFAULT_DURATION
    if not caption:
        return effect, duration
    parts = caption.strip().lower().split()
    if parts and parts[0] in VALID_EFFECTS:
        effect = parts[0]
    if len(parts) >= 2:
        try:
            duration = max(2.0, min(float(parts[1]), 30.0))
        except ValueError:
            pass
    return effect, duration


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.photo:
        return

    effect, duration = _parse_caption(msg.caption)
    status = await msg.reply_text(
        f"Converting with '{effect}' effect ({duration}s)... give me a moment."
    )

    photo_file = await msg.photo[-1].get_file()  # largest available size

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        in_path = tmp / "input.jpg"
        out_path = tmp / "output.mp4"
        await photo_file.download_to_drive(in_path)

        try:
            subprocess.run(
                [sys.executable, str(HELPERS / "ken_burns.py"),
                 str(in_path), "-o", str(out_path),
                 "--effect", effect, "--duration", str(duration)],
                check=True,
                capture_output=True,
                timeout=180,
            )
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode(errors="replace")[-400:]
            await status.edit_text(f"Conversion failed:\n{err}")
            return
        except subprocess.TimeoutExpired:
            await status.edit_text("Timed out (>3 min). Try a shorter duration.")
            return

        with open(out_path, "rb") as f:
            await msg.reply_video(f, caption=f"{effect} · {duration}s")
        await status.delete()

    _register_chat(update.effective_chat.id)


# ---------------------------------------------------------------------------
# /start and /help
# ---------------------------------------------------------------------------

HELP_TEXT = (
    "Hi! I'm your Elvis & MJ content bot.\n\n"
    "*Send me a photo* and I'll turn it into a Ken Burns video clip.\n"
    "Caption it with an effect name and duration, e.g. `pan_right 8`\n\n"
    "*Commands:*\n"
    "/generate [topic] — auto-generate a YouTube Short (Elvis or MJ)\n"
    "/effects — list all photo effects\n"
    "/remind HH:MM — add a daily content reminder\n"
    "/reminders — see your active reminders\n"
    "/forget HH:MM — remove a reminder\n"
    "/status — latest YouTube video stats\n"
    "/help — show this message\n\n"
    "You'll also receive a message here whenever a video render finishes.\n\n"
    "*Generate examples:*\n"
    "`/generate Elvis recorded Hound Dog in one take`\n"
    "`/generate mj The making of Thriller`"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _register_chat(update.effective_chat.id)
    _restore_reminders(context.job_queue)
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /effects
# ---------------------------------------------------------------------------

async def effects_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*Ken Burns effects* — use as photo caption:\n\n"
        "`zoom_in` — slow zoom into center (portraits, promo shots)\n"
        "`zoom_out` — pull back from close-up (dramatic openers)\n"
        "`pan_right` — sweep left to right (wide concert shots)\n"
        "`pan_left` — sweep right to left\n"
        "`pan_up` — reveal from bottom to top\n"
        "`ken_burns` — zoom in + subtle drift (PBS documentary) ← default\n\n"
        "Add duration in seconds: `ken_burns 8` or `zoom_in 4`\n"
        "Range: 2–30 seconds. Default: 6 seconds.",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

_REMINDER_MESSAGES = [
    "Time to post your Elvis content! What are you uploading today?",
    "Your fans are waiting — share some Elvis magic today.",
    "Daily reminder: have you posted to your channel yet?",
    "Keep The King alive — it's content time!",
    "Don't forget your MJ TikTok today. Thriller awaits.",
]


async def _send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    chat_id = state.get("chat_id")
    if not chat_id:
        return
    import random
    await context.bot.send_message(chat_id=chat_id, text=random.choice(_REMINDER_MESSAGES))


def _restore_reminders(job_queue) -> None:
    state = _load_state()
    for t_str in state.get("reminders", []):
        name = f"reminder_{t_str}"
        if job_queue.get_jobs_by_name(name):
            continue  # already registered
        try:
            h, m = map(int, t_str.split(":"))
            job_queue.run_daily(_send_reminder, time=dt_time(h, m), name=name)
        except Exception:
            pass


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /remind HH:MM  e.g. /remind 09:00")
        return

    t_str = args[0]
    try:
        h, m = map(int, t_str.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            f"Invalid time '{t_str}'. Use 24-hour format, e.g. /remind 09:00"
        )
        return

    _register_chat(update.effective_chat.id)
    state = _load_state()  # reload after registration so chat_id is present
    if t_str not in state.get("reminders", []):
        state.setdefault("reminders", []).append(t_str)
        _save_state(state)
        context.job_queue.run_daily(
            _send_reminder, time=dt_time(h, m), name=f"reminder_{t_str}"
        )

    await update.message.reply_text(f"Reminder set for {t_str} every day.")


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    items = sorted(state.get("reminders", []))
    if not items:
        await update.message.reply_text(
            "No reminders set. Use /remind HH:MM to add one."
        )
    else:
        lines = ["*Active reminders:*"] + [f"  • {r}" for r in items]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def forget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /forget HH:MM")
        return

    t_str = args[0]
    state = _load_state()
    reminders = state.get("reminders", [])
    if t_str not in reminders:
        await update.message.reply_text(f"No reminder found at {t_str}.")
        return

    reminders.remove(t_str)
    state["reminders"] = reminders
    _save_state(state)
    for job in context.job_queue.get_jobs_by_name(f"reminder_{t_str}"):
        job.schedule_removal()
    await update.message.reply_text(f"Removed reminder at {t_str}.")


# ---------------------------------------------------------------------------
# /status — YouTube channel stats
# ---------------------------------------------------------------------------

def _fetch_youtube_stats() -> str:
    if not YT_API_KEY or not YT_CHANNEL_ID:
        return (
            "YouTube stats not configured\\.\n\n"
            "Add to your \\.env:\n"
            "  YOUTUBE\\_API\\_KEY=your\\_key\n"
            "  YOUTUBE\\_CHANNEL\\_ID=UCxxxxxxxx\n\n"
            "Free key: console\\.cloud\\.google\\.com \\(enable YouTube Data API v3\\)\n"
            "Channel ID: youtube\\.com/account\\_advanced"
        )
    try:
        # Channel overview
        rc = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "statistics,snippet", "id": YT_CHANNEL_ID, "key": YT_API_KEY},
            timeout=10,
        )
        rc.raise_for_status()
        ch_item = rc.json()["items"][0]
        ch_name = ch_item["snippet"]["title"]
        chs = ch_item["statistics"]
        subs = int(chs.get("subscriberCount", 0))
        total_views = int(chs.get("viewCount", 0))
        vid_count = int(chs.get("videoCount", 0))

        # Recent 5 videos
        rs = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "channelId": YT_CHANNEL_ID,
                "order": "date",
                "maxResults": 5,
                "type": "video",
                "key": YT_API_KEY,
            },
            timeout=10,
        )
        rs.raise_for_status()
        search_items = rs.json().get("items", [])

        if not search_items:
            return (
                f"*{ch_name}*\n"
                f"\U0001f465 {subs:,} subs · \U0001f441 {total_views:,} views · \U0001f4f9 {vid_count:,} videos\n\n"
                "No videos found yet."
            )

        video_ids = ",".join(i["id"]["videoId"] for i in search_items)
        snippets = {i["id"]["videoId"]: i["snippet"] for i in search_items}

        rv = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "statistics", "id": video_ids, "key": YT_API_KEY},
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
                "views": int(s.get("viewCount", 0)),
                "likes": int(s.get("likeCount", 0)),
                "comments": int(s.get("commentCount", 0)),
            })
        videos.sort(key=lambda v: v["published"], reverse=True)
        top_id = max(videos, key=lambda v: v["views"])["id"] if videos else None

        lines = [
            f"*{ch_name}*",
            f"\U0001f465 {subs:,} subs · \U0001f441 {total_views:,} views · \U0001f4f9 {vid_count:,} videos",
            "",
            "*Recent uploads:*",
        ]
        for v in videos:
            star = " ⭐" if v["id"] == top_id else ""
            lines.append(
                f"\n*{v['title']}{star}*\n"
                f"{v['published']} · \U0001f441 {v['views']:,} · \U0001f44d {v['likes']:,} · \U0001f4ac {v['comments']:,}\n"
                f"youtu\\.be/{v['id']}"
            )

        return "\n".join(lines)

    except requests.RequestException as e:
        return f"Could not reach YouTube API: {e}"
    except (KeyError, IndexError, ValueError) as e:
        return f"Unexpected YouTube API response: {e}"


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text("Fetching your YouTube stats...")
    text = _fetch_youtube_stats()
    await msg.edit_text(text, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /generate — AI Short video pipeline (youtube-shorts-pipeline)
# ---------------------------------------------------------------------------

_MJ_KEYWORDS = {"mj", "michael jackson", "jackson 5", "thriller", "billie jean", "beat it", "moonwalk"}


def _detect_niche(text: str) -> tuple[str, str]:
    """Return (niche, cleaned_topic) from user input."""
    words = text.strip().split()
    lower = text.lower()

    # Explicit override as first word
    if words and words[0].lower() == "mj":
        return "mj", " ".join(words[1:]) or text
    if words and words[0].lower() == "elvis":
        return "elvis", text  # keep "elvis" in topic for context

    # Keyword detection
    if any(k in lower for k in _MJ_KEYWORDS):
        return "mj", text

    return "elvis", text  # default


async def _run_verticals(chat_id: int, topic: str, niche: str, bot) -> None:
    """Run youtube-shorts-pipeline in the background and report the result."""
    env = os.environ.copy()
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip())

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "verticals", "run",
            "--topic", topic,
            "--niche", niche,
            "--platform", "shorts",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        except asyncio.TimeoutError:
            proc.kill()
            await bot.send_message(chat_id=chat_id, text="Generation timed out (10 min). Check your terminal.")
            return

        output = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        yt_match = re.search(r"https?://(?:youtu\.be|www\.youtube\.com)/\S+", output)

        if proc.returncode == 0:
            if yt_match:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"Your Short is ready!\n{yt_match.group(0)}"
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text="Short generated! Check YouTube Studio — it was uploaded as private."
                )
        else:
            tail = output[-600:]
            await bot.send_message(
                chat_id=chat_id,
                text=f"Generation failed. Last output:\n{tail}"
            )

    except FileNotFoundError:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "verticals pipeline not installed.\n"
                "Run bot/setup_verticals.py first:\n"
                ".venv\\Scripts\\python bot\\setup_verticals.py"
            ),
        )
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"Unexpected error: {e}")


async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text(
            "*Usage:* /generate [topic]\n\n"
            "Auto-detects Elvis or MJ from the topic.\n"
            "Prefix with `mj` to force MJ niche.\n\n"
            "*Examples:*\n"
            "`/generate Elvis recorded Hound Dog in one take`\n"
            "`/generate mj How Michael Jackson created the moonwalk`\n"
            "`/generate The 1968 Elvis Comeback Special`",
            parse_mode="Markdown",
        )
        return

    topic_raw = " ".join(args)
    niche, topic = _detect_niche(topic_raw)
    if not topic.strip():
        await update.message.reply_text("Please include a topic after the niche name.")
        return

    _register_chat(update.effective_chat.id)
    await update.message.reply_text(
        f"Generating *{niche.upper()}* Short: _{topic}_\n\n"
        f"This takes 3–5 minutes. I'll message you when it's done.",
        parse_mode="Markdown",
    )
    asyncio.create_task(
        _run_verticals(update.effective_chat.id, topic, niche, context.bot)
    )


# ---------------------------------------------------------------------------
# Startup & main
# ---------------------------------------------------------------------------

async def post_init(application: Application) -> None:
    _restore_reminders(application.job_queue)
    state = _load_state()
    if state.get("chat_id"):
        log.info(f"Restored state: chat_id={state['chat_id']}, reminders={state.get('reminders', [])}")


def main() -> None:
    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("generate", generate_command))
    app.add_handler(CommandHandler("effects", effects_command))
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(CommandHandler("forget", forget_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    log.info("Bot running. Open Telegram and send /start to @TheKingLives_bot to register.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
