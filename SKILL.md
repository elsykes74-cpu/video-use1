---
name: video-use
description: Edit any video by conversation. Transcribe, cut, color grade, generate overlay animations, burn subtitles — for talking heads, montages, tutorials, travel, interviews. No presets, no menus. Ask questions, confirm the plan, execute, iterate, persist. Production-correctness rules are hard; everything else is artistic freedom.
---

# Video Use

## Principle

1. **LLM reasons from raw transcript + on-demand visuals.** The only derived artifact that earns its keep is a packed phrase-level transcript (`takes_packed.md`). Everything else — filler tagging, retake detection, shot classification, emphasis scoring — you derive at decision time.
2. **Audio is primary, visuals follow.** Cut candidates come from speech boundaries and silence gaps. Drill into visuals only at decision points.
3. **Ask → confirm → execute → iterate → persist.** Never touch the cut until the user has confirmed the strategy in plain English.
4. **Generalize.** Do not assume what kind of video this is. Look at the material, ask the user, then edit.
5. **Artistic freedom is the default.** Every specific value, preset, font, color, duration, pitch structure, and technique in this document is a *worked example* from one proven video — not a mandate. Read them to understand what's possible and why each worked. Then make your own taste calls based on what the material actually is and what the user actually wants. **The only things you MUST do are in the Hard Rules section below.** Everything else is yours.
6. **Invent freely.** If the material calls for a technique not described here — split-screen, picture-in-picture, lower-third identity cards, reaction cuts, speed ramps, freeze frames, crossfades, match cuts, L-cuts, J-cuts, speed ramps over breath, whatever — build it. The helpers are ffmpeg and PIL. They can do anything the format supports. Do not wait for permission.
7. **Verify your own output before showing it to the user.** If you wouldn't ship it, don't present it.

## Hard Rules (production correctness — non-negotiable)

These are the things where deviation produces silent failures or broken output. They are not taste, they are correctness. Memorize them.

1. **Subtitles are applied LAST in the filter chain**, after every overlay. Otherwise overlays hide captions. Silent failure.
2. **Per-segment extract → lossless `-c copy` concat**, not single-pass filtergraph. Otherwise you double-encode every segment when overlays are added.
3. **30ms audio fades at every segment boundary** (`afade=t=in:st=0:d=0.03,afade=t=out:st={dur-0.03}:d=0.03`). Otherwise audible pops at every cut.
4. **Overlays use `setpts=PTS-STARTPTS+T/TB`** to shift the overlay's frame 0 to its window start. Otherwise you see the middle of the animation during the overlay window.
5. **Master SRT uses output-timeline offsets**: `output_time = word.start - segment_start + segment_offset`. Otherwise captions misalign after segment concat.
6. **Never cut inside a word.** Snap every cut edge to a word boundary from the Scribe transcript.
7. **Pad every cut edge.** Working window: 30–200ms. Scribe timestamps drift 50–100ms — padding absorbs the drift. Tighter for fast-paced, looser for cinematic.
8. **Word-level verbatim ASR only.** Never SRT/phrase mode (loses sub-second gap data). Never normalized fillers (loses editorial signal).
9. **Cache transcripts per source.** Never re-transcribe unless the source file itself changed.
10. **Parallel sub-agents for multiple animations.** Never sequential. Spawn N at once via the `Agent` tool; total wall time ≈ slowest one.
11. **Strategy confirmation before execution.** Never touch the cut until the user has approved the plain-English plan.
12. **All session outputs in `<videos_dir>/edit/`.** Never write inside the `video-use/` project directory.

Everything else in this document is a worked example. Deviate whenever the material calls for it.

## Directory layout

The skill lives in `video-use/`. User footage lives wherever they put it. All session outputs go into `<videos_dir>/edit/`.

