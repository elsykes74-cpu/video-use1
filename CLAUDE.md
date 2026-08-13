# video-use1 — Claude Code Project Memory

This repo produces viral TikTok / YouTube Shorts from archival footage.
Channel: **@mjforeverlove0** (Michael Jackson tribute content)

---

## Environment & Paths

```
SCRATCHPAD  /tmp/claude-0/-home-user-video-use1/<session-id>/scratchpad
FFMPEG      $SCRATCHPAD/ffmpeg-7.0.2-amd64-static/ffmpeg   ← always use this
UPLOADS     /root/.claude/uploads/<session-id>/
```

**CRITICAL**: Never use the system `ffmpeg`. The static binary at `$SCRATCHPAD/ffmpeg-7.0.2-amd64-static/ffmpeg` is the only one that works. Download it if it doesn't exist:
```bash
cd $SCRATCHPAD
wget -q https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
tar -xf ffmpeg-release-amd64-static.tar.xz
```

**30 MB upload limit** for file delivery in the Claude interface. Encode at CRF 26 (not 24) to stay under. CRF 26 on `libx265 -preset ultrafast` produces ~28–29 MB for a 70s 4K Short.

---

## Repo Structure

```
deliverables/
  <project-name>/
    build_<project>_v<N>.py   ← build script (source of truth)
    j5_captions_v<N>.ass       ← generated ASS subtitle file
    <project>_SHORT_4K_v<N>.mp4
presets/
  mj-niche.yaml               ← MJ channel style guide
helpers/                      ← transcribe, grade, render utilities
```

---

## Standard Video Production Pipeline

### 1. Inspect source footage
```bash
$FFMPEG -i "$SRC" 2>&1 | grep -E "Stream|Duration"
```
Note codec (often VP9), resolution, fps, duration.

### 2. Generate VO with ElevenLabs
```python
import requests, os
API_KEY = os.getenv("ELEVENLABS_API_KEY")   # always read from .env
VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"          # George — free tier, warm narrator
MODEL = "eleven_multilingual_v2"            # required model

r = requests.post(
    f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
    headers={"xi-api-key": API_KEY},
    json={"text": SCRIPT, "model_id": MODEL,
          "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
)
```

### 3. Get word-level timestamps via Scribe
```python
r = requests.post(
    "https://api.elevenlabs.io/v1/speech-to-text",
    headers={"xi-api-key": API_KEY},
    files={"file": ("vo.mp3", open(VO, "rb"), "audio/mpeg")},
    data={"model_id": "scribe_v1", "timestamps_granularity": "word"}
)
words = [w for w in r.json()["words"] if w["type"] == "word"]
# fields: w["text"], w["start"], w["end"]
```

### 4. Build ASS captions + FFmpeg encode
See **ASS Caption System** and **FFmpeg Filter Chain** sections below.

---

## FFmpeg Filter Chain (4K Portrait Short)

```python
VIDEO_DUR = 70.0        # seconds
VO_END    = 26.52       # last word end from Scribe

# Crop: source 1188×1078, portrait crop centered on subject
# x=420 centers on MJ in Jackson 5 footage — adjust per source
CROP = "crop=607:1078:420:0"

# Audio volume automation: duck to 15% during VO, swell back to 85%
vol = (f"if(lt(t,{VO_END}),0.15,"
       f"if(lt(t,{VO_END+3}),(t-{VO_END})/3.0*0.70+0.15,0.85))")

# Source watermark kill — fully opaque black box (adjust y/h per source)
WM_BOX = "drawbox=x=0:y=3450:w=1700:h=390:color=black:t=fill"

fcomplex = (
    f"[0:v]{CROP},"
    f"scale=2160:3840:flags=lanczos,"
    f"eq=saturation=1.35:contrast=1.05:brightness=0.02,"
    f"unsharp=5:5:0.8:5:5:0.0,"
    f"{WM_BOX},"
    f"ass={ASS_OUT}[vout];"
    f"[0:a]volume='{vol}':eval=frame[bed];"
    f"[1:a]volume=1.0[vo];"
    f"[bed][vo]amix=inputs=2:duration=first:dropout_transition=2[aout]"
)

cmd = [
    FFMPEG, "-y",
    "-t", str(VIDEO_DUR), "-i", SRC,
    "-i", VO,
    "-filter_complex", fcomplex,
    "-map", "[vout]", "-map", "[aout]",
    "-t", str(VIDEO_DUR),
    "-c:v", "libx265", "-crf", "26", "-preset", "ultrafast",
    "-tag:v", "hvc1", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "192k",
    VIDEO_OUT,
]
```

**Known limitation**: `drawtext` is NOT compiled into the static FFmpeg binary. Use ASS subtitles for ALL text overlay (captions, watermarks, CTAs).

---

## ASS Caption System

### PlayRes (4K portrait)
```
PlayResX: 2160
PlayResY: 3840
ScaledBorderAndShadow: yes
```

