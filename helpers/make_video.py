#!/usr/bin/env python3
"""One command, prompt to finished video.

Chains every stage and skips whatever is already done, so you run the same
command whether you are starting from nothing or picking up after a failure.
Nothing needs babysitting between steps.

    # everything that remains for an existing project
    python helpers/make_video.py --project finals/colonel_parker

    # start a brand new video from a topic
    python helpers/make_video.py --new elvis_1968_comeback \
        --topic "The 68 Comeback Special" --scenes 12

    # force a stage to re-run
    python helpers/make_video.py --project ... --redo captions,render

    # keep watching the project and build whenever inputs change
    python helpers/make_video.py --project ... --watch

STAGES
  script     script.txt exists?            -> else generate via OpenRouter
  images     every manifest image on disk? -> else generate via Gemini
  narration  voice.mp3 + boundaries?       -> else Edge TTS
  captions   captions.ass newer than voice?-> else align
  render     FINAL.mp4 newer than inputs?  -> else assemble

Each stage is idempotent. A stage only runs when its output is missing or
older than the thing it depends on.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELP = ROOT / "helpers"
STAGES = ["script", "images", "narration", "captions", "render"]


# ──────────────────────────────────────────────────────────

def log(msg: str = "") -> None:
    print(msg, flush=True)


def rule(title: str) -> None:
    log()
    log("=" * 62)
    log(title)
    log("=" * 62)


def py() -> str:
    """A real python.exe. 'python' on some machines is a .cmd shim that
    breaks when called from a batch context, so prefer sys.executable."""
    return sys.executable


def sh(args: list[str], **kw) -> int:
    log("  $ " + " ".join(str(a) for a in args[1:]))
    return subprocess.run([str(a) for a in args], **kw).returncode


def newer(a: Path, b: Path) -> bool:
    """True if a exists and is newer than b (or b is missing)."""
    if not a.exists():
        return False
    if not b.exists():
        return True
    return a.stat().st_mtime >= b.stat().st_mtime


# ──────────────────────────────────────────────────────────
# stages
# ──────────────────────────────────────────────────────────

def _resolve_source(proj: Path, source_raw: str) -> Path:
    p = Path(source_raw)
    return p if p.is_absolute() else (proj / p).resolve()


def _transcribe_to_script(source: Path, script: Path,
                           bounds_path: Path, model_size: str = "small") -> bool:
    """Transcribe source audio → script.txt + voice_boundaries.json.

    Uses faster-whisper with word timestamps.  The boundaries file is in the
    same format as Edge TTS word boundaries so the rest of the caption pipeline
    needs no changes.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log("  ERROR: faster-whisper not available after install attempt")
        return False

    log(f"  loading faster-whisper '{model_size}' "
        f"(first run downloads the model — this may take a minute)...")
    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments, info = model.transcribe(
        str(source), word_timestamps=True, vad_filter=True, beam_size=5,
    )

    lines: list[str] = []
    boundaries: list[dict] = []
    for seg in segments:
        t = seg.text.strip()
        if t:
            lines.append(t)
        for w in (seg.words or []):
            word = w.word.strip()
            if word:
                boundaries.append({
                    "text": word,
                    "start": float(w.start),
                    "end": float(w.end),
                })

    transcript = " ".join(lines)
    script.write_text(transcript, encoding="utf-8")
    bounds_path.write_text(json.dumps(boundaries, indent=1), encoding="utf-8")

    words = len(transcript.split())
    dur = info.duration
    log(f"  transcript: {words} words, "
        f"{int(dur // 60)}:{int(dur % 60):02d}, "
        f"{len(boundaries)} word timestamps")
    log(f"  wrote {script.name}  +  {bounds_path.name}")
    return True


def stage_script(proj: Path, m: dict, force: bool) -> bool:
    script = proj / m["audio"]["narration_script"]

    # ── Native-audio mode: transcribe source with Whisper ───────────────────
    source_raw = m["audio"].get("source")
    if source_raw:
        source_path = _resolve_source(proj, source_raw)
        bounds = proj / "voice_boundaries.json"
        if script.exists() and bounds.exists() and not force:
            if newer(script, source_path):
                words = len(script.read_text(encoding="utf-8").split())
                log(f"  script.txt present ({words} words) - skipping")
                return True
        if not source_path.exists():
            log(f"  ERROR: source audio not found: {source_path}")
            return False
        log(f"  transcribing {source_path.name} ...")
        ensure("faster-whisper", "faster_whisper")
        return _transcribe_to_script(source_path, script, bounds)
    # ────────────────────────────────────────────────────────────────────────

    if script.exists() and not force:
        words = len(script.read_text(encoding="utf-8").split())
        log(f"  script.txt present ({words} words) - skipping")
        return True
    log("  ERROR: no script.txt and automatic scripting is not wired up yet.")
    log("  Write finals/<project>/script.txt and re-run.")
    return False