```
<videos_dir>/
├── <source files, untouched>
└── edit/
    ├── project.md               ← memory; appended every session
    ├── takes_packed.md          ← phrase-level transcripts, the LLM's primary reading view
    ├── edl.json                 ← cut decisions
    ├── transcripts/<name>.json  ← cached raw Scribe JSON
    ├── animations/slot_<id>/    ← per-animation source + render + reasoning
    ├── clips_graded/            ← per-segment extracts with grade + fades
    ├── master.srt               ← output-timeline subtitles
    ├── downloads/               ← yt-dlp outputs
    ├── verify/                  ← debug frames / timeline PNGs
    ├── preview.mp4
    └── final.mp4
```

## Setup

First-time install lives in `install.md` (clone, deps, ffmpeg, skill registration, API key). Don't re-run it every session; on cold start just verify:

- `ELEVENLABS_API_KEY` resolves — either in the environment or in `.env` at the video-use repo root. If missing, ask the user to paste one and write it to `.env` (never to the user's `<videos_dir>`).
- `ffmpeg` + `ffprobe` on PATH.
- Python deps installed (`uv sync` or `pip install -e .` inside the repo).
- Node.js + npm available if the session needs HyperFrames or Remotion slots. HyperFrames currently requires Node.js 22+.
- `yt-dlp`, HyperFrames, Remotion, Manim installed only on first use.
- First-use animation setup happens inside the slot directory, never at the video-use repo root. HyperFrames can be invoked with `npx --yes hyperframes ...`; Remotion can be scaffolded with `npx create-video@latest` or installed as a project-local dependency before using its `remotion render` command.
- This skill vendors `skills/manim-video/`. Read its SKILL.md when building a Manim slot.

Helpers (`helpers/transcribe.py`, `helpers/render.py`, etc.) live alongside this SKILL.md. Resolve their paths relative to the directory containing this file — the skill is typically symlinked at `~/.claude/skills/video-use/` or `~/.codex/skills/video-use/`.

## Helpers

- **`transcribe.py <video>`** — single-file Scribe call. `--num-speakers N` optional. Cached.
- **`transcribe_batch.py <videos_dir>`** — 4-worker parallel transcription. Use for multi-take.
- **`pack_transcripts.py --edit-dir <dir>`** — `transcripts/*.json` → `takes_packed.md` (phrase-level, break on silence ≥ 0.5s).
- **`timeline_view.py <video> <start> <end>`** — filmstrip + waveform PNG. On-demand visual drill-down. **Not a scan tool** — use it at decision points, not constantly.
- **`render.py <edl.json> -o <out>`** — per-segment extract → concat → overlays (PTS-shifted) → subtitles LAST. `--preview` for 720p fast. `--build-subtitles` to generate master.srt inline.
- **`grade.py <in> -o <out>`** — ffmpeg filter chain grade. Presets + `--filter '<raw>'` for custom.
- **`ken_burns.py <photo> -o <clip.mp4>`** — convert a still photo to a video clip with Ken Burns zoom/pan motion. `--effect zoom_in|zoom_out|pan_right|pan_left|pan_up|ken_burns`. `--duration` (default 6s). `--size 1080x1920` for vertical output. `--batch` to process a whole folder of images. Output is a standard MP4 with silent audio — drop it into `sources` in `edl.json` like any video clip.
- **`youtube_stats.py`** — fetch YouTube channel analytics via YouTube Data API v3. Reads `YOUTUBE_API_KEY` / `YOUTUBE_CHANNEL_ID` from `.env`. Outputs channel overview (subscribers, total views, video count) + per-video stats (views, likes, comments) for recent uploads. `--max-videos N` (default 5). Also importable: `channel_stats(key, id)` and `recent_videos(key, id, n)` return dicts for programmatic use.
- **`notebooklm_research.py <topic>`** — NotebookLM-style deep research using Gemini API. Reads `GEMINI_API_KEY` from `.env`. Outputs `research/<slug>.json` containing: research summary, 5 emotional angles, N voiceover scripts (timed, word-counted), TikTok title/description/hashtags/pinned comment. `--scripts N` (default 3). Run before every new video to generate ready-to-paste ElevenLabs scripts.
- **`download_reference.py <url_or_query>`** — Download YouTube videos or audio for reference material using yt-dlp. Saves to `reference/<slug>/` with metadata JSON. `--search` to search by keyword instead of URL. `--audio-only` for MP3. `--max N` for multiple results. Use to pull concert footage, interviews, or tour documentation for research.

For animations, create `<edit>/animations/slot_<id>/` with `Bash` and spawn a sub-agent via the `Agent` tool.

## The process

1. **Inventory.** `ffprobe` every source. `transcribe_batch.py` on the directory. `pack_transcripts.py` to produce `takes_packed.md`. Sample one or two `timeline_view`s for a visual first impression.
2. **Pre-scan for problems.** One pass over `takes_packed.md` to note verbal slips, obvious mis-speaks, or phrasings to avoid. Plain list, feed into the editor brief.
3. **Converse.** Describe what you see in plain English. Ask questions *shaped by the material*. Collect: content type, target length/aspect, aesthetic/brand direction, pacing feel, must-preserve moments, must-cut moments, animation and grade preferences, subtitle needs. Do not use a fixed checklist — the right questions are different every time.
4. **Propose strategy.** 4–8 sentences: shape, take choices, cut direction, animation plan, grade direction, subtitle style, length estimate. **Wait for confirmation.**
5. **Execute.** Produce `edl.json` via the editor sub-agent brief. Drill into `timeline_view` at ambiguous moments. Build animations in parallel sub-agents. Apply grade per-segment. Compose via `render.py`.
6. **Preview.** `render.py --preview`.
7. **Self-eval (before showing the user).** Run `timeline_view` on the **rendered output** (not the sources) at every cut boundary (±1.5s window). Check each image for:
   - Visual discontinuity / flash / jump at the cut
   - Waveform spike at the boundary (audio pop that slipped past the 30ms fade)
   - Subtitle hidden behind an overlay (Rule 1 violation)
   - Overlay misaligned or showing wrong frames (Rule 4 violation)

   Also sample: first 2s, last 2s, and 2–3 mid-points — check grade consistency, subtitle readability, overall coherence. Run `ffprobe` on the output to verify duration matches the EDL expectation.

   If anything fails: fix → re-render → re-eval. **Cap at 3 self-eval passes** — if issues remain after 3, flag them to the user rather than looping forever. Only present the preview once the self-eval passes.
8. **Iterate + persist.** Natural-language feedback, re-plan, re-render. Never re-transcribe. Final render on confirmation. Append to `project.md`.

## Cut craft (techniques)

- **Audio-first.** Candidate cuts from word boundaries and silence gaps.
- **Preserve peaks.** Laughs, punchlines, emphasis beats. Extend past punchlines to include reactions — the laugh IS the beat.
- **Speaker handoffs** benefit from air between utterances. Common values: 400–600ms. Less for fast-paced, more for cinematic. Taste call.
- **Audio events as signals.** `(laughs)`, `(sighs)`, `(applause)` mark beats. Extend past them.
- **Silence gaps are cut candidates.** Silences ≥400ms are usually the cleanest. 150–400ms phrase boundaries are usable with a visual check. <150ms is unsafe (mid-phrase).
- **Example cut padding** (the launch video shipped with this): 50ms before the first kept word, 80ms after the last. Tighter for montage energy, looser for documentary. Stay in the 30–200ms working window (Hard Rule 7).
- **Never reason audio and video independently.** Every cut must work on both tracks.

## The packed transcript (primary reading view)

`pack_transcripts.py` reads all `transcripts/*.json` and produces one markdown file where each take is a list of phrase-level lines, each prefixed with its `[start-end]` time range. Phrases break on any silence ≥ 0.5s OR speaker change. This is the artifact the editor sub-agent reads to pick cuts — it gives word-boundary precision from text alone at 1/10 the tokens of raw JSON.

Example line:
```
## C0103  (duration: 43.0s, 8 phrases)
  [002.52-005.36] S0 Ninety percent of what a web agent does is completely wasted.
  [006.08-006.74] S0 We fixed this.
```

## Editor sub-agent brief (for multi-take selection)

When the task is "pick the best take of each beat across many clips," spawn a dedicated sub-agent with a brief shaped like this. The structure is load-bearing; the pitch-shape example is not.

```
You are editing a <type> video. Pick the best take of each beat and 
assemble them chronologically by beat, not by source clip order.

INPUTS:
  - takes_packed.md (time-annotated phrase-level transcripts of all takes)
  - Product/narrative context: <2 sentences from the user>
  - Speaker(s): <name, role, delivery style note>
  - Expected structure: <pick an archetype or invent one>
  - Verbal slips to avoid: <list from the pre-scan pass>
  - Target runtime: <seconds>

Common structural archetypes (pick, adapt, or invent):
  - Tech launch / demo:   HOOK → PROBLEM → SOLUTION → BENEFIT → EXAMPLE → CTA
  - Tutorial:             INTRO → SETUP → STEPS → GOTCHAS → RECAP
  - Interview:            (QUESTION → ANSWER → FOLLOWUP) repeat
  - Travel / event:       ARRIVAL → HIGHLIGHTS → QUIET MOMENTS → DEPARTURE
  - Documentary:          THESIS → EVIDENCE → COUNTERPOINT → CONCLUSION
  - Music / performance:  INTRO → VERSE → CHORUS → BRIDGE → OUTRO
  - Or invent your own.

RULES:
  - Start/end times must fall on word boundaries from the transcript.
  - Pad cut boundaries (working window 30–200ms).
  - Prefer silences ≥ 400ms as cut targets.
  - Unavoidable slips are kept if no better take exists. Note them in "reason".
  - If over budget, revise: drop a beat or trim tails. Report total and self-correct.

OUTPUT (JSON array, no prose):
  [{"source": "C0103", "start": 2.42, "end": 6.85, "beat": "HOOK",
    "quote": "...", "reason": "..."}, ...]

Return the final EDL and a one-line total runtime check.
```

## Color grade (when requested)

Your job is to **reason about the image**, not apply a preset. Look at a frame (via `timeline_view`), decide what's wrong, adjust one thing, look again.

Mental model is ASC CDL. Per channel: `out = (in * slope + offset) ** power`, then global saturation. `slope` → highlights, `offset` → shadows, `power` → midtones.

**Example filter chains** (`grade.py` has `--list-presets`; use them as starting points or mix your own):

- **`warm_cinematic`** — retro/technical, subtle teal/orange split, desaturated. Shipped in a real launch video. Safe for talking heads.
- **`vintage_warm`** — archival/documentary look for 1950s-70s footage. Lifts muddy blacks, adds amber warmth, reduces over-saturation from tape digitization. Gentler than warm_cinematic. Good for Elvis/Motown-era concert and TV footage.
- **`neutral_punch`** — minimal corrective: contrast bump + gentle S-curve. No hue shifts.
- **`none`** — straight copy. Default when the user hasn't asked.

For anything else — portraiture, nature, product, music video, documentary — invent your own chain. `grade.py --filter '<raw ffmpeg>'` accepts any filter string.

Hard rules: apply **per-segment during extraction** (not post-concat, which re-encodes twice). Never go aggressive without testing skin tones.

## Subtitles (when requested)

Subtitles have three dimensions worth reasoning about: **chunking** (1/2/3/sentence per line), **case** (UPPER/Title/Natural), and **placement** (margin from bottom). The right combo depends on content.

**Worked styles** — pick, adapt, or invent:

**`bold-overlay`** — short-form tech launch, fast-paced social. 2-word chunks, UPPERCASE, break on punctuation, Helvetica 18 Bold, white-on-outline, `MarginV=35`. `render.py` ships with this as `SUB_FORCE_STYLE`.

```
FontName=Helvetica,FontSize=18,Bold=1,
PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,
BorderStyle=1,Outline=2,Shadow=0,
Alignment=2,MarginV=35
```

**`natural-sentence`** (if you invent this mode) — narrative, documentary, education. 4–7 word chunks, sentence case, break on natural pauses, `MarginV=60–80`, larger font for readability, slightly wider max-width. No shipped force_style — design one if you need it.

Invent a third style if neither fits. Hard rules: subtitles LAST (Rule 1), output-timeline offsets (Rule 5).

## Animations (when requested)

Animations match the content and the brand. **Get the palette, font, and visual language from the conversation** — never assume a default. If the user hasn't told you, propose a palette in the strategy phase and wait for confirmation before building anything.

**Tool options:**

Pick the engine per animation slot. Do not default to Remotion just because the animation is web-adjacent.

- **HyperFrames** — Browser-native HTML/CSS/GSAP video compositions: product UI motion, website-to-video or mockup-to-video captures, kinetic typography, landing-page/storyboard promos, data-driven UI states, transparent WebM overlays, and clips that need deterministic frame capture plus HyperFrames lint/validate/render checks. Best when the animation should be authored and verified like a web composition instead of a React component tree.
- **Remotion** — React/CSS compositions with component state, reusable React primitives, or an existing Remotion brand system. Best when the user specifically asks for React/Remotion or when React composition is the simpler authoring model.
- **Manim** — formal diagrams, state machines, equation derivations, graph morphs. Read `skills/manim-video/SKILL.md` and its references for depth.
- **PIL + PNG sequence + ffmpeg** — simple overlay cards: counters, typewriter text, single bar reveals, progressive draws. Fast to iterate, any aesthetic you want. The launch video used this.

For HyperFrames slots, scaffold the slot inside `edit/animations/slot_<id>/` with `npx --yes hyperframes init . --example blank --non-interactive --skip-skills`, build the HTML composition there, run the HyperFrames checks that fit the slot (`lint`, `validate`, and a draft render when practical), then produce the final overlay video with `npx --yes hyperframes render . -o render.mp4` or `--format webm -o render.webm` when alpha is required. Point the EDL overlay `file` at the actual rendered path.

For Remotion slots, keep the Remotion project isolated inside the same slot directory, scaffold with `npx create-video@latest` or install Remotion locally there, render the composition to `render.mp4` with the project-local `remotion render` command, and verify duration and dimensions with `ffprobe`.

None is mandatory. Invent hybrids if useful (e.g., PIL background with a HyperFrames or Remotion layer on top).

**Duration rules of thumb, context-dependent:**

- **Sync-to-narration explanations.** A viewer needs to parse the content at 1×. Rough floor 3s, typical 5–7s for simple cards, 8–14s for complex diagrams. The launch video shipped at 5–7s per simple card.
- **Beat-synced accents** (music video, fast montage). 0.5–2s is fine — they're visual accents, not information. The "readable at 1×" rule becomes *"recognizable at 1×"*, not *"fully parseable."*
- **Hold the final frame ≥ 1s** before the cut (universal).
- **Over voiceover:** total duration ≥ `narration_length + 1s` (universal).
- **Never parallel-reveal independent elements** — the eye can't track two new things at once. One thing, pause, next thing.

**Animation payoff timing (rule for sync-to-narration):** get the payoff word's timestamp. Start the overlay `reveal_duration` seconds earlier so the landing frame coincides with the spoken payoff word. Without this sync the animation feels disconnected.

**Easing** (universal — never `linear`, it looks robotic):

```python
def ease_out_cubic(t):    return 1 - (1 - t) ** 3
def ease_in_out_cubic(t):
    if t < 0.5: return 4 * t ** 3
    return 1 - (-2 * t + 2) ** 3 / 2
```

`ease_out_cubic` for single reveals (slow landing). `ease_in_out_cubic` for continuous draws.

**Typing text anchor trick:** center on the FULL string's width, not the partial-string width — otherwise text slides left during reveal.

**Example palette** (the launch video — one aesthetic among infinite):
- Background `(10, 10, 10)` near-black
- Accent `#FF5A00` / `(255, 90, 0)` orange
- Labels `(110, 110, 110)` dim gray
- Font: Menlo Bold at `/System/Library/Fonts/Menlo.ttc` (index 1)
- ≤ 2 accent colors, ~40% empty space, minimal chrome
- Result: terminal / retro tech feel

This is one style. If the brand is warm and serif, use that. If it's colorful and playful, use that. If the user handed you a style guide, follow it. If they didn't, propose one and confirm.

**Parallel sub-agent brief** — each animation is one sub-agent spawned via the `Agent` tool. Each prompt is self-contained (sub-agents have no parent context). Include:

1. One-sentence goal: *"Build ONE animation: [spec]. Nothing else."*
2. Absolute output path (`<edit>/animations/slot_<id>/render.mp4`)
3. Exact technical spec: resolution, fps, codec, pix_fmt, CRF, duration
4. Style palette as concrete values (RGB tuples, hex, or reference to a design system)
5. Font path with index
6. Frame-by-frame timeline (what happens when, with easing)
7. Anti-list ("no chrome, no extras, no titles unless specified")
8. Code pattern reference (copy helpers inline, don't import across slots)
9. Deliverable checklist (script, render, verify duration via ffprobe, report)
10. **"Do not ask questions. If anything is ambiguous, pick the most obvious interpretation and proceed."**

One sub-agent = one file (unique filenames, parallel agents don't overwrite each other).

## Output spec

Match the source unless the user asked for something specific. Common targets: `1920×1080@24` cinematic, `1920×1080@30` screen content, `1080×1920@30` vertical social, `3840×2160@24` 4K cinema, `1080×1080@30` square. `render.py` defaults the scale to 1080p from any source; pass `--filter` or edit the extract command for other targets. Worth asking the user which delivery format matters.

## EDL format

```json
{
  "version": 1,
  "sources": {"C0103": "/abs/path/C0103.MP4", "C0108": "/abs/path/C0108.MP4"},
  "ranges": [
    {"source": "C0103", "start": 2.42, "end": 6.85,
     "beat": "HOOK", "quote": "...", "reason": "Cleanest delivery, stops before slip at 38.46."},
    {"source": "C0108", "start": 14.30, "end": 28.90,
     "beat": "SOLUTION", "quote": "...", "reason": "Only take without the false start."}
  ],
  "grade": "warm_cinematic",
  "overlays": [
    {"file": "edit/animations/slot_1/render.mp4", "start_in_output": 0.0, "duration": 5.0}
  ],
  "subtitles": "edit/master.srt",
  "total_duration_s": 87.4
}
```

`grade` is a preset name or raw ffmpeg filter. `overlays` are rendered animation clips. `subtitles` is optional and applied LAST.

## Memory — `project.md`

Append one section per session at `<edit>/project.md`:

```markdown
## Session N — YYYY-MM-DD

**Strategy:** one paragraph describing the approach
**Decisions:** take choices, cuts, grades, animations + why
**Reasoning log:** one-line rationale for non-obvious decisions
**Outstanding:** deferred items
```

On startup, read `project.md` if it exists and summarize the last session in one sentence before asking whether to continue.

## FOREVER MICHAEL TikTok Workflow

End-to-end pipeline for turning raw TikTok concert footage into a branded, narrated, captioned 4K post.

### Pipeline (in order)

**0. Research & Script (NotebookLM)**
Before touching any video, build your script in [NotebookLM](https://notebooklm.google.com):

1. **Create a notebook** for the specific MJ era/tour/moment
2. **Upload sources** — Wikipedia articles, concert reviews, fan accounts, interview transcripts, setlists, tour programs. The more specific the better (e.g. "HIStory World Tour 1996-97 fan reactions")
3. **Generate the script** using this prompt template:
```
Write a 25-30 second emotional voiceover narration for a TikTok video showing [DESCRIBE THE FOOTAGE — e.g. "Michael Jackson pulling a fan onto the stage during the HIStory tour and embracing her while the crowd goes wild"].

Tone: cinematic, reverent, second-person. Make the viewer feel like THEY are in that moment.
Structure: hook question → what's happening → emotional impact → legacy line
Style: short punchy sentences. No filler. Every word earns its place.
Do NOT mention song titles or dates — keep it timeless.
End with a line about how we still feel this today.
```
4. **Refine** — ask follow-up questions: "make it more emotional", "shorten to 20 seconds", "make the hook stronger"
5. **Use Audio Overview** to hear a two-person conversation about the footage context — mine it for angles and facts you hadn't considered
6. Copy the final script → paste into ElevenLabs (Step 5)

**NotebookLM source library to build over time:**
- MJ HIStory tour reviews + setlists
- MJ Dangerous tour documentation
- Rolling Stone / NME concert reviews
- Fan accounts from r/MichaelJackson
- MJ interviews about connecting with fans
- Grammy / award show performance transcripts

**1. Ingest**
- Accept upload or Google Drive link (`gdown` for Drive: `gdown --fuzzy "<share_url>" -O input.mp4`)
- Probe with static FFmpeg ffprobe: dimensions, duration, codec
- Static FFmpeg lives in scratchpad at `ffmpeg-7.0.2-amd64-static/` (downloaded from johnvansickle.com if not present)

**2. Watermark removal**
- User annotates screenshot with red circle around watermark
- Extract a frame, eyeball coordinates → `crop=W:H:X:Y`
- FFmpeg filter: `split[base][wm];[wm]crop=W:H:X:Y,boxblur=15:5[blurred];[base][blurred]overlay=X:Y`
- Use `boxblur`, NOT `avgblur` (avgblur absent in static FFmpeg 7.0.2)

**3. FOREVER MICHAEL logo overlay**
- Logo: white-on-black PNG (`79239fd0-1000086052.jpg` in uploads)
- Make black transparent with PIL (`pixels where R,G,B < 40 → alpha=0`)
- Scale to ~180px wide, place centered over watermark coordinates
- FFmpeg: `[0:v]split[base][bg];[bg]crop=...,boxblur=...[blurred];[base][blurred]overlay=...[cleaned];[1:v]scale=180:179[logo];[cleaned][logo]overlay=X:Y`

**4. Build 3-segment structure**

| Segment | Duration | Source |
|---|---|---|
| Intro title card | 9s | PIL-rendered PNG → `-loop 1` FFmpeg, fade in/out |
| Main footage | original × 1.25 (~80% speed) | `setpts=1.25*PTS`, `atempo=0.8`, `volume=0.25` |
| FOREVER MICHAEL outro | 9s | Logo centered on black PNG → `-loop 1` FFmpeg |

Concat with `ffmpeg -f concat -safe 0 -i list.txt`

Intro card style: black background, white regular font top lines, gold bold (`255,215,80`) on "Michael Jackson?", PIL DejaVuSans-Bold, centered, y≈780/855/940 in 1080×1920

**5. ElevenLabs voiceover**
- Key: `ELEVENLABS_API_KEY` in `.env`
- Voice: **Young Jamal** — `voice_id: 6OzrBCQf8cjERkYgzSg8`
- Endpoint: `POST /v1/text-to-speech/{voice_id}/with-timestamps` → returns `audio_base64` + `alignment`
- Settings: `stability=0.45, similarity_boost=0.80, style=0.35, use_speaker_boost=True`
- Model: `eleven_multilingual_v2`
- The `alignment` dict has `characters`, `character_start_times_seconds`, `character_end_times_seconds`

**6. ASS captions from alignment**
- Group characters → words (split on space/newline)
- Chunk 4 words per caption line, ALL CAPS
- Add `VO_DELAY` (2.0s) to all timestamps
- ASS style for 4K (PlayResX=1080, PlayResY=1920):
```
Style: Cap,DejaVu Sans,62,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,2,0,1,4,2,2,40,40,720,1
```
- `MarginV=720` → captions land just below center (1920-720=1200px from top = 62% down), above TikTok UI
- `MarginV=80` → bottom of frame (for reference)
- Use `ass` filter NOT `subtitles` filter (subtitles silently fails in some builds)

**7. Audio auto-duck mix**
VO starts at t=2s (adelay=2000ms), ends at `VO_duration + 2.0s`.
```
[bg_audio]volume=volume='if(lt(t,2),4.0,if(lte(t,VO_END),0.32,if(lte(t,VO_END+2),(t-VO_END)/2.0*3.68+0.32,4.0)))':eval=frame[bg];
[vo]adelay=2000|2000,volume=1.0[vo];
[bg][vo]amix=inputs=2:duration=first:dropout_transition=1[mixed]
```
- `4.0x` of NO_VO audio = 100% original (crowd at 25% in seg_main × 4 = 100%)
- `0.32x` = ~8% original (ducked under narrator)
- 2-second ramp back up after VO ends

**8. 4K encode**
- Upscale: `scale=2160:3840:flags=lanczos`
- Codec: `libx265 -preset fast -crf 28 -pix_fmt yuv420p -tag:v hvc1`
- Audio: `aac -b:a 192k`
- Target file size: ~28MB for 70s at these settings (fits 30MB SendUserFile limit)
- Encode time: ~6 min at 4K H.265 on CPU

**9. TikTok copy formula**
- **Title**: hook question or dramatic statement (first line = TikTok Title field)
- **Description**: mirrors the VO script, 3-5 short paragraphs
- **Hashtags**: `#MichaelJackson #MJForever #ForeverMichael #KingOfPop #Legend #MJ #17Years #Concert #GOAT #fyp #foryou #viral #mjconcert #michaeljacksonfan #iconic #emotional #mjhistory #neverforget #mjlove`
- **Pinned comment**: question that drives replies + emoji reaction (e.g. "Drop a 🕊️ if you would have passed out 😭 What song was he performing? 👇")

### Key assets
- FOREVER MICHAEL logo: `uploads/79239fd0-1000086052.jpg` (white silhouette + text on black)
- Young Jamal voice ID: `6OzrBCQf8cjERkYgzSg8`
- Static FFmpeg: download from `https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz`

### Voiceover script template (MJ concert fan-pull moment)
```
Imagine standing in a crowd of 70,000 people...
and suddenly, Michael Jackson points at you.
Not the person next to you. You.
This is what that moment looked like.
This is what his music did to people — it didn't just move you.
It broke you open.
Tears. Screaming. Strangers holding each other like family.
No stage, no screen, no algorithm has ever touched what Michael created in that room.
This wasn't a concert.
This was a religious experience.
And 17 years later... we're still not over it.
```

## Anti-patterns

Things that consistently fail regardless of style:

- **Hierarchical pre-computed codec formats** with USABILITY / tone tags / shot layers. Over-engineering. Derive from the transcript at decision time.
- **Hand-tuned moment-scoring functions.** The LLM picks better than any heuristic you'll write.
- **Whisper SRT / phrase-level output.** Loses sub-second gap data. Always word-level verbatim.
- **Running Whisper locally on CPU.** Slow and it normalizes fillers. Use hosted Scribe.
- **Burning subtitles into base before compositing overlays.** Overlays hide them. (Hard Rule 1.)
- **Single-pass filtergraph when you have overlays.** Double re-encodes. Use per-segment extract → concat.
- **Linear animation easing.** Looks robotic. Always cubic.
- **Hard audio cuts at segment boundaries.** Audible pops. (Hard Rule 3.)
- **Typing text centered on the partial string.** Text slides left as it grows.
- **Sequential sub-agents for multiple animations.** Always parallel.
- **Editing before confirming the strategy.** Never.
- **Re-transcribing cached sources.** Immutable outputs of immutable inputs.
- **Assuming what kind of video it is.** Look first, ask second, edit last.
