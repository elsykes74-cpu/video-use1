# video-use1 — AI documentary pipeline

Turns a script + still images into a finished narrated documentary video.
Built for "The King Lives" (Elvis) and a Michael Jackson channel.

**Environment: Windows. Read the GOTCHAS section before running anything —
several of them cost hours to find and every one will bite again.**

---

## Build a video

```bash
python helpers/make_video.py --project finals/colonel_parker
```

Idempotent and dependency-aware. Each stage runs only if its output is missing
or older than its inputs, so run it as often as you like.

```bash
--redo narration      # force a stage; dependents re-run automatically
--watch               # rebuild forever whenever an input changes
--only captions       # single stage
--preset veryfast     # faster, larger; default is medium/crf19
```

Stages: `script → images → narration → captions → render`

Also: `powershell -ExecutionPolicy Bypass -File .\make.ps1 [-Watch] [-Redo x]`
— a wrapper that finds a real python.exe and puts ffmpeg on PATH.

---

## Starting a new video

```bash
# 1. package zip -> project folder, manifest, prompts.txt
python helpers/ingest.py package --zip "C:/Users/erick/Downloads/Pkg.zip"

# 2. generate prompts.txt in Google Flow (16:9, Nano Banana 2, x2 variants)

# 3. newest Downloads images -> scenes/, matched in generation order
python helpers/ingest.py images --project finals/<name> --dedupe --apply

# 4. build
python helpers/make_video.py --project finals/<name>
```

`ingest images` always dry-runs first. It filters Flow's junk output
(files named `_prompt_`, `Google_Flow`, `Nano_Banana`, `16_9`) and collapses
x2 variants, keeping the larger file. **Matching is by generation time, not
content** — generate prompts in scene order.

---

## The manifest is the contract

`finals/<project>/manifest.json` drives everything. A prompt-to-video pipeline
only has to emit this file.

```jsonc
{
  "format":  { "width": 1920, "height": 1080, "fps": 30 },
  "audio":   { "narration_script": "script.txt", "voice": "en-US-GuyNeural",
               "rate": "-10%" },
  "music":   { "crossfade": 3.0, "cues": [ { "file": "...", "from_scene": 1,
               "to_scene": 7, "gain": 1.0, "mood": "cold, sparse" } ] },
  "transitions": { "duration": 0.9 },
  "text_overlay": { "enabled": false },     // boxed title cards; off - they
                                            // collided with the captions
  "captions": { "enabled": true, "words_per_line": 5, "font_size": 42 },
  "pronunciation_fixes": [ { "from": "Breda", "to": "Bray-dah" } ],
  "scenes": [ { "n": 1, "image": "scenes/x.jpg", "ken_burns": "hold",
                "weight": 47, "overlay": "TEXT", "prompt": "for regeneration" } ]
}
```

- **weight** — share of runtime. Set from the script's act word-counts so
  images track what is being narrated, not an even split.
- **ken_burns** — `hold` / `zoom_in` / `zoom_in_slow` / `pull_back` / `zoom_out`.
  Currently all `hold`; the user dislikes Ken Burns. Originals are preserved
  in `ken_burns_original`.
- **pronunciation_fixes** — applied to the TTS input only. Captions always
  display `script.txt` spelling, never the phonetic version. Fixes must be
  1:1 on word count or the caption mapping falls back with a warning.

---

## Captions: three tiers, best available wins

1. **Edge TTS word boundaries** (`voice_boundaries.json`) — exact by
   construction. `make_narration.py` streams rather than saves, capturing
   `WordBoundary` events.
2. **faster-whisper** — near-exact, works with **any** TTS. Transcribes with
   word timestamps, then aligns the transcript to `script.txt` with difflib
   and carries the timings across, interpolating over mismatches. Measured
   95.4% token match on the current narration.
3. **Pause-anchored DP estimate** — no dependencies. Dynamic programming maps
   sentences onto silence-detected regions. Good, not exact.