### Standard styles
```
Style: Cap,DejaVu Sans,140,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,2,0,1,10,1,2,80,80,900,1
Style: Hook,DejaVu Sans,220,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,2,0,1,12,1,5,80,80,0,1
Style: Outro,DejaVu Sans,180,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,2,0,1,10,1,5,80,80,0,1
Style: Watermark,DejaVu Sans,72,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,1,1,50,50,110,1
```

### Alignment codes
| Code | Position |
|------|----------|
| 1 | Bottom-left |
| 2 | Bottom-center |
| 5 | Center-screen |

### Color format: `&HAABBGGRR` (BGR, not RGB)
- White: `&H00FFFFFF`
- Yellow highlight: `&H0000FFFF` (R=FF, G=FF, B=00)
- Black outline: `&H00000000`

### Inline color override tags
```python
Y = r"{\c&H0000FFFF&}"   # yellow on
W = r"{\c&H00FFFFFF&}"   # white reset
# Usage: f"{Y}MICHAEL JACKSON{W}"
```

### Timestamp helper
```python
def to_ass(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h}:{m:02d}:{int(s):02d}.{round((s-int(s))*100):02d}"
```

### Persistent channel watermark (every frame)
```
Dialogue: 0,0:00:00.00,1:10:00.00,Watermark,,0,0,0,,@mjforeverlove0
```
Watermark style (Alignment=1, MarginV=110) places text at y≈3730 — inside the solid black WM_BOX strip (y=3450–3840). Clean branded zone.

### Caption style guide (MJ / viral Shorts)
- **ALL CAPS**, 2–3 words per card
- Yellow highlights on key phrases: names, years, power words
- Word-group pacing synced to Scribe timestamps
- Add 3–4 sparse captions in the post-narration performance section (don't leave 30+ seconds blank)
- Hook style: center-screen (Alignment=5), first 1–2 seconds
- Outro: center-screen, last 4–6 seconds, `@mjforeverlove0`

---

## Voice IDs (ElevenLabs)

| Voice | ID | Plan | Notes |
|-------|----|------|-------|
| George | `JBFqnCBsd6RMkjVDRZzb` | Free | Warm captivating storyteller — **default** |
| LaSean Pickens | `bQxW1c7YCr6VQgQhw8KX` | Creator ($22/mo) | Community library voice, more authoritative |
| E Sykes (clone) | *(user's cloned voice)* | Creator ($22/mo) | Personal brand voice |

Always use model `eleven_multilingual_v2`. Free tier locks out library and instant-clone voices — fall back to George if 402 error.

---

## Watermark Removal Strategy

Source footage often has a creator watermark in the lower-left corner.

1. Probe exact position with a test frame:
   ```bash
   $FFMPEG -ss 5 -i "$SRC" -frames:v 1 -vf scale=2160:3840 /tmp/probe.jpg
   ```
2. Cover with a fully opaque black box (`color=black`, no alpha):
   ```
   drawbox=x=0:y=<Y>:w=<W>:h=<H>:color=black:t=fill
   ```
3. Burn `@mjforeverlove0` into the same black strip via the Watermark ASS style.

**Do NOT use** `color=black@0.85` — semi-transparent boxes leave traces visible. Use `color=black` only.

---

## Niche Presets

`presets/mj-niche.yaml` — MJ channel style guide:
- Tone: high-energy, celebratory, devoted fan
- Hook templates (age reveals, "nobody talks about", "the real story behind")
- Forbidden phrases: "in today's video", "don't forget to like and subscribe", "let's dive in"
- ElevenLabs voice: George (`JBFqnCBsd6RMkjVDRZzb`)
- Music duck factor: 0.10 during VO

---

## API Keys (read from .env only)

```bash
# /home/user/video-use1/.env
ELEVENLABS_API_KEY=...
GEMINI_API_KEY=...
```

Never hardcode keys. Always `os.getenv("ELEVENLABS_API_KEY")`. Rotate any key that appears in chat.

---

## Git Workflow

- Branch: `claude/youtube-tiktok-content-0ge6ss`
- Deliverables live in `deliverables/<project>/`
- Commit build script + ASS file + MP4 together
- PR #4 tracks this branch on `elsykes74-cpu/video-use1`

---

## QC Checklist Before Delivery

- [ ] Source watermark 100% invisible (no semi-transparency)
- [ ] `@mjforeverlove0` visible on frame 1
- [ ] File size < 30 MB
- [ ] No caption gaps > 10s except intentional (performance breathing room max ~10s)
- [ ] Yellow highlights on: names, years, power words (KING, LEGEND, etc.)
- [ ] Outro CTA at 5+ seconds before end
- [ ] Return code 0 from FFmpeg

---

## Common Errors & Fixes

| Error | Fix |
|-------|-----|
| `Filter not found: drawtext` | Use ASS subtitles — drawtext not compiled in static build |
| ElevenLabs 402 on voice | Free tier: use George (`JBFqnCBsd6RMkjVDRZzb`); upgrade to Creator for library voices |
| File > 30 MB | Raise CRF to 26 or 27; never go below 26 for delivery |
| ASS watermark not showing | Check Alignment=1 and MarginV puts text inside the drawbox strip |
| `amix` audio sync drift | Add `dropout_transition=2` to amix; ensure both inputs have same sample rate |
