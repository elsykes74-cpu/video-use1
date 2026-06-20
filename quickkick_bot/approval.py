"""Telegram approval gate for weak QuickKick scene-image matches.

Design (docs/superpowers/specs/2026-06-19-morning-automation-design.md, "Weak-Match Gate"):
  - if any scene's image match score is below the weak threshold, pause
  - send a full contact-sheet preview to Telegram via the bot's own BOT_TOKEN
  - wait up to `approval_timeout_seconds` for a human reply
  - /approve_run <run_id>  -> resume (caller rescans Drive once, see pipeline.py)
  - /reject_run <run_id>   -> cancel the run
  - no reply in time       -> cancel the run
  - Telegram delivery failure -> cancel the run (never upload a weak set silently)

State is exchanged between processes purely through `_runs/<run_id>/approval_state.json`
(see state.py). This lets a short-lived script (morning_runner.py) request approval
and block, while the long-running Telegram bot process (pipeline.py's polling loop)
is the one that actually receives the /approve_run or /reject_run reply and flips
the state file. Both must be looking at the same `root` directory.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from quickkick_bot.contact_sheet import build_contact_sheet
from quickkick_bot.state import ApprovalState, load_approval_state, save_approval_state

logger = logging.getLogger(__name__)

TELEGRAM_POLL_SECONDS = 5


def _send_telegram_photo(photo_path: Path, caption: str, bot_token: str, chat_id: str) -> None:
    if not bot_token or not chat_id:
        raise RuntimeError(
            "BOT_TOKEN and TELEGRAM_NOTIFY_CHAT must both be set to request approval"
        )
    with open(photo_path, "rb") as fh:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption[:1024]},
            files={"photo": fh},
            timeout=30,
        )
    if not resp.ok:
        raise RuntimeError(f"Telegram sendPhoto failed ({resp.status_code}): {resp.text}")


def request_approval(
    run_id: str,
    topic: str,
    image_paths: list[Path],
    weak_scenes: list[int],
    root: Path,
    bot_token: str = "",
    chat_id: str = "",
    timeout_seconds: int = 600,
) -> ApprovalState:
    """Persist a 'waiting' ApprovalState and send the contact-sheet alert.

    Raises if the Telegram alert cannot be delivered — per spec, delivery
    failure must cancel the run rather than upload a weak set silently.
    """
    state = ApprovalState(run_id=run_id, topic=topic, weak_scenes=weak_scenes, status="waiting", approved=False)
    save_approval_state(state, root)

    if not image_paths:
        # Nothing to show the reviewer at all — there's no point waiting on a
        # reply to a message that was never sent. Fail fast instead of
        # silently parking the run for the full approval timeout.
        state.status = "delivery_failed"
        save_approval_state(state, root)
        raise RuntimeError("no images available to build an approval preview — cannot request approval")

    labels = [
        f"Scene {index + 1}" + (" ⚠️ weak" if (index + 1) in weak_scenes else "")
        for index in range(len(image_paths))
    ]
    preview = build_contact_sheet(
        image_paths,
        root / "_runs" / run_id / "contact_sheet.png",
        labels,
    )
    weak_text = ", ".join(str(scene) for scene in weak_scenes) or "none"
    minutes = max(1, timeout_seconds // 60)
    caption = (
        f"⚠️ Weak QuickKick image match for '{topic[:80]}'.\n"
        f"Weak scenes: {weak_text}\n"
        f"Reply /approve_run {run_id} to continue, or /reject_run {run_id} to cancel.\n"
        f"Auto-cancels in {minutes} min with no reply."
    )

    try:
        _send_telegram_photo(preview, caption, bot_token, chat_id)
    except Exception as exc:
        logger.error(f"[approval] Telegram alert failed for run {run_id}: {exc}")
        state.status = "delivery_failed"
        save_approval_state(state, root)
        raise

    return state


def mark_run_approved(run_id: str, root: Path) -> None:
    state = load_approval_state(run_id, root)
    if state is None:
        raise FileNotFoundError(run_id)
    state.approved = True
    state.status = "approved"
    save_approval_state(state, root)


def mark_run_rejected(run_id: str, root: Path) -> None:
    state = load_approval_state(run_id, root)
    if state is None:
        raise FileNotFoundError(run_id)
    state.approved = False
    state.status = "rejected"
    save_approval_state(state, root)


def wait_for_approval(run_id: str, root: Path, timeout_seconds: int) -> bool:
    """Poll approval_state.json until approved, rejected, or timeout.

    Returns True only if the run was explicitly approved within the window.
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        state = load_approval_state(run_id, root)
        if state is None:
            return False
        if state.status == "rejected":
            logger.info(f"[approval] run {run_id} rejected")
            return False
        if state.approved:
            return True
        time.sleep(TELEGRAM_POLL_SECONDS)
    logger.warning(f"[approval] run {run_id} timed out after {timeout_seconds}s with no reply")
    return False