def stage_images(proj: Path, m: dict, force: bool) -> bool:
    missing = [s for s in m["scenes"] if not (proj / s["image"]).exists()]
    if not missing and not force:
        log(f"  all {len(m['scenes'])} scene images present - skipping")
        return True

    log(f"  {len(missing)} scene image(s) missing")
    gen = HELP / "regen_scene.py"
    if not gen.exists():
        log("  ERROR: helpers/regen_scene.py not found")
        return False

    for s in missing:
        prompt = s.get("prompt")
        if not prompt:
            log(f"  scene {s['n']}: no 'prompt' in the manifest, cannot generate")
            log(f"    add one, or drop the file in at {s['image']}")
            return False
        out = proj / s["image"]
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [py(), str(gen), "--prompt", prompt, "-o", str(out), "--aspect", "16:9"]
        for r in s.get("refs", []):
            cmd += ["--refs", str(proj / r)]
        if sh(cmd) != 0 or not out.exists():
            log(f"  ERROR: scene {s['n']} did not generate")
            return False
    return True


def stage_narration(proj: Path, m: dict, force: bool) -> bool:
    voice = proj / "voice.mp3"

    # ── Native-audio mode: normalise source to voice.mp3, never call TTS ───
    source_raw = m["audio"].get("source")
    if source_raw:
        source_path = _resolve_source(proj, source_raw)
        if not source_path.exists():
            log(f"  ERROR: source audio not found: {source_path}")
            return False
        if voice.exists() and not force and newer(voice, source_path):
            log(f"  voice.mp3 is newer than source audio - skipping")
            return True
        return sh([py(), "-u", str(HELP / "make_narration.py"),
                   "--manifest", str(proj / "manifest.json")]) == 0
    # ────────────────────────────────────────────────────────────────────────

    bounds = proj / "voice_boundaries.json"
    script = proj / m["audio"]["narration_script"]

    ok = voice.exists() and bounds.exists() and newer(voice, script)
    if ok and not force:
        log(f"  voice.mp3 + boundaries present and newer than script - skipping")
        return True
    if voice.exists() and not bounds.exists():
        log("  voice.mp3 exists but has no word boundaries; regenerating so "
            "captions can be exact")
    ensure("edge-tts", "edge_tts")
    return sh([py(), "-u", str(HELP / "make_narration.py"),
               "--manifest", str(proj / "manifest.json")]) == 0


def ensure(pkg: str, import_name: str | None = None) -> bool:
    """Install a package on demand so no one has to run pip by hand."""
    import importlib
    name = import_name or pkg.replace("-", "_")
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        pass
    log(f"  installing {pkg} (one time)...")
    rc = subprocess.run([py(), "-m", "pip", "install", "--quiet", pkg]).returncode
    if rc != 0:
        log(f"  could not install {pkg}")
        return False
    try:
        importlib.invalidate_caches()
        importlib.import_module(name)
        return True
    except ImportError:
        return False


def stage_captions(proj: Path, m: dict, force: bool) -> bool:
    if not (m.get("captions") or {}).get("enabled"):
        log("  captions disabled in manifest - skipping")
        return True
    caps = proj / "captions.ass"
    voice = proj / "voice.mp3"
    if newer(caps, voice) and not force:
        log("  captions.ass newer than voice.mp3 - skipping")
        return True

    # No TTS word boundaries means the narration came from something other than
    # Edge - VibeVoice, Chatterbox, ElevenLabs. Whisper can still time it
    # exactly, so pull it in rather than silently falling back to estimation.
    if not (proj / "voice_boundaries.json").exists():
        log("  no TTS word boundaries; ensuring faster-whisper is available")
        ensure("faster-whisper", "faster_whisper")

    return sh([py(), "-u", str(HELP / "make_captions.py"),
               "--manifest", str(proj / "manifest.json")]) == 0


def stage_render(proj: Path, m: dict, force: bool, extra: list[str]) -> bool:
    out = proj / f"{m['job_id']}_FINAL.mp4"
    deps = [proj / "manifest.json", proj / "voice.mp3"]
    if (proj / "captions.ass").exists():
        deps.append(proj / "captions.ass")
    deps += [proj / s["image"] for s in m["scenes"]]

    if out.exists() and not force and all(newer(out, d) for d in deps):
        log(f"  {out.name} is newer than every input - skipping")
        return True

    cmd = [py(), "-u", str(HELP / "assemble_production.py"),
           "--manifest", str(proj / "manifest.json"),
           "--narration", str(proj / "voice.mp3"),
           "--resume"] + extra
    return sh(cmd) == 0


