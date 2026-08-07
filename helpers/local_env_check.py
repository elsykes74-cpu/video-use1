#!/usr/bin/env python3
"""Local environment check — proves which generation endpoints THIS machine can reach.

Claude's sandbox is network-restricted (Gemini and Microsoft speech are both
blocked there), so every generation step has to run here instead. This script
tests each dependency and endpoint and writes a log Claude can read back.

Run via run_local_check.bat, or:
    python helpers/local_env_check.py
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "finals" / "local_check.log"

lines: list[str] = []


def say(msg: str = "") -> None:
    print(msg)
    lines.append(msg)


def rule(title: str) -> None:
    say()
    say("=" * 62)
    say(title)
    say("=" * 62)


def load_env(name: str) -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    import os
    return os.environ.get(name, "")


def check_python() -> None:
    rule("PYTHON")
    say(f"executable : {sys.executable}")
    say(f"version    : {sys.version.split()[0]}")
    say(f"platform   : {platform.platform()}")


def check_packages() -> None:
    rule("PACKAGES")
    for pkg in ["requests", "PIL", "edge_tts", "numpy", "librosa"]:
        try:
            mod = __import__(pkg)
            ver = getattr(mod, "__version__", "(no __version__)")
            say(f"  OK       {pkg:<12} {ver}")
        except ImportError as e:
            say(f"  MISSING  {pkg:<12} ({e})")


def check_ffmpeg() -> None:
    rule("FFMPEG")
    exe = shutil.which("ffmpeg")
    if not exe:
        say("  MISSING  ffmpeg not on PATH — video assembly will fail")
        return
    say(f"  path     {exe}")
    try:
        r = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=20)
        say(f"  version  {r.stdout.splitlines()[0]}")
        f = subprocess.run([exe, "-hide_banner", "-filters"],
                           capture_output=True, text=True, timeout=30)
        for filt in ["xfade", "zoompan", "ass", "drawtext", "amix"]:
            present = any(ln.split()[1:2] == [filt] for ln in f.stdout.splitlines())
            say(f"  filter   {filt:<9} {'OK' if present else 'MISSING'}")
    except Exception as e:
        say(f"  ERROR    {e}")


def check_keys() -> None:
    rule("API KEYS IN .env  (presence only, values never printed)")
    for k in ["GEMINI_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
              "ELEVENLABS_API_KEY", "FAL_KEY", "SERP_API_KEY"]:
        v = load_env(k)
        say(f"  {'SET    ' if v else 'MISSING'}  {k}"
            + (f"  (len {len(v)})" if v else ""))


def check_gemini() -> None:
    rule("GEMINI / NANO BANANA REACHABILITY  (image generation)")
    key = load_env("GEMINI_API_KEY")
    if not key:
        say("  SKIPPED  no GEMINI_API_KEY in .env")
        return
    try:
        import requests
        url = ("https://generativelanguage.googleapis.com/v1beta"
               "/models/gemini-2.5-flash-image:generateContent")
        body = {"contents": [{"parts": [{"text":
                "Generate an image: a plain grey ceramic coffee mug on a white table, "
                "soft daylight, photorealistic."}]}],
                "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}}
        r = requests.post(url, json=body, timeout=120,
                          headers={"Content-Type": "application/json",
                                   "x-goog-api-key": key})
        say(f"  HTTP     {r.status_code}")
        if r.status_code == 200:
            parts = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
            got = any("inlineData" in p for p in parts)
            say(f"  image    {'RETURNED — image generation works here' if got else 'none in response'}")
            if got:
                import base64
                out = ROOT / "finals" / "local_check_gemini.png"
                out.parent.mkdir(parents=True, exist_ok=True)
                for p in parts:
                    if "inlineData" in p:
                        out.write_bytes(base64.b64decode(p["inlineData"]["data"]))
                        say(f"  saved    {out}  ({out.stat().st_size} bytes)")
                        break
        else:
            try:
                say(f"  detail   {r.json().get('error', {}).get('message', r.text[:200])}")
            except Exception:
                say(f"  detail   {r.text[:200]}")
    except Exception as e:
        say(f"  FAILED   {type(e).__name__}: {e}")


def check_edge_tts() -> None:
    rule("EDGE TTS REACHABILITY  (free narration)")
    try:
        import asyncio
        import edge_tts
    except ImportError:
        say("  MISSING  edge-tts not installed — run: pip install edge-tts")
        return
    out = ROOT / "finals" / "local_check_voice.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)

    async def go():
        c = edge_tts.Communicate(
            "His real name was Andreas Cornelis van Kuijk. He was born in "
            "nineteen oh nine in Breda, Netherlands.",
            "en-US-GuyNeural")
        await c.save(str(out))

    try:
        asyncio.run(go())
        size = out.stat().st_size if out.exists() else 0
        if size > 1000:
            say(f"  OK       narration works here — {out.name} ({size} bytes)")
            say("  NOTE     listen to this file: it says the two hardest names")
            say("           in the script (van Kuijk, Breda). If they are")
            say("           mangled we fix them with phonetic spelling.")
        else:
            say(f"  FAILED   wrote {size} bytes — endpoint reachable but empty audio")
    except Exception as e:
        say(f"  FAILED   {type(e).__name__}: {e}")


def main() -> int:
    say(f"LOCAL ENVIRONMENT CHECK — {datetime.now():%Y-%m-%d %H:%M:%S}")
    say(f"repo: {ROOT}")
    check_python()
    check_packages()
    check_ffmpeg()
    check_keys()
    check_gemini()
    check_edge_tts()
    rule("DONE")
    say("Tell Claude this finished and it will read the log:")
    say(f"  {LOG}")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
