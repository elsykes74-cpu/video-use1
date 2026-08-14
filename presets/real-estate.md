# Real Estate — Project Template

Copy this file to `<your-listing-folder>/edit/project.md` before your first session.
Run `claude` in that folder and say "make a listing video from these photos".

---

## Project context

**Use case:** Property listing video for MLS embed, Zillow, Instagram, or agent website
**Target format:** 1920×1080 @ 24fps, 60–90 seconds, -14 LUFS normalized
**Source material:** iPhone photos from iCloud / camera roll, drone footage, walkthrough video

---

## Getting photos from iCloud

If your photos are in an iCloud shared album, download them first:

```bash
# Download from a shared iCloud album link
python helpers/download_icloud.py "https://share.icloud.com/photos/YOUR_TOKEN" -o /path/to/listing/photos

# If the link requires sign-in (returns 404), download manually:
# 1. Open the link in Safari on Mac/iPhone
# 2. Select All (⌘A on Mac) → Download
# 3. Copy the folder here and continue with the steps below
```

## Convert photos to video clips

```bash
# Batch convert all photos to animated Ken Burns clips
python helpers/ken_burns.py photos/ -o edit/clips/ --batch --effect ken_burns --duration 6

# For wide exterior shots, pan is more natural:
python helpers/ken_burns.py exterior.jpg -o edit/clips/exterior.mp4 --effect pan_right --duration 7

# For vertical phone photos (portrait), use pan_up or zoom_in:
python helpers/ken_burns.py bedroom.jpg -o edit/clips/bedroom.mp4 --effect zoom_in --size 1920x1080
```

---

## Workflow for a photo-only listing

```
1. Download photos → photos/
2. Convert to clips → edit/clips/  (ken_burns.py --batch)
3. Build edl.json manually or ask Claude:
   "Build an EDL from the clips in edit/clips/ for a 90-second listing video"
4. Render:
   python helpers/render.py edit/edl.json -o edit/final.mp4 --build-subtitles
```

## Workflow for a walkthrough video + drone + photos

```
1. Transcribe the walkthrough video (if agent is narrating):
   python helpers/transcribe.py walkthrough.MOV --edit-dir edit/

2. Convert any still photos to clips (ken_burns.py)

3. Build EDL: exterior drone → front door entry → living/kitchen → bedrooms
              → bathrooms → backyard/outdoor → exterior closing shot

4. Render with grade:
   python helpers/render.py edit/edl.json -o edit/final.mp4
```

---

## EDL structure for a listing video

```json
{
  "grade": "warm_cinematic",
  "sources": {
    "exterior":  "edit/clips/0001_exterior.mp4",
    "entry":     "edit/clips/0002_entry.mp4",
    "living":    "edit/clips/0003_living.mp4",
    "kitchen":   "edit/clips/0004_kitchen.mp4",
    "primary":   "edit/clips/0005_primary_bed.mp4",
    "bathroom":  "edit/clips/0006_bathroom.mp4",
    "backyard":  "edit/clips/0007_backyard.mp4",
    "aerial":    "drone_flyover.mp4"
  },
  "ranges": [
    {"source": "aerial",   "start": 0.0,  "end": 6.0,  "note": "opening flyover"},
    {"source": "exterior", "start": 0.0,  "end": 6.0,  "note": "curb appeal"},
    {"source": "entry",    "start": 0.0,  "end": 5.0,  "note": "door reveal"},
    {"source": "living",   "start": 0.0,  "end": 8.0,  "note": "living room"},
    {"source": "kitchen",  "start": 0.0,  "end": 8.0,  "note": "kitchen island"},
    {"source": "primary",  "start": 0.0,  "end": 7.0,  "note": "primary suite"},
    {"source": "bathroom", "start": 0.0,  "end": 5.0,  "note": "en-suite"},
    {"source": "backyard", "start": 0.0,  "end": 8.0,  "note": "outdoor space"},
    {"source": "aerial",   "start": 6.0,  "end": 12.0, "note": "closing pull-back"}
  ]
}
```

---

## Color grading for real estate

```bash
# Warm cinematic — lifted shadows, warm midtones, gentle highlights
# Works well for most interior photography
python helpers/grade.py input.mp4 -o graded.mp4 --preset warm_cinematic

# Auto-grade per segment (recommended for mixed indoor/outdoor shots)
# Set "grade": "auto" in edl.json
```

---

## Caption style for listing videos

For MLS/website (clean, readable):
```
FontName=Helvetica,FontSize=16,Bold=0,
PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,
BorderStyle=1,Outline=1,Shadow=1,Alignment=2,MarginV=50
```

For Instagram Reels (bold-overlay):
```
FontName=Helvetica,FontSize=18,Bold=1,
PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,
BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=90
```

---

## Social repurpose (9:16 from 16:9 master)

After the master is approved, cut a 30–45s vertical version:

```bash
# Crop center to 9:16 — best for kitchen, bedroom, and bathroom shots
# Exterior shots may need a tighter range selection
# Override grade in edl.json with a crop filter:
# "grade": "crop=1080:1920:(iw-1080)/2:(ih-1920)/2"
```

---

## Cut craft for real estate footage

- **Always start on the hero room** — the kitchen or primary bedroom usually performs best. Exteriors work for drone openers but lose attention as a first cut on social.
- **Natural walkthrough order feels intuitive:** entry → public rooms → private rooms → outdoor.
- **Ken Burns pacing:** 5–7s per photo. Alternate zoom_in / pan_right / zoom_out to avoid monotony. Never use the same effect on two consecutive stills.
- **Drone footage:** open and close with aerials (establishes location, leaves on a wide pull). Cut the drone down to 5–8s maximum; the property, not the drone move, is the subject.
- **Light:** if the photographer shot at different times of day, color-grade per segment with "grade": "auto" — it normalizes each clip independently.
- **No narration?** Let the music carry the visuals. Keep ambient sound if the walkthrough has it (birds, light traffic, HVAC hum can be cut). Pure silence under music feels produced; total silence without music feels broken.

---

## Session log