# ──────────────────────────────────────────────────────────

def build(proj: Path, only: set[str], redo: set[str], extra: list[str]) -> bool:
    mpath = proj / "manifest.json"
    if not mpath.exists():
        log(f"ERROR: no manifest at {mpath}")
        return False
    m = json.loads(mpath.read_text(encoding="utf-8"))

    log(f"\nproject : {proj}")
    log(f"title   : {m.get('title','(untitled)')}")
    log(f"scenes  : {len(m['scenes'])}")

    runners = {
        "script":    lambda f: stage_script(proj, m, f),
        "images":    lambda f: stage_images(proj, m, f),
        "narration": lambda f: stage_narration(proj, m, f),
        "captions":  lambda f: stage_captions(proj, m, f),
        "render":    lambda f: stage_render(proj, m, f, extra),
    }

    for name in STAGES:
        if only and name not in only:
            continue
        rule(name.upper())
        if not runners[name](name in redo):
            log(f"\nSTOPPED at stage: {name}")
            return False

    out = proj / f"{m['job_id']}_FINAL.mp4"
    rule("DONE")
    if out.exists():
        size = out.stat().st_size / 1e6
        try:
            d = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries",
                                "format=duration", "-of", "csv=p=0", str(out)],
                               capture_output=True, text=True).stdout.strip()
            secs = float(d)
            log(f"  {out}")
            log(f"  {int(secs//60)}:{int(secs%60):02d}   {size:.1f} MB")
        except Exception:
            log(f"  {out}  ({size:.1f} MB)")
    return True


def project_signature(proj: Path) -> tuple:
    """Fingerprint every input that should trigger a rebuild.

    Also watches the helpers directory, so a fix to the renderer or the caption
    aligner rebuilds the video without anyone having to start anything.
    """
    parts: list = []
    for f in ("manifest.json", "script.txt", "script_spoken.txt",
              "voice.mp3", "voice_boundaries.json", "captions.ass"):
        p = proj / f
        parts.append((f, p.stat().st_mtime if p.exists() else 0))
    for d in (proj / "scenes", ROOT / ".verticals-src" / "music"):
        if d.exists():
            parts.append((d.name, tuple(sorted(
                (p.name, p.stat().st_mtime) for p in d.rglob("*") if p.is_file()))))
    parts.append(("helpers", tuple(sorted(
        (p.name, p.stat().st_mtime) for p in HELP.glob("*.py")))))
    return tuple(parts)


def watch(proj: Path, only: set[str], extra: list[str], interval: int) -> int:
    """Rebuild whenever an input changes. Ctrl+C to stop."""
    log("=" * 62)
    log(f"WATCHING {proj}")
    log("Rebuilds automatically when the manifest, script, narration,")
    log("captions, scene images, music or any helper script changes.")
    log("Leave this running. Ctrl+C to stop.")
    log("=" * 62)
    last = None
    while True:
        try:
            sig = project_signature(proj)
        except Exception as e:
            log(f"  (scan error: {e})")
            time.sleep(interval)
            continue
        if sig != last:
            if last is not None:
                log(f"\n>>> change detected at {time.strftime('%H:%M:%S')} - rebuilding\n")
            build(proj, only, set(), extra)
            last = project_signature(proj)   # re-read: the build touched files
            log(f"\n--- idle, watching for changes ---")
        time.sleep(interval)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", type=Path, required=True,
                    help="Folder containing manifest.json")
    ap.add_argument("--only", default="", help="Comma list: " + ",".join(STAGES))
    ap.add_argument("--redo", default="", help="Comma list of stages to force")
    ap.add_argument("--watch", action="store_true",
                    help="Keep running and rebuild when inputs change")
    ap.add_argument("--interval", type=int, default=20)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--crf", type=int, default=19)
    args, unknown = ap.parse_known_args()

    proj = args.project.resolve()
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    redo = {s.strip() for s in args.redo.split(",") if s.strip()}
    if redo & {"narration"}:
        redo.add("captions")          # captions depend on narration
    if redo & {"captions", "images", "narration"}:
        redo.add("render")
    extra = ["--preset", args.preset, "--crf", str(args.crf)] + unknown

    bad = (only | redo) - set(STAGES)
    if bad:
        log(f"unknown stage(s): {', '.join(sorted(bad))}")
        return 2

    if args.watch:
        try:
            return watch(proj, only, extra, args.interval)
        except KeyboardInterrupt:
            log("\nstopped")
            return 0
    return 0 if build(proj, only, redo, extra) else 1


if __name__ == "__main__":
    raise SystemExit(main())
