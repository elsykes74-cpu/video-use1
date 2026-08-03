#!/usr/bin/env python3
"""Build J5 viral Short: crop, mix audio, ASS captions, H.265 1080x1920"""

import json, subprocess, sys, os

SCRATCHPAD = "/tmp/claude-0/-home-user-video-use1/1c2881f6-ff29-574a-9a36-c36e872fd636/scratchpad"
FFMPEG = f"{SCRATCHPAD}/ffmpeg-7.0.2-amd64-static/ffmpeg"
SRC = "/root/.claude/uploads/1c2881f6-ff29-574a-9a36-c36e872fd636/d88d42d3-Video_by_mjthecollection_Dal6PLvp8Fg.mp4"
VO = f"{SCRATCHPAD}/j5_vo.mp3"
SCRIBE = f"{SCRATCHPAD}/j5_scribe.json"
ASS_OUT = f"{SCRATCHPAD}/j5_captions.ass"
VIDEO_OUT = f"{SCRATCHPAD}/j5_SHORT_1080p.mp4"

# ── ASS timestamp helper ─────────────────────────────────────────────────────
def to_ass(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    cs = round((s - int(s)) * 100)
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"

# ── Caption groups (manually curated phrase breaks) ──────────────────────────
# (start_t, end_t, text, style)
# Hook covers 0.08-1.18 ("He was 15 years old") via Hook style
# Captions start from "Standing..." at 1.60s

HOOK_END = 2.00
OUTRO_START = 62.0
OUTRO_END   = 66.0
VIDEO_DUR   = 66.0  # seconds of source footage to use

CAPTION_LINES = [
    # style, t_start, t_end, text
    ("Hook",    0.00,   2.00,  "HE WAS 15 YEARS OLD."),
    ("Default", 1.60,   3.30,  "Standing on The Tonight Show stage."),
    ("Default", 3.60,   5.40,  "In front of millions of people."),
    ("Default", 5.72,   8.20,  "This is Michael Jackson\nwith the Jackson Five."),
    ("Default", 8.62,  10.10,  "Nineteen seventy-four."),
    ("Default",10.36,  11.40,  "Look at his eyes."),
    ("Default",11.60,  12.80,  "Watch how he moves."),
    ("Default",12.98,  14.50,  "That is not a nervous kid."),
    ("Default",14.68,  16.50,  "That is a king being crowned."),
    ("Default",16.70,  18.50,  "He was fifteen years old."),
    ("Default",18.72,  20.62,  "And Michael Jackson was already"),
    ("Default",20.66,  22.50,  "the greatest performer alive."),
    ("Default",22.98,  24.60,  "Some people are just born for it."),
    ("Default",25.12,  27.10,  "Follow for more moments like this."),
    ("Outro",  OUTRO_START, OUTRO_END, "@mjforeverlove0"),
]

# ── Build ASS file ───────────────────────────────────────────────────────────
# PlayRes = 1080x1920
# Default: white, 58px, bottom-center, black outline
# Hook: white bold, 88px, middle-center
# Outro: white, 72px, middle-center

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,58,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,60,60,80,1
Style: Hook,DejaVu Sans,92,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,60,60,0,1
Style: Outro,DejaVu Sans,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

lines = [ASS_HEADER]
for style, t_start, t_end, text in CAPTION_LINES:
    safe = text.replace("\n", "\\N")
    lines.append(f"Dialogue: 0,{to_ass(t_start)},{to_ass(t_end)},{style},,0,0,0,,{safe}")

with open(ASS_OUT, "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"ASS written: {len(lines)-1} events")

# ── FFmpeg command ────────────────────────────────────────────────────────────
# Input 0: source footage (first VIDEO_DUR seconds)
# Input 1: VO mp3
# Video: crop 607x1078 at x=420, scale to 1080x1920, burn ASS captions
# Audio: original at 20% + VO at 100%, amix, apad to VIDEO_DUR
#
# Strategy: use the source from t=0. The footage is 90.92s; we use first 66s.

cmd = [
    FFMPEG, "-y",
    "-t", str(VIDEO_DUR), "-i", SRC,
    "-i", VO,
    "-filter_complex",
    (
        # Video: crop → scale → captions
        f"[0:v]crop=607:1078:420:0,scale=1080:1920:flags=lanczos,ass={ASS_OUT}[vout];"
        # Audio: original bed at 20% + VO at full
        "[0:a]volume=0.20[bed];"
        "[1:a]volume=1.0[vo];"
        "[bed][vo]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    ),
    "-map", "[vout]",
    "-map", "[aout]",
    "-t", str(VIDEO_DUR),
    "-c:v", "libx265",
    "-crf", "24",
    "-preset", "ultrafast",
    "-tag:v", "hvc1",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "192k",
    VIDEO_OUT
]

print("Running FFmpeg...")
print(" ".join(cmd[:8]) + " ...")
sys.stdout.flush()

result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
print("STDOUT:", result.stdout[-500:] if result.stdout else "(empty)")
print("STDERR (last 1000):", result.stderr[-1000:] if result.stderr else "(empty)")
print("Return code:", result.returncode)

if result.returncode == 0:
    size = os.path.getsize(VIDEO_OUT) / (1024*1024)
    print(f"\nSUCCESS: {VIDEO_OUT} ({size:.1f} MB)")
else:
    print("\nFAILED — check stderr above")
