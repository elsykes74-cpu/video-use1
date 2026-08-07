#!/usr/bin/env python3
"""Manifest-driven 16:9 production renderer.

Everything the render needs comes from a manifest.json, so a prompt-to-video
pipeline only has to emit that manifest — this script turns it into a finished
video. Adds what the existing verticals assembler lacks:

  * 16:9 landscape output (not 9:16)
  * xfade crossfades between every scene (verticals hard-cuts)
  * per-scene Ken Burns honouring the manifest, including "hold" for stills
  * burned-in text-overlay title cards per scene
  * narration via free Edge TTS, with pronunciation fixes applied first
  * optional ducked music bed
  * no 6-frame cap

Usage:
    # full render
    python helpers/assemble_production.py --manifest finals/colonel_parker/manifest.json

    # reuse narration already rendered (skips TTS)
    python helpers/assemble_production.py --manifest ... --narration finals/colonel_parker/voice.mp3

    # video only, no audio - useful for checking motion/transitions fast
    python helpers/assemble_production.py --manifest ... --silent --duration 60

    # print the plan and exit
    python helpers/assemble_production.py --manifest ... --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PRESET = "medium"   # overridden by --preset
CRF = 18            # overridden by --crf


# ──────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────

def run(cmd: list[str], desc: str = "") -> subprocess.CompletedProcess:
    if desc:
        print(f"  {desc}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = (r.stderr or "")[-1500:]
        raise RuntimeError(f"command failed: {' '.join(cmd[:6])}...\n{tail}")
    return r


def probe_duration(path: Path) -> float:
    r = run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)])
    return float(r.stdout.strip())


def ffmpeg_has(filt: str) -> bool:
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                           capture_output=True, text=True, timeout=30)
        return any(ln.split()[1:2] == [filt] for ln in r.stdout.splitlines())
    except Exception:
        return False


def esc_drawtext(s: str) -> str:
    """Escape text for ffmpeg drawtext."""
    return (s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\u2019")
             .replace("%", "\\%").replace(",", "\\,"))


def esc_filter_path(p: str | Path) -> str:
    """Escape a filesystem path for use inside an ffmpeg filter argument.

    On Windows the drive-letter colon in 'C:/Windows/Fonts/arialbd.ttf' is
    parsed as an option separator, so ffmpeg reads 'C' as an option name and
    fails with "No option name near '/Windows/...'". Backslashes must become
    forward slashes and the colon must be escaped.
    """
    return str(p).replace("\\", "/").replace(":", "\\:")


def wrap_overlay(text: str, max_chars: int, max_lines: int = 2) -> list[str]:
    """Greedy word-wrap for title cards, preferring a break after a sentence.

    Long cards were overflowing the 1920px frame, so anything over max_chars
    is split. A break at a sentence boundary reads better than mid-clause, so
    that is tried first.
    """
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return [text]

    # prefer splitting after a '.' near the middle
    mid = len(text) // 2
    best, best_dist = None, None
    for i, ch in enumerate(text):
        if ch == "." and i < len(text) - 1:
            d = abs(i - mid)
            if best_dist is None or d < best_dist:
                best, best_dist = i, d
    if best is not None:
        a, b = text[: best + 1].strip(), text[best + 1 :].strip()
        if a and b and max(len(a), len(b)) <= max_chars * 1.35:
            return [a, b]

    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if len(trial) <= max_chars or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines - 1:
                break
    rest = " ".join(words[sum(len(l.split()) for l in lines):])
    if rest:
        lines.append(rest)
    return lines[:max_lines] or [text]


# ──────────────────────────────────────────────────────────
# narration
# ──────────────────────────────────────────────────────────

def apply_pronunciation(text: str, fixes: list[dict]) -> tuple[str, int]:
    n = 0
    for fix in fixes:
        src, dst = fix["from"], fix["to"]
        if src in text:
            n += text.count(src)
            text = text.replace(src, dst)
    return text, n


def make_narration(manifest: dict, base: Path, out: Path) -> Path:
    """Render narration with Edge TTS (free, no API key)."""
    import asyncio
    try:
        import edge_tts
    except ImportError:
        sys.exit("edge-tts not installed. Run: pip install edge-tts")

    audio_cfg = manifest["audio"]
    script_path = base / audio_cfg["narration_script"]
    if not script_path.exists():
        sys.exit(f"narration script not found: {script_path}")

    text = script_path.read_text(encoding="utf-8")
    text, nfix = apply_pronunciation(text, manifest.get("pronunciation_fixes", []))
    if nfix:
        print(f"  applied {nfix} pronunciation fix(es)")
        (base / "script_spoken.txt").write_text(text, encoding="utf-8")

    voice = audio_cfg.get("voice", "en-US-GuyNeural")
    rate = audio_cfg.get("rate", "+0%")
    print(f"  Edge TTS  voice={voice}  rate={rate}")

    async def go():
        c = edge_tts.Communicate(text, voice, rate=rate)
        await c.save(str(out))

    asyncio.run(go())
    if not out.exists() or out.stat().st_size < 2000:
        sys.exit("Edge TTS produced no usable audio (network blocked?)")
    return out


# ──────────────────────────────────────────────────────────
# timing
# ──────────────────────────────────────────────────────────

def plan_scenes(manifest: dict, total: float) -> list[dict]:
    """Allocate on-screen time per scene, weighted, compensating for xfade overlap.

    xfade consumes `t` seconds of overlap per transition, so the sum of clip
    durations must exceed the target runtime by (n-1)*t for the final video to
    match the narration length.
    """
    scenes = manifest["scenes"]
    t = float(manifest["transitions"]["duration"])
    n = len(scenes)
    padded_total = total + (n - 1) * t

    weights = [max(1, int(s.get("weight", 1))) for s in scenes]
    wsum = sum(weights)
    MIN = 2.0 + t

    durs = [max(MIN, padded_total * w / wsum) for w in weights]
    scale = padded_total / sum(durs)
    durs = [d * scale for d in durs]

    plan = []
    clock = 0.0
    for s, d in zip(scenes, durs):
        visible = d - t                      # time before the next fade starts
        plan.append({**s, "dur": round(d, 3),
                     "start": round(clock, 3),
                     "visible": round(visible, 3)})
        clock += visible
    return plan


# ──────────────────────────────────────────────────────────
# per-scene clip with Ken Burns + overlay
# ──────────────────────────────────────────────────────────

KB_ZOOM = {
    "hold":         (1.00, 1.00),
    "zoom_in":      (1.00, 1.14),
    "zoom_in_slow": (1.00, 1.07),
    "pull_back":    (1.14, 1.00),
    "zoom_out":     (1.12, 1.00),
}


def clip_ok(path: Path, want: float, fps: int, tol: float = 0.25) -> bool:
    """True if `path` is an already-rendered clip of about the right length."""
    if not path.exists() or path.stat().st_size < 20000:
        return False
    try:
        return abs(probe_duration(path) - want) <= tol
    except Exception:
        return False


def build_clip(scene: dict, base: Path, out: Path, fmt: dict,
               overlay_cfg: dict, font: str | None, resume: bool = False) -> Path:
    W, H, FPS = fmt["width"], fmt["height"], fmt["fps"]
    img = base / scene["image"]
    if not img.exists():
        sys.exit(f"missing scene image: {img}")

    if resume and clip_ok(out, scene["dur"], FPS):
        print(f"  scene {scene['n']:>2}  reusing existing {out.name}")
        return out

    dur = scene["dur"]
    frames = max(2, int(round(dur * FPS)))
    move = scene.get("ken_burns", "zoom_in")
    z0, z1 = KB_ZOOM.get(move, KB_ZOOM["zoom_in"])

    # Oversample only as much as the zoom actually needs, then crop to exact
    # 16:9. Oversampling to 2x (3840x2160) made every frame ~4x more expensive
    # than necessary — a 1.14 zoom only needs ~1.2x headroom.
    SS = round(max(z0, z1, 1.0) * 1.06, 3)
    ow, oh = int(W * SS) // 2 * 2, int(H * SS) // 2 * 2
    pre = (f"scale={ow}:{oh}:force_original_aspect_ratio=increase,"
           f"crop={ow}:{oh},setsar=1")

    if move == "hold":
        vf = f"{pre},scale={W}:{H},fps={FPS}"
    else:
        zexpr = f"{z0}+({z1 - z0})*on/{frames}"
        vf = (f"{pre},zoompan=z='{zexpr}'"
              f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={W}x{H}:fps={FPS}")

    text = scene.get("overlay")
    if text and overlay_cfg.get("enabled"):
        o = overlay_cfg
        t0 = float(o.get("start_offset", 1.5))
        fi = float(o.get("fade_in", 0.6))
        hold = float(o.get("hold", 4.5))
        fo = float(o.get("fade_out", 0.6))
        t1 = min(t0 + fi + hold + fo, max(dur - 0.2, t0 + fi + fo + 0.5))
        alpha = (f"if(lt(t,{t0}),0,"
                 f"if(lt(t,{t0+fi}),(t-{t0})/{fi},"
                 f"if(lt(t,{t1-fo}),1,"
                 f"if(lt(t,{t1}),({t1}-t)/{fo},0))))")

        size = int(o.get("font_size", 54))
        # A 58-char card at size 54 overran the frame, so wrap to <= MAXCH
        # per line (max 2 lines) and stack them. One drawtext per line keeps
        # positioning deterministic — embedded newlines in drawtext are fragile.
        MAXCH = int(o.get("max_chars_per_line", 38))
        lines = wrap_overlay(text, MAXCH)
        line_h = int(size * 1.35)
        bottom = int(H * 0.10)

        for i, line in enumerate(lines):
            y_off = bottom + (len(lines) - 1 - i) * line_h
            dt = [
                f"text='{esc_drawtext(line)}'",
                f"fontsize={size}",
                f"fontcolor={o.get('font_color', 'white')}",
                f"box=1:boxcolor={o.get('box_color', 'black@0.55')}:boxborderw=20",
                "x=(w-text_w)/2",
                f"y=h-th-{y_off}",
                f"alpha='{alpha}'",
            ]
            if font:
                dt.insert(0, f"fontfile='{esc_filter_path(font)}'")
            vf += ",drawtext=" + ":".join(dt)

    run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(img),
         "-vf", vf, "-t", f"{dur:.3f}", "-r", str(FPS),
         "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
         "-pix_fmt", "yuv420p", str(out)],
        desc=f"scene {scene['n']:>2}  {dur:6.2f}s  {move:<13} "
             f"{'overlay' if text else '       '}  -> {out.name}")
    return out


# ──────────────────────────────────────────────────────────
# crossfade chain
# ──────────────────────────────────────────────────────────

def xfade_chain(clips: list[Path], plan: list[dict], t: float,
                out: Path, fmt: dict) -> Path:
    if len(clips) == 1:
        shutil.copy(clips[0], out)
        return out

    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]

    parts = []
    cur = "[0:v]"
    offset = 0.0
    for i in range(1, len(clips)):
        offset += plan[i - 1]["visible"]
        label = f"[vx{i}]"
        parts.append(f"{cur}[{i}:v]xfade=transition=fade"
                     f":duration={t}:offset={offset:.3f}{label}")
        cur = label
    filt = ";".join(parts)

    run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
         "-filter_complex", filt, "-map", cur,
         "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
         "-pix_fmt", "yuv420p", "-r", str(fmt["fps"]), str(out)],
        desc=f"crossfading {len(clips)} scenes ({t}s fades)")
    return out


# ──────────────────────────────────────────────────────────
# audio mux
# ──────────────────────────────────────────────────────────

def mux(video: Path, narration: Path | None, music: Path | None,
        manifest: dict, out: Path) -> Path:
    if narration is None and music is None:
        shutil.copy(video, out)
        return out

    a = manifest["audio"]
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video)]
    filt = []

    # Everything is forced to 48kHz stereo BEFORE mixing. Without this amix
    # adopts the format of its first input - the 24kHz mono TTS - and silently
    # downsamples the music to 12kHz mono, which sounds dull and flat.
    FMT = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"

    if narration:
        cmd += ["-i", str(narration)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]

    if narration and music:
        # asplit because a filter label can only be consumed once, and the
        # narration is needed twice: as the mix source and as the sidechain key.
        filt.append(f"[1:a]{FMT},asplit=2[vo1][vo2]")
        filt.append(f"[2:a]{FMT},volume={a.get('music_volume_in_gaps', 0.22)}[mraw]")
        filt.append("[mraw][vo1]sidechaincompress="
                    "threshold=0.03:ratio=12:attack=20:release=700[mduck]")
        filt.append("[vo2][mduck]amix=inputs=2:duration=first:"
                    "dropout_transition=2:normalize=0[mixed]")
        filt.append("[mixed]loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
        desc = "muxing narration + ducked music (48kHz stereo, -16 LUFS)"
    elif narration:
        filt.append(f"[1:a]{FMT},loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
        desc = "muxing narration (48kHz stereo, -16 LUFS)"
    else:
        vol = a.get("music_volume_under_speech", 0.10)
        filt.append(f"[1:a]{FMT},volume={vol}[aout]")
        desc = "muxing music only"

    cmd += ["-filter_complex", ";".join(filt), "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-ac", "2", "-shortest", str(out)]
    run(cmd, desc=desc)
    return out


# ──────────────────────────────────────────────────────────

def find_font() -> str | None:
    for p in [
        "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if Path(p).exists():
            return p
    return None


def pick_music(manifest: dict) -> Path | None:
    d = ROOT / ".verticals-src" / "music"
    if not d.is_dir():
        return None
    tracks = sorted(list(d.glob("*.mp3")) + list(d.glob("*.wav")))
    return tracks[0] if tracks else None


def build_music_track(manifest: dict, base: Path, plan: list[dict],
                      total: float, out: Path) -> Path | None:
    """Build a single music track from per-act cues timed to scene boundaries.

    A documentary that runs cold -> tense -> elegiac should not sit on one
    looped bed. Each cue covers a scene range from the manifest; cues are
    looped to fill their span and joined with acrossfade so the change of
    mood lands on the act boundary rather than mid-sentence.
    """
    mcfg = manifest.get("music") or {}
    cues = mcfg.get("cues") or []
    if not cues:
        return None

    xf = float(mcfg.get("crossfade", 3.0))
    starts = {s["n"]: s["start"] for s in plan}
    end_of = {s["n"]: s["start"] + s["visible"] for s in plan}
    last_scene = plan[-1]["n"]

    segs: list[Path] = []
    for i, cue in enumerate(cues):
        src = (base / cue["file"]).resolve()
        if not src.exists():
            log_miss = f"  music cue missing, skipping: {src}"
            print(log_miss)
            continue
        a = starts.get(int(cue.get("from_scene", 1)), 0.0)
        b = end_of.get(int(cue.get("to_scene", last_scene)), total)
        span = max(1.0, b - a)
        # overlap so acrossfade has material to work with
        want = span + (xf if i < len(cues) - 1 else 0.0)
        gain = float(cue.get("gain", 1.0))

        seg = out.parent / f"_mus_{i:02d}.wav"
        run(["ffmpeg", "-y", "-loglevel", "error",
             "-stream_loop", "-1", "-i", str(src),
             "-t", f"{want:.3f}",
             "-af", (f"volume={gain},"
                     f"afade=t=in:st=0:d=1.5,"
                     f"afade=t=out:st={max(0.0, want-2.0):.3f}:d=2.0,"
                     f"aresample=48000"),
             "-ac", "2", "-ar", "48000", str(seg)],
            desc=f"music cue {i+1}  scenes {cue.get('from_scene')}-{cue.get('to_scene')}  "
                 f"{span:6.1f}s  {Path(cue['file']).name}")
        segs.append(seg)

    if not segs:
        return None
    if len(segs) == 1:
        shutil.move(str(segs[0]), str(out))
        return out

    inputs: list[str] = []
    for s in segs:
        inputs += ["-i", str(s)]
    parts, cur = [], "[0:a]"
    for i in range(1, len(segs)):
        lbl = f"[m{i}]"
        parts.append(f"{cur}[{i}:a]acrossfade=d={xf}:c1=tri:c2=tri{lbl}")
        cur = lbl
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
         "-filter_complex", ";".join(parts), "-map", cur,
         "-ac", "2", "-ar", "48000", str(out)],
        desc=f"joining {len(segs)} cues with {xf}s crossfades")
    for s in segs:
        s.unlink(missing_ok=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--narration", type=Path, help="Use this audio instead of running TTS")
    ap.add_argument("--music", type=Path, help="Music bed (default: first track in .verticals-src/music/)")
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--silent", action="store_true", help="No audio at all")
    ap.add_argument("--duration", type=float, help="Override total runtime (implies --silent timing)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--work", type=Path, help="Scratch dir (default: <manifest dir>/_work)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true", help="Keep intermediate clips")
    ap.add_argument("--preset", default="medium",
                    help="x264 preset (ultrafast..veryslow). veryfast is ~4x faster than medium.")
    ap.add_argument("--crf", type=int, default=18, help="x264 quality, lower is better")
    ap.add_argument("--resume", action="store_true",
                    help="Reuse scene clips already present in the work dir")
    ap.add_argument("--max-clips", type=int, default=0,
                    help="Render at most N scene clips this pass, then stop "
                         "(use with --resume to render in stages under a time limit)")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH")

    global PRESET, CRF
    PRESET, CRF = args.preset, args.crf

    mpath = args.manifest.resolve()
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    base = mpath.parent
    fmt = manifest["format"]

    print(f"\n{manifest['title']}  —  {fmt['width']}x{fmt['height']} @ {fmt['fps']}fps")
    print(f"manifest : {mpath}")

    if not ffmpeg_has("xfade"):
        sys.exit("this ffmpeg build has no 'xfade' filter — transitions impossible")
    if not ffmpeg_has("zoompan"):
        sys.exit("this ffmpeg build has no 'zoompan' filter — Ken Burns impossible")

    # ---- narration / total duration -------------------------------------
    narration: Path | None = None
    if args.silent or args.duration:
        total = args.duration or 60.0
        print(f"\n[1/5] SILENT mode — target runtime {total:.1f}s")
    elif args.narration:
        narration = args.narration.resolve()
        total = probe_duration(narration)
        print(f"\n[1/5] narration supplied: {narration.name}  {total:.1f}s")
    else:
        print("\n[1/5] narration")
        narration = base / "voice.mp3"
        if not args.dry_run:
            make_narration(manifest, base, narration)
            total = probe_duration(narration)
            print(f"  rendered {narration.name}  {total:.1f}s "
                  f"({int(total//60)}:{int(total%60):02d})")
        else:
            total = 600.0

    # ---- plan ------------------------------------------------------------
    t = float(manifest["transitions"]["duration"])
    plan = plan_scenes(manifest, total)
    print(f"\n[2/5] scene plan  (target {total:.1f}s, {t}s crossfades)")
    print(f"  {'#':>2}  {'clip':>7}  {'visible':>8}  {'start':>8}  move           overlay")
    for s in plan:
        ov = (s.get("overlay") or "")[:34]
        print(f"  {s['n']:>2}  {s['dur']:7.2f}  {s['visible']:8.2f}  "
              f"{s['start']:8.2f}  {s.get('ken_burns','zoom_in'):<13}  {ov}")
    calc = sum(x["visible"] for x in plan) + t
    print(f"  predicted final runtime: {calc:.2f}s  (target {total:.2f}s)")

    if args.dry_run:
        print("\n--dry-run: nothing rendered")
        return 0

    # ---- clips -----------------------------------------------------------
    work = (args.work or base / "_work").resolve()
    work.mkdir(parents=True, exist_ok=True)
    font = find_font()
    print(f"\n[3/5] rendering {len(plan)} scene clips"
          + (f"  (font: {Path(font).name})" if font else "  (no font found — overlays skipped)"))
    clips = []
    for s in plan:
        target = work / f"clip_{s['n']:02d}.mp4"
        clips.append(build_clip(s, base, target, fmt,
                                manifest.get("text_overlay", {}), font,
                                resume=args.resume))
        if args.max_clips and sum(1 for c in clips if c.exists()) >= 0:
            done = sum(1 for c in clips)
            if args.max_clips and done >= args.max_clips:
                missing = [p for p in plan[done:]]
                if missing:
                    print(f"\n--max-clips {args.max_clips} reached; "
                          f"{len(missing)} scene(s) still to render.")
                    print("Re-run the same command with --resume to continue.")
                    return 2

    # ---- crossfade -------------------------------------------------------
    print(f"\n[4/5] transitions")
    merged = xfade_chain(clips, plan, t, work / "merged.mp4", fmt)

    # ---- captions --------------------------------------------------------
    cap_cfg = manifest.get("captions") or {}
    cap_file = base / "captions.ass"
    if cap_cfg.get("enabled") and cap_file.exists():
        if not ffmpeg_has("ass"):
            print("  WARNING: this ffmpeg has no libass — captions NOT burned in")
        else:
            burned = work / "with_captions.mp4"
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(merged),
                 "-vf", f"ass='{esc_filter_path(cap_file)}'",
                 "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
                 "-pix_fmt", "yuv420p", str(burned)],
                desc=f"burning captions from {cap_file.name}")
            merged = burned
    elif cap_cfg.get("enabled"):
        print(f"  captions enabled but {cap_file.name} not found — "
              f"run helpers/make_captions.py first")

    # ---- audio -----------------------------------------------------------
    print(f"\n[5/5] audio")
    music = None
    if not (args.no_music or args.silent):
        if args.music:
            music = args.music.resolve()
            print(f"  music: {music.name} (override)")
        else:
            music = build_music_track(manifest, base, plan, total,
                                      work / "music_track.wav")
            if music:
                print(f"  music: {len(manifest.get('music', {}).get('cues', []))} "
                      f"cue(s) -> {music.name}")
            else:
                music = pick_music(manifest)
                if music:
                    print(f"  music: single bed {music.name}")
                else:
                    print("  no music cues or tracks found — skipping bed")
    out = (args.out or base / f"{manifest['job_id']}_FINAL.mp4").resolve()
    mux(merged, narration, music, manifest, out)

    # ---- report ----------------------------------------------------------
    dur = probe_duration(out)
    size = out.stat().st_size / 1e6
    print(f"\nDONE  {out}")
    print(f"  runtime {int(dur//60)}:{int(dur%60):02d} ({dur:.2f}s)   {size:.1f} MB")
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
