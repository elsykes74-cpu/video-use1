#!/usr/bin/env python3
"""Word-synced captions from narration audio + the known script.

No speech recognition. We already know exactly what was said, so instead of
transcribing we ALIGN: ffmpeg's silencedetect finds where the speaker pauses,
those pauses are matched to sentence boundaries in the script, and words are
distributed inside each sentence by character length. For TTS narration -
which pauses reliably at punctuation - this lands very close to true timing
and needs no model download.

If the narration came from Edge TTS you can do better: edge-tts emits
WordBoundary events with exact offsets. Use --boundaries with that JSON and
this script will use real timings instead of estimating.

    python helpers/make_captions.py --manifest finals/colonel_parker/manifest.json
    python helpers/make_captions.py --manifest ... --words-per-line 4
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def probe_duration(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(r.stdout.strip())


def detect_speech(audio: Path, noise_db: int = -34, min_sil: float = 0.28
                  ) -> list[tuple[float, float]]:
    """Return [(start, end)] speech regions using ffmpeg silencedetect."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(audio),
         "-af", f"silencedetect=noise={noise_db}dB:d={min_sil}", "-f", "null", "-"],
        capture_output=True, text=True)
    log = r.stderr
    starts = [float(m) for m in re.findall(r"silence_start:\s*(-?[\d.]+)", log)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*(-?[\d.]+)", log)]
    total = probe_duration(audio)

    speech, cursor = [], 0.0
    for i, s in enumerate(starts):
        if s > cursor + 0.05:
            speech.append((cursor, s))
        cursor = ends[i] if i < len(ends) else total
    if cursor < total - 0.05:
        speech.append((cursor, total))
    return [(a, b) for a, b in speech if b - a > 0.12]


def split_sentences(text: str) -> list[str]:
    text = " ".join(text.split())
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


# ──────────────────────────────────────────────────────────
# whisper alignment - works with ANY tts, not just edge
# ──────────────────────────────────────────────────────────

def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


def whisper_word_times(audio: Path, model_size: str = "base"
                       ) -> list[tuple[str, float, float]]:
    """Word-level timestamps via faster-whisper. Empty list if unavailable."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return []
    print(f"  loading faster-whisper '{model_size}' (first run downloads the model)...")
    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments, _ = model.transcribe(str(audio), word_timestamps=True,
                                   vad_filter=False, beam_size=1)
    out: list[tuple[str, float, float]] = []
    for seg in segments:
        for w in (seg.words or []):
            t = w.word.strip()
            if t:
                out.append((t, float(w.start), float(w.end)))
    return out


def map_timings_to_script(heard: list[tuple[str, float, float]],
                          script_tokens: list[str]
                          ) -> list[tuple[str, float, float]]:
    """Transfer timings from what Whisper heard onto the script's own wording.

    Whisper's transcript will differ from the script - contractions, numbers
    written as digits, the odd misheard word. Align the two token sequences and
    carry the timings across, interpolating over any stretch that did not match
    so no word is left without a time.
    """
    import difflib
    if not heard or not script_tokens:
        return []

    a = [_norm(w) for w, _, _ in heard]
    b = [_norm(w) for w in script_tokens]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)

    times: list[tuple[float, float] | None] = [None] * len(script_tokens)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(j2 - j1):
                _, s, e = heard[i1 + k]
                times[j1 + k] = (s, e)
        elif tag in ("replace", "delete", "insert"):
            # spread the heard span evenly over the script words it covers
            if j2 > j1:
                if i2 > i1:
                    s = heard[i1][1]
                    e = heard[i2 - 1][2]
                else:
                    s = heard[min(i1, len(heard) - 1)][1]
                    e = s
                n = j2 - j1
                step = (e - s) / n if n else 0.0
                for k in range(n):
                    times[j1 + k] = (s + k * step, s + (k + 1) * step)

    # fill any remaining gaps by interpolation
    last = 0.0
    for i, t in enumerate(times):
        if t is None:
            nxt = next((times[j][0] for j in range(i + 1, len(times)) if times[j]), last + 0.3)
            times[i] = (last, max(last + 0.05, nxt))
        last = times[i][1]

    matched = sum(1 for tag, _, _, _, _ in sm.get_opcodes() if tag == "equal")
    ratio = sm.ratio()
    print(f"  aligned transcript to script: {ratio*100:.1f}% token match "
          f"({len(heard)} heard vs {len(script_tokens)} written)")
    return [(script_tokens[i], times[i][0], times[i][1]) for i in range(len(script_tokens))]


def ass_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600); m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def align_sentences_to_regions(sentences: list[str],
                               speech: list[tuple[float, float]]
                               ) -> list[tuple[float, float]]:
    """Assign each sentence a [start, end] by matching it to speech regions.

    The earlier version spread sentences across the timeline in proportion to
    their character length, which accumulates error - a single long pause
    early on pushes everything after it out of sync. Instead, treat the
    detected pauses as hard anchors and use dynamic programming to decide how
    many regions each sentence spans, minimising the mismatch between a
    sentence's share of the text and its share of the audio.
    """
    n_s, n_r = len(sentences), len(speech)
    if n_s == 0 or n_r == 0:
        return []

    lens = [max(1, len(s)) for s in sentences]
    total_len = sum(lens)
    dur = [b - a for a, b in speech]
    total_dur = sum(dur) or 1.0

    # prefix sums for O(1) span cost
    plen, pdur = [0.0], [0.0]
    for x in lens:
        plen.append(plen[-1] + x)
    for x in dur:
        pdur.append(pdur[-1] + x)

    INF = float("inf")
    # cost[i][j] = best cost assigning sentences[0:i] to regions[0:j]
    cost = [[INF] * (n_r + 1) for _ in range(n_s + 1)]
    back = [[0] * (n_r + 1) for _ in range(n_s + 1)]
    cost[0][0] = 0.0

    for i in range(1, n_s + 1):
        want = (plen[i] - plen[i - 1]) / total_len          # share of the text
        # a sentence may span 1..K regions; K small keeps this fast
        K = max(1, min(n_r, 6))
        for j in range(i, n_r + 1):                          # >=1 region each
            best, bestk = INF, 1
            for k in range(1, min(K, j - (i - 1)) + 1):
                prev = cost[i - 1][j - k]
                if prev == INF:
                    continue
                got = (pdur[j] - pdur[j - k]) / total_dur    # share of the audio
                c = prev + abs(want - got)
                if c < best:
                    best, bestk = c, k
            cost[i][j] = best
            back[i][j] = bestk

    # If no complete assignment exists (more sentences than regions, or every
    # path blocked by the span cap) the table has no finite endpoint. Bail out
    # and let the caller fall back rather than walking off the list.
    if cost[n_s][n_r] == INF:
        return []

    spans: list[tuple[float, float]] = []
    j = n_r
    for i in range(n_s, 0, -1):
        k = back[i][j] or 1
        k = max(1, min(k, j))                 # never step past the start
        lo, hi = j - k, j - 1
        if lo < 0 or hi < 0 or hi >= len(speech):
            return []                          # inconsistent table; fall back
        spans.append((speech[lo][0], speech[hi][1]))
        j -= k
    if j != 0:
        return []
    spans.reverse()
    return spans


def build_word_times(sentences: list[str], speech: list[tuple[float, float]],
                     total: float) -> list[tuple[str, float, float]]:
    """Map sentences onto speech regions, then words onto time inside them."""
    spans = align_sentences_to_regions(sentences, speech)
    if spans and len(spans) == len(sentences):
        out: list[tuple[str, float, float]] = []
        for sent, (a, b) in zip(sentences, spans):
            words = sent.split()
            if not words:
                continue
            wl = [max(1, len(w)) for w in words]
            tot = sum(wl)
            span = max(0.25, b - a)
            t = a
            for w, l in zip(words, wl):
                d = span * l / tot
                out.append((w, t, t + d))
                t += d
        return out
    return _build_word_times_proportional(sentences, speech, total)


def _build_word_times_proportional(sentences: list[str],
                                   speech: list[tuple[float, float]],
                                   total: float) -> list[tuple[str, float, float]]:
    """Fallback: spread sentences by length across the speech timeline."""
    # Distribute sentences across speech regions proportionally to length.
    sent_lens = [max(1, len(s)) for s in sentences]
    total_len = sum(sent_lens)
    speech_total = sum(b - a for a, b in speech) or total

    # Walk the speech timeline, consuming it in proportion to sentence length.
    out: list[tuple[str, float, float]] = []
    region_i = 0
    region_pos = speech[0][0] if speech else 0.0

    for sent, slen in zip(sentences, sent_lens):
        want = speech_total * slen / total_len
        # collect [start, end] for this sentence across (possibly) many regions
        sent_start = region_pos
        remaining = want
        while remaining > 0 and region_i < len(speech):
            a, b = speech[region_i]
            if region_pos < a:
                region_pos = a
            avail = b - region_pos
            if avail <= 0:
                region_i += 1
                if region_i < len(speech):
                    region_pos = speech[region_i][0]
                continue
            take = min(avail, remaining)
            region_pos += take
            remaining -= take
            if region_pos >= b - 1e-6:
                region_i += 1
                if region_i < len(speech):
                    region_pos = speech[region_i][0]
        sent_end = region_pos

        words = sent.split()
        if not words:
            continue
        wlens = [max(1, len(w)) for w in words]
        wtotal = sum(wlens)
        span = max(0.25, sent_end - sent_start)
        t = sent_start
        for w, wl in zip(words, wlens):
            d = span * wl / wtotal
            out.append((w, t, t + d))
            t += d
    return out


def group_lines(words: list[tuple[str, float, float]], per_line: int
                ) -> list[tuple[float, float, list[tuple[str, float, float]]]]:
    lines = []
    for i in range(0, len(words), per_line):
        chunk = words[i:i + per_line]
        lines.append((chunk[0][1], chunk[-1][2], chunk))
    return lines


def write_ass(lines, cfg: dict, out: Path, w: int, h: int) -> Path:
    fs = int(cfg.get("font_size", 40))
    prim = cfg.get("primary_colour", "&H00FFFFFF")
    hl = cfg.get("highlight_colour", "&H0027A9C9")
    outl = cfg.get("outline_colour", "&H00000000")
    mv = int(cfg.get("margin_v", 90))

    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Arial,{fs},{prim},{hl},{outl},&H64000000,-1,0,0,0,100,100,0,0,1,3,1,2,80,80,{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    rows = []
    for start, end, chunk in lines:
        # karaoke: each word highlights as it is spoken
        parts = []
        for w_, ws, we in chunk:
            cs = int(round(max(0.0, (we - ws)) * 100))   # centiseconds
            safe = w_.replace("{", "(").replace("}", ")")
            parts.append(f"{{\\kf{cs}}}{safe} ")
        text = "".join(parts).strip()
        rows.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Cap,,0,0,0,,{text}")

    out.write_text(head + "\n".join(rows) + "\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--audio", type=Path, help="Default: <manifest dir>/voice.mp3")
    ap.add_argument("--script", type=Path, help="Default: script_spoken.txt then script.txt")
    ap.add_argument("--out", type=Path, help="Default: <manifest dir>/captions.ass")
    ap.add_argument("--words-per-line", type=int)
    ap.add_argument("--align", choices=["auto", "whisper", "estimate"], default="auto",
                    help="auto = tts boundaries, then whisper, then estimate")
    ap.add_argument("--whisper-model", default="base",
                    help="tiny/base/small/medium/large-v3 (bigger = better, slower)")
    ap.add_argument("--boundaries", type=Path,
                    help="Exact word timings JSON from make_narration.py "
                         "(default: <manifest dir>/voice_boundaries.json)")
    args = ap.parse_args()

    m = json.loads(args.manifest.read_text(encoding="utf-8"))
    base = args.manifest.parent
    fmt = m["format"]
    cfg = m.get("captions", {})
    if args.words_per_line:
        cfg["words_per_line"] = args.words_per_line

    audio = args.audio or base / "voice.mp3"
    if not audio.exists():
        print(f"ERROR: narration not found: {audio}", file=sys.stderr)
        return 1

    # Time against what was SPOKEN (phonetic), but display what was WRITTEN.
    # "Bray-dah" must never appear on screen - the viewer reads "Breda".
    spoken_p = args.script or (base / "script_spoken.txt")
    display_p = base / "script.txt"
    if not spoken_p.exists():
        spoken_p = display_p
    if not display_p.exists():
        display_p = spoken_p
    if not spoken_p.exists():
        print(f"ERROR: script not found: {spoken_p}", file=sys.stderr)
        return 1

    total = probe_duration(audio)
    speech = None        # only set by the estimate path
    sentences = None     # only set by the estimate path

    # Exact timings if the TTS gave us word boundaries; estimate only as fallback.
    bpath = args.boundaries or (base / "voice_boundaries.json")
    words: list[tuple[str, float, float]] = []
    if bpath.exists():
        try:
            data = json.loads(bpath.read_text(encoding="utf-8"))
            words = [(d["text"], float(d["start"]), float(d["end"])) for d in data]
            print(f"timing     : EXACT - {len(words)} word boundaries from {bpath.name}")
        except Exception as e:
            print(f"WARNING: could not read {bpath.name} ({e}); estimating instead",
                  file=sys.stderr)
            words = []

    disp_tokens_early = " ".join(
        (base / "script.txt").read_text(encoding="utf-8").split()).split() \
        if (base / "script.txt").exists() else []

    if not words and args.align != "estimate":
        # Works with any TTS - VibeVoice, Chatterbox, ElevenLabs - not just Edge.
        heard = whisper_word_times(audio, args.whisper_model)
        if heard:
            words = map_timings_to_script(heard, disp_tokens_early)
            if words:
                print(f"timing     : WHISPER - {len(words)} words from "
                      f"'{args.whisper_model}' model")
        elif args.align == "whisper":
            print("ERROR: --align whisper but faster-whisper is not installed.\n"
                  "       pip install faster-whisper", file=sys.stderr)
            return 1

    if not words:
        speech = detect_speech(audio)
        sentences = split_sentences(spoken_p.read_text(encoding="utf-8"))
        words = build_word_times(sentences, speech, total)
        print(f"timing     : ESTIMATED from {len(speech)} silence-detected regions "
              f"(install faster-whisper, or use Edge TTS, for exact timings)")

    # Swap in display spelling. Every pronunciation fix in the manifest is a
    # 1:1 word-count substitution, so the sequences line up token for token.
    disp_tokens = " ".join(display_p.read_text(encoding="utf-8").split()).split()
    if len(disp_tokens) == len(words):
        words = [(disp_tokens[i], s, e) for i, (_, s, e) in enumerate(words)]
        print(f"display    : using script.txt spelling ({len(disp_tokens)} tokens matched)")
    else:
        print(f"WARNING: spoken/display word counts differ "
              f"({len(words)} vs {len(disp_tokens)}) - captions will show the "
              f"phonetic spelling. Check pronunciation_fixes are 1:1 on words.",
              file=sys.stderr)
    per_line = int(cfg.get("words_per_line", 5))
    lines = group_lines(words, per_line)

    out = args.out or base / "captions.ass"
    write_ass(lines, cfg, out, fmt["width"], fmt["height"])

    # 'speech' and 'sentences' only exist when the estimate path ran; the
    # whisper and boundaries paths skip silence detection entirely.
    print(f"audio      : {audio.name}  {total:.1f}s")
    if speech is not None:
        covered = sum(b - a for a, b in speech)
        print(f"speech     : {len(speech)} regions, {covered:.1f}s "
              f"({covered/total*100:.0f}% of runtime)")
    print(f"script     : {len(words)} words"
          + (f", {len(sentences)} sentences" if sentences is not None else ""))
    print(f"captions   : {len(lines)} lines at {per_line} words each")
    print(f"written    : {out}")
    if words:
        print(f"\nfirst: {words[0][0]!r} @ {words[0][1]:.2f}s"
              f"   last: {words[-1][0]!r} @ {words[-1][2]:.2f}s  (audio {total:.2f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
