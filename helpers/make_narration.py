#!/usr/bin/env python3
"""Narration only — produces voice.mp3 from either a pre-recorded source or
Edge TTS, depending on the manifest's audio configuration.

Native-audio mode (audio.source present in manifest):
    Normalises the supplied file to 48 kHz stereo with loudnorm.  Never
    calls TTS.  Skips normalisation when voice.mp3 is already newer than the
    source.

    python helpers/make_narration.py --manifest finals/<project>/manifest.json

TTS mode (no audio.source):
    Generates voice.mp3 via Edge TTS and captures word-boundary events for
    exact caption timing.

    python helpers/make_narration.py
    python helpers/make_narration.py --voice en-US-ChristopherNeural
    python helpers/make_narration.py --list-voices
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "finals" / "colonel_parker" / "manifest.json"

# Male documentary-leaning Edge voices, worth auditioning if Guy isn't right.
SUGGESTED = [
    ("en-US-GuyNeural",         "warm baritone, default for this channel"),
    ("en-US-ChristopherNeural", "weightier, more authoritative"),
    ("en-US-RogerNeural",       "drier, closest to classic documentary"),
    ("en-US-EricNeural",        "measured, neutral"),
    ("en-GB-RyanNeural",        "British, cooler"),
]


def native_audio_mode(source: Path, out: Path) -> int:
    """Normalise a pre-recorded narration to project voice.mp3.

    Converts to 48 kHz stereo and applies loudnorm so the mix engine gets the
    same format it would receive from Edge TTS.  Never calls TTS.
    Returns 0 on success, non-zero on error.
    """
    if not source.exists():
        print(f"ERROR: source audio not found: {source}", file=sys.stderr)
        return 1

    if out.exists() and out.stat().st_mtime >= source.stat().st_mtime:
        size = out.stat().st_size
        print(f"  voice.mp3 is newer than source — skipping normalisation")
        print(f"  {out}  ({size / 1e6:.2f} MB)")
        return 0

    print(f"source      : {source}")
    print(f"writing     : {out}")
    print(f"normalising : 48 kHz stereo, loudnorm I=-16 TP=-1.5 LRA=11")

    cmd = [
        "ffmpeg", "-y", "-hide_banner",
        "-i", str(source),
        "-ar", "48000",
        "-ac", "2",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        str(out),
    ]
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        print(f"ERROR: ffmpeg normalisation failed (rc={rc})", file=sys.stderr)
        return rc

    size = out.stat().st_size
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    )
    try:
        secs = float(probe.stdout.strip())
        print(f"\nOK  {out.name}  {size / 1e6:.2f} MB  "
              f"({int(secs // 60)}:{int(secs % 60):02d})")
    except ValueError:
        print(f"\nOK  {out.name}  {size / 1e6:.2f} MB")
    return 0


async def list_voices() -> int:
    import edge_tts
    vs = await edge_tts.list_voices()
    en = sorted([v for v in vs if v["Locale"].startswith("en-")],
                key=lambda v: (v["Locale"], v["ShortName"]))
    print(f"{len(en)} English voices available\n")
    for v in en:
        g = v.get("Gender", "")
        print(f"  {v['ShortName']:<34} {g:<7} {v['Locale']}")
    print("\nSuggested for this documentary:")
    for n, why in SUGGESTED:
        print(f"  {n:<34} {why}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--voice", help="Override the manifest voice")
    ap.add_argument("--rate", help="Override the manifest rate, e.g. -10%%")
    ap.add_argument("--out", type=Path, help="Override output path")
    ap.add_argument("--list-voices", action="store_true")
    args = ap.parse_args()

    if args.list_voices:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            print("ERROR: edge-tts not installed.  Run:  pip install edge-tts",
                  file=sys.stderr)
            return 1
        return asyncio.run(list_voices())

    if not args.manifest.exists():
        print(f"ERROR: manifest not found: {args.manifest}", file=sys.stderr)
        return 1

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    base = args.manifest.parent
    a = manifest["audio"]

    # ── Native-audio mode (no TTS dependency) ────────────────────────────────
    source_raw = a.get("source")
    if source_raw:
        source_path = Path(source_raw)
        if not source_path.is_absolute():
            source_path = (base / source_path).resolve()
        out = args.out or (base / "voice.mp3")
        return native_audio_mode(source_path, out)
    # ────────────────────────────────────────────────────────────────────────

    # TTS mode: edge-tts required from here on.
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        print("ERROR: edge-tts not installed.  Run:  pip install edge-tts",
              file=sys.stderr)
        return 1

    script = base / a["narration_script"]
    if not script.exists():
        print(f"ERROR: script not found: {script}", file=sys.stderr)
        return 1

    text = script.read_text(encoding="utf-8")
    raw_words = len(text.split())

    applied = []
    for fix in manifest.get("pronunciation_fixes", []):
        if fix["from"] in text:
            applied.append(f"{fix['from']} -> {fix['to']}")
            text = text.replace(fix["from"], fix["to"])

    spoken = base / "script_spoken.txt"
    spoken.write_text(text, encoding="utf-8")

    voice = args.voice or a.get("voice", "en-US-GuyNeural")
    rate = args.rate or a.get("rate", "+0%")
    out = args.out or (base / "voice.mp3")

    print(f"script      : {script.name}  ({raw_words} words)")
    print(f"voice       : {voice}")
    print(f"rate        : {rate}")
    if applied:
        print(f"pronunciation fixes applied ({len(applied)}):")
        for x in applied:
            print(f"                {x}")
    else:
        print("pronunciation: no fixes matched")
    boundaries_path = base / "voice_boundaries.json"
    print(f"writing     : {out}")
    print(f"            : {boundaries_path.name}  (exact word timings)")
    print("\ncontacting Edge TTS ...")

    # Stream rather than save(), so we capture WordBoundary events alongside
    # the audio. These give the exact offset of every spoken word, which beats
    # estimating timings from silence detection afterwards.
    boundaries: list[dict] = []

    async def go():
        import edge_tts
        c = edge_tts.Communicate(text, voice, rate=rate)
        with open(out, "wb") as f:
            async for chunk in c.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    # edge-tts reports in 100-nanosecond ticks
                    boundaries.append({
                        "text": chunk["text"],
                        "start": chunk["offset"] / 10_000_000,
                        "end": (chunk["offset"] + chunk["duration"]) / 10_000_000,
                    })

    try:
        asyncio.run(go())
    except Exception as e:
        print(f"\nERROR: Edge TTS failed: {type(e).__name__}: {e}", file=sys.stderr)
        print("If this is a network error, your firewall or VPN is blocking "
              "speech.platform.bing.com", file=sys.stderr)
        return 2

    if boundaries:
        boundaries_path.write_text(json.dumps(boundaries, indent=1), encoding="utf-8")
        print(f"captured {len(boundaries)} word boundaries "
              f"(last word ends {boundaries[-1]['end']:.2f}s)")
    else:
        print("WARNING: no word boundaries returned; captions will fall back "
              "to silence-based estimation", file=sys.stderr)

    if not out.exists() or out.stat().st_size < 2000:
        print("\nERROR: no usable audio produced.", file=sys.stderr)
        return 3

    size = out.stat().st_size
    # rough duration estimate from a typical edge-tts bitrate (~24 kbps)
    est = size * 8 / 24000
    print(f"\nOK  {out.name}  {size/1e6:.2f} MB  (~{int(est//60)}:{int(est%60):02d})")
    print(f"    {spoken.name} shows exactly what was read aloud")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
