"""
generate_script.py — QuickKick API client for GitHub Actions.

Posts a video generation job to QuickKick's HTTP API and polls until
the run finishes (or fails). Exits 0 on success, 1 on failure.

Environment variables (set as GitHub Secrets):
  QUICKKICK_API_URL   e.g. https://xxxx.ngrok-free.app
  QUICKKICK_API_KEY   Bearer token from QuickKick's .env

Optional:
  TOPIC               Short topic string  (default: auto-selected by QuickKick)
  SCRIPT              Full script text    (overrides TOPIC if provided)
  POLL_INTERVAL       Seconds between status polls (default: 15)
  TIMEOUT             Max seconds to wait for completion (default: 900)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

# ── Config ────────────────────────────────────────────────────────────────────
API_URL   = os.environ["QUICKKICK_API_URL"].rstrip("/")
API_KEY   = os.environ["QUICKKICK_API_KEY"]
TOPIC     = os.environ.get("TOPIC", "")
SCRIPT    = os.environ.get("SCRIPT", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "15"))
TIMEOUT       = int(os.environ.get("TIMEOUT", "1200"))

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


def _request(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{API_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        payload = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code} from {url}: {payload}") from e


def main() -> None:
    # ── 1. Health check ───────────────────────────────────────────────────────
    print("→ Checking QuickKick health…")
    health = _request("GET", "/health")
    print(f"   status={health.get('status')}  daily_runs={health.get('daily_runs')}/{health.get('daily_cap')}")

    daily_runs = health.get("daily_runs", 0)
    daily_cap  = health.get("daily_cap", 10)
    if daily_runs >= daily_cap:
        print(f"✗ Daily cap reached ({daily_runs}/{daily_cap}). Exiting without generating.")
        sys.exit(0)  # Not a failure — cap is intentional

    # ── 2. POST /generate ─────────────────────────────────────────────────────
    payload: dict = {}
    if SCRIPT:
        payload["script"] = SCRIPT
    if TOPIC:
        payload["topic"] = TOPIC

    print(f"→ Submitting job: topic={TOPIC!r}  script={'<provided>' if SCRIPT else '<none>'}")
    result = _request("POST", "/generate", payload)
    run_id = result.get("run_id")
    if not run_id:
        raise RuntimeError(f"No run_id in response: {result}")
    print(f"   run_id={run_id}  status={result.get('status')}")

    # ── 3. Poll /runs/{run_id} ────────────────────────────────────────────────
    deadline = time.time() + TIMEOUT
    print(f"→ Polling every {POLL_INTERVAL}s (timeout {TIMEOUT}s)…")

    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        status_data = _request("GET", f"/runs/{run_id}")
        status = status_data.get("status", "unknown")
        step   = status_data.get("step", "")
        print(f"   [{status}] {step}")

        if status == "finished":
            yt_url = status_data.get("youtube_url", "")
            title  = status_data.get("title", "")
            print(f"\n✓ Video generated successfully!")
            if title:
                print(f"   Title: {title}")
            if yt_url:
                print(f"   YouTube: {yt_url}")
            sys.exit(0)

        if status == "failed":
            error = status_data.get("error", "unknown error")
            print(f"\n✗ Pipeline failed: {error}")
            sys.exit(1)

    print(f"\n✗ Timed out after {TIMEOUT}s waiting for run {run_id}")
    sys.exit(1)


if __name__ == "__main__":
    main()
