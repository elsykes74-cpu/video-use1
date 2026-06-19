# Elvis YouTube — Project Template

Copy this file to `<your-elvis-videos-folder>/edit/project.md` before your first session.
Then run `claude` in that folder and say "let's make a video".

---

## Project context

**Channel:** Elvis Presley tribute / documentary YouTube channel
**Target formats:** Long-form YouTube (10–20 min) and clips (3–5 min)
**Output spec:** 1920×1080 @ 24fps, -14 LUFS normalized

**Source material types:**
- Concert footage (live performances, Ed Sullivan, '68 Comeback Special, Aloha from Hawaii, etc.)
- TV/press interviews (vintage 1950s–1970s broadcast quality)
- Still photos (promotional, personal, press photography)

---

## Workflow defaults for this channel

### Color grade
Default: `vintage_warm`
- Lifts muddy blacks and adds amber warmth — correct for digitized 1950s-70s film/tape
- For '68 Comeback Special footage (high-contrast black-and-white or deep color):
  use `auto` per-segment — the auto-grade will detect and correct correctly
- For photos converted with ken_burns.py: auto-grade applied at render time via EDL

### Subtitles
Style: `natural-sentence` (4–6 words per line, sentence case, MarginV=70)
- YouTube viewers are desktop-first; smaller, cleaner captions read better than bold-overlay
- Use `bold-overlay` only if the specific video is designed to be shared as a Short/clip
- Suggested force_style override:
  ```
  FontName=Helvetica,FontSize=16,Bold=0,
  PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,
  BorderStyle=1,Outline=1,Shadow=1,
  Alignment=2,MarginV=70
  ```

### Still photos → video clips
Use `ken_burns.py` to convert photos before adding them to the EDL:
```bash
python /path/to/video-use/helpers/ken_burns.py photo.jpg -o edit/clips/photo_01.mp4 --effect ken_burns --duration 7
```
Batch a whole folder:
```bash
python /path/to/video-use/helpers/ken_burns.py photos/ -o edit/clips/ --batch --effect zoom_in --duration 6
```
Then add the output MP4 to `edl.json` sources like any video file.

---

## Proven video structures for Elvis content

### Tribute / era overview (12–18 min)
```
HOOK          → 30–60s: iconic performance moment, no narration, let Elvis speak
INTRO CARD    → 10s animation: title card with era (e.g., "The Sun Sessions, 1954–1955")
CONTEXT       → 2–3 min: interviews + photos setting the scene
PEAK MOMENT   → 3–4 min: best concert/performance footage, graded, subtitled
BEHIND-SCENES → 2–3 min: press photos with ken_burns + interview clips
LEGACY BEAT   → 1–2 min: reflection clip or quote montage
OUTRO         → 30s: music fade over final photo or performance still
```

### Single-song breakdown (5–8 min)
```
HOOK          → cold open on the song's most famous moment
ORIGIN        → photos + interview about the song's creation
PERFORMANCE   → full or near-full performance footage
IMPACT        → quotes, chart context, cultural moment
OUTRO
```

### Interview deep-dive (8–12 min)
```
HOOK          → most quotable line from the interview
CONTEXT       → who, when, where (photo card with ken_burns + narration)
INTERVIEW     → best exchanges, cleaned up (filler removal, best takes)
COMMENTARY    → supporting footage or photos that illustrate each topic
CLOSING QUOTE → end on a strong Elvis line
```

---

## Animation ideas for this channel

### Date / era cards (PIL)
- Background: near-black `(15, 12, 10)`
- Accent: gold `(212, 175, 55)` — Elvis TCB lightning bolt as decorative element
- Font: serif (e.g., Georgia Bold) for the era name, sans-serif for dates
- Example: `"Memphis, Tennessee — July 1954"` typewriter reveal over 2s

### Location / venue callouts (PIL)
- Lower-third style: thin gold line + white text
- e.g., `"Ed Sullivan Show — September 9, 1956"`

### "Did You Know" fact cards (PIL)
- Full-frame card, dark background, fact in large text
- Source citation in small text at bottom
- 5–7s duration, fade in/out

---

## Cut craft notes for Elvis footage

- **Preserve breath and natural pause before Elvis speaks** — his timing is part of the performance. Don't cut too tight.
- **Concert footage**: cuts should follow musical phrases, not just speech. Silence ≥ 500ms between songs is the natural edit point.
- **Interview footage**: Elvis was a careful, thoughtful speaker — he sometimes pauses long (1–2s) mid-thought. Check before cutting a pause; it may be intentional.
- **Don't cut during applause unless it's very long** — applause is an emotional signal; cutting through it kills the moment.
- **Photo montages**: 5–8 seconds per photo (shorter for energy, longer for reflection). Use different ken_burns effects per photo to vary the motion.

---

## Session log
