"""Install and configure youtube-shorts-pipeline for the Elvis & MJ bot.

Run once after setup.bat completes:
    .venv\Scripts\python bot\setup_verticals.py

What this does:
  1. Installs youtube-shorts-pipeline into your venv
  2. Copies elvis and mj niche profiles into the pipeline
  3. Writes API keys from .env into ~/.verticals/config.json
  4. Guides you through YouTube OAuth setup (needed for auto-upload)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PRESETS = ROOT / "presets"

VERTICALS_DIR = Path.home() / ".verticals"
PIPELINE_REPO = "https://github.com/rushindrasinha/youtube-shorts-pipeline.git"
PIPELINE_LOCAL = ROOT / ".verticals-src"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def pip(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", *args], check=True)


def step(n: int, msg: str) -> None:
    print(f"\n[{n}] {msg}")


def main() -> None:
    print("=" * 55)
    print("  youtube-shorts-pipeline Setup for Elvis & MJ Bot")
    print("=" * 55)

    env = load_env()

    # ------------------------------------------------------------------
    # 1. Clone + install pipeline
    # ------------------------------------------------------------------
    step(1, "Installing youtube-shorts-pipeline...")

    if PIPELINE_LOCAL.exists():
        print(f"  already cloned at {PIPELINE_LOCAL}, pulling latest...")
        subprocess.run(["git", "pull"], cwd=PIPELINE_LOCAL, check=False)
    else:
        print(f"  cloning from {PIPELINE_REPO}...")
        subprocess.run(
            ["git", "clone", "--depth", "1", PIPELINE_REPO, str(PIPELINE_LOCAL)],
            check=True,
        )

    print("  installing dependencies (this may take a few minutes)...")
    pip("install", "-e", str(PIPELINE_LOCAL), "--quiet")
    pip("install", "-r", str(PIPELINE_LOCAL / "requirements.txt"), "--quiet")
    print("  pipeline installed.")

    # ------------------------------------------------------------------
    # 2. Copy niche YAML profiles
    # ------------------------------------------------------------------
    step(2, "Installing Elvis & MJ niche profiles...")

    niches_dir = PIPELINE_LOCAL / "niches"
    niches_dir.mkdir(exist_ok=True)

    for name in ("elvis", "mj"):
        src = PRESETS / f"{name}-niche.yaml"
        dst = niches_dir / f"{name}.yaml"
        if src.exists():
            shutil.copy(src, dst)
            print(f"  copied {name}.yaml → pipeline/niches/")
        else:
            print(f"  WARNING: {src} not found — skipping")

    # ------------------------------------------------------------------
    # 3. Write config from .env
    # ------------------------------------------------------------------
    step(3, "Writing ~/.verticals/config.json from your .env...")

    VERTICALS_DIR.mkdir(exist_ok=True)
    config_path = VERTICALS_DIR / "config.json"

    config: dict = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except Exception:
            pass

    key_map = {
        "ANTHROPIC_API_KEY": "ANTHROPIC_API_KEY",
        "ELEVENLABS_API_KEY": "ELEVENLABS_API_KEY",
        "GEMINI_API_KEY": "GEMINI_API_KEY",
        "YOUTUBE_API_KEY": "YOUTUBE_API_KEY",
    }
    for env_key, cfg_key in key_map.items():
        val = env.get(env_key, "").strip()
        if val:
            config[cfg_key] = val
            print(f"  {cfg_key}: set")
        else:
            print(f"  {cfg_key}: not set (optional or add to .env)")

    if not config.get("GEMINI_API_KEY"):
        print()
        print("  GEMINI_API_KEY is required for AI visuals and thumbnails.")
        print("  Get a free key at: https://aistudio.google.com/apikey")
        key = input("  Paste your Gemini API key (or press Enter to skip): ").strip()
        if key:
            config["GEMINI_API_KEY"] = key
            # Also write it back to .env
            _add_to_env("GEMINI_API_KEY", key)
            print("  GEMINI_API_KEY saved.")

    config_path.write_text(json.dumps(config, indent=2))
    config_path.chmod(0o600)
    print(f"  config saved to {config_path}")

    # ------------------------------------------------------------------
    # 4. YouTube OAuth
    # ------------------------------------------------------------------
    step(4, "YouTube OAuth setup (needed for auto-upload)...")
    oauth_token = VERTICALS_DIR / "youtube_token.json"
    if oauth_token.exists():
        print("  OAuth token already exists — skipping.")
    else:
        print()
        print("  To auto-upload Shorts to YouTube, you need to connect your account once.")
        print("  This opens a browser window for Google sign-in.")
        print()
        choice = input("  Set up YouTube OAuth now? (y/n): ").strip().lower()
        if choice == "y":
            oauth_script = PIPELINE_LOCAL / "scripts" / "setup_youtube_oauth.py"
            if oauth_script.exists():
                subprocess.run([sys.executable, str(oauth_script)], check=False)
            else:
                print("  OAuth script not found. Run it manually later:")
                print(f"  {sys.executable} {PIPELINE_LOCAL}/scripts/setup_youtube_oauth.py")
        else:
            print("  Skipped. Run it later when you're ready to auto-upload.")

    # ------------------------------------------------------------------
    # Done
    # ------------------------------------------------------------------
    print()
    print("=" * 55)
    print("  Setup complete!")
    print("=" * 55)
    print()
    print("  Start the bot:  start_bot.bat")
    print()
    print("  Then in Telegram:")
    print("  /generate Elvis recorded Hound Dog in one take")
    print("  /generate mj How Michael Jackson created the moonwalk")
    print()


def _add_to_env(key: str, value: str) -> None:
    env_file = ROOT / ".env"
    text = env_file.read_text() if env_file.exists() else ""
    if key in text:
        lines = []
        for line in text.splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}")
            else:
                lines.append(line)
        env_file.write_text("\n".join(lines) + "\n")
    else:
        with open(env_file, "a") as f:
            f.write(f"\n{key}={value}\n")


if __name__ == "__main__":
    main()