```bash
python helpers/make_captions.py --manifest ... --align whisper --whisper-model small
```

---

## GOTCHAS — all of these were live bugs

**`python` is a .cmd shim.** `C:\Users\erick\bin\python.cmd` shadows the real
interpreter. Calling a `.cmd` from a `.bat` without `call` transfers control
and never returns — a batch file will die silently at its first `python` line.
Always resolve a real `python.exe`; `make_video.py` uses `sys.executable`.

**ffmpeg is not on PATH by default.** It lives at
`C:\Users\erick\Downloads\ffmpeg-8.1.1-essentials_build\ffmpeg-8.1.1-essentials_build\bin`
(note the doubled folder name). Version 8.1.1 with libass, libfreetype, NVENC.

**Windows paths inside ffmpeg filters need the drive colon escaped.**
`C:/Windows/Fonts/arialbd.ttf` makes the parser read `C` as an option name.
Use `esc_filter_path()` — backslashes to forward slashes, `:` to `\:`.
Applies to `drawtext=fontfile` and `ass=`.

**`amix` adopts the format of its first input.** Mixing 24 kHz mono TTS with
48 kHz stereo music silently downsampled the music to mono 12 kHz — the log
said "muxing narration + ducked music" and exited 0. Always `aformat` every
input to 48 kHz stereo *before* mixing, and `loudnorm` after.

**A filter label can only be consumed once.** Narration is needed twice — as
the mix source and the sidechain key — so `asplit=2` it first.

**Batch files need CRLF.** `.ps1`/`.bat` written with LF line endings fail
with "cannot find the batch label specified".

**Crossfade re-encodes the whole accumulated timeline.** Chaining `xfade`
across 18 clips is O(n²) on the tail. On a slow box, render in halves and
join. On this machine it is fine.

**The Downloads folder is not redirected.** Files land in
`C:\Users\erick\Downloads`. Flow has no API and no auto-download; images must
be exported manually or generated via the Gemini API instead.

---

## Current project: finals/colonel_parker

"The Man Who Owned The King" — Colonel Tom Parker, 9:17, 18 scenes, 1920x1080.

- `script.txt` 1,416 words · `voice.mp3` Edge TTS en-US-GuyNeural at -10%
- 3 CC0 music cues in `.verticals-src/music/`, chosen by measuring level,
  spectral centroid and flux — not by filename. See `LICENSE-CC0.txt`.
- Scene 5 (the Dutch kitchen at ~1:25) is mismatched to its narration and has
  a replacement prompt at `prompt_scene05_replacement.txt`.
- Six improved Flow images were generated but never retrieved from the browser.

**Open questions the user is deciding:** switching narration to VibeVoice
(community fork) or Chatterbox for a more natural voice; whether to move image
generation from Flow to the Gemini API (~$8–25/month for 500 images) to close
the last manual step.

---

## Security

`.git/config` contains a **GitHub personal access token in plaintext** in the
`origin` URL. It should be revoked and replaced with a credential helper.
Do not commit or push until that is done.

---

## Layout

```
helpers/
  make_video.py            orchestrator - start here
  ingest.py                package zip -> project; Downloads -> scenes
  make_narration.py        Edge TTS + word boundaries
  make_captions.py         3-tier caption alignment
  assemble_production.py   the renderer
  regen_scene.py           Gemini image generation with reference conditioning
finals/<project>/          manifest, script, voice, captions, scenes/, output
.verticals-src/            older 9:16 vertical pipeline (broll, tts, upload)
reference_library/         era-sorted reference photos, mj/ and elvis/
```

`.verticals-src/verticals/` is the earlier vertical-video pipeline. It still
holds `upload.py`, `thumbnail.py` and `tts.py` (multi-provider). Its
`assemble.py` hard-cuts and caps at 6 frames — `helpers/assemble_production.py`
replaced it.
