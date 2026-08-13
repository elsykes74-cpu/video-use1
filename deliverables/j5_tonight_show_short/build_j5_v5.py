#!/usr/bin/env python3
"""J5 viral Short V5: V4 + sparse performance captions (27-66s) for caption coverage."""

import subprocess, sys, os

SCRATCHPAD = "/tmp/claude-0/-home-user-video-use1/1c2881f6-ff29-574a-9a36-c36e872fd636/scratchpad"
FFMPEG    = f"{SCRATCHPAD}/ffmpeg-7.0.2-amd64-static/ffmpeg"
SRC       = "/root/.claude/uploads/1c2881f6-ff29-574a-9a36-c36e872fd636/d88d42d3-Video_by_mjthecollection_Dal6PLvp8Fg.mp4"
VO        = f"{SCRATCHPAD}/j5_vo_george.mp3"
ASS_OUT   = f"{SCRATCHPAD}/j5_captions_v5.ass"
VIDEO_OUT = f"{SCRATCHPAD}/j5_SHORT_4K_v5.mp4"

VO_END    = 26.52
VIDEO_DUR = 70.0

def to_ass(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h}:{m:02d}:{int(s):02d}.{round((s-int(s))*100):02d}"

Y = r"{\c&H0000FFFF&}"
W = r"{\c&H00FFFFFF&}"

CAPTIONS = [
    # ── Narration (0–27s) ────────────────────────────────────────────────────
    ("Hook",      0.00,  1.80,  r"HE WAS 15\NYEARS OLD."),
    ("Cap",       1.74,  2.24,  "STANDING ON"),
    ("Cap",       2.28,  2.98,  "THE TONIGHT SHOW"),
    ("Cap",       3.04,  3.75,  "STAGE."),
    ("Cap",       3.86,  4.28,  "IN FRONT OF"),
    ("Cap",       4.36,  4.70,  "MILLIONS"),
    ("Cap",       4.70,  5.60,  "OF PEOPLE."),
    ("Cap",       5.96,  6.26,  "THIS IS"),
    ("Cap",       6.34,  7.10,  f"{Y}MICHAEL JACKSON{W}"),
    ("Cap",       7.20,  7.38,  "WITH THE"),
    ("Cap",       7.46,  8.32,  "JACKSON FIVE,"),
    ("Cap",       8.94, 10.16,  f"{Y}1974.{W}"),
    ("Cap",      10.86, 11.10,  "LOOK AT"),
    ("Cap",      11.10, 11.74,  "THOSE EYES."),
    ("Cap",      12.32, 12.68,  "WATCH HOW"),
    ("Cap",      12.74, 13.34,  "HE MOVES."),
    ("Cap",      14.00, 14.46,  "THAT IS NOT"),
    ("Cap",      14.50, 15.30,  "A NERVOUS KID."),
    ("Cap",      15.64, 16.00,  "THAT IS A"),
    ("Cap",      16.06, 17.16,  f"{Y}KING{W}\\NBEING CROWNED."),
    ("Cap",      17.80, 18.04,  "HE WAS"),
    ("Cap",      18.10, 19.10,  f"{Y}15 YEARS OLD.{W}"),
    ("Cap",      19.90, 20.40,  "AND ALREADY"),
    ("Cap",      20.46, 21.00,  "THE GREATEST"),
    ("Cap",      21.06, 22.06,  "PERFORMER ALIVE."),
    ("Cap",      22.78, 23.22,  "SOME PEOPLE"),
    ("Cap",      23.24, 23.84,  "ARE JUST BORN"),
    ("Cap",      23.90, 24.22,  "FOR IT."),
    ("Cap",      24.88, 25.50,  "FOLLOW FOR MORE"),
    ("Cap",      25.58, 26.80,  "MOMENTS LIKE THIS."),
    # ── Sparse performance captions (27–66s) ─────────────────────────────────
    ("Cap",      29.00, 30.60,  "WATCH HIM MOVE."),
    ("Cap",      38.00, 39.80,  "THIS IS RARE FOOTAGE."),
    ("Cap",      49.00, 50.80,  f"{Y}NATURAL BORN{W}\\NPERFORMER."),
    ("Cap",      60.00, 61.80,  "YOU'RE WATCHING\\NHISTORY."),
    # ── Branding ─────────────────────────────────────────────────────────────
    ("Watermark", 0.00, 70.00,  "@mjforeverlove0"),
    ("Outro",    66.00, 70.00,  "@mjforeverlove0"),
]

ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: 2160
PlayResY: 3840
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,DejaVu Sans,140,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,2,0,1,10,1,2,80,80,900,1
Style: Hook,DejaVu Sans,220,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,2,0,1,12,1,5,80,80,0,1
Style: Outro,DejaVu Sans,180,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,2,0,1,10,1,5,80,80,0,1
Style: Watermark,DejaVu Sans,72,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,1,1,50,50,110,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

events = [f"Dialogue: 0,{to_ass(t0)},{to_ass(t1)},{s},,0,0,0,,{txt}"
          for s, t0, t1, txt in CAPTIONS]

with open(ASS_OUT, "w") as f:
    f.write(ASS + "\n".join(events) + "\n")
print(f"ASS: {len(events)} events")

vol = (f"if(lt(t,{VO_END}),0.15,"
       f"if(lt(t,{VO_END+3}),(t-{VO_END})/3.0*0.70+0.15,0.85))")

WM_BOX = "drawbox=x=0:y=3450:w=1700:h=390:color=black:t=fill"

fcomplex = (
    f"[0:v]crop=607:1078:420:0,"
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

print("Building V5…")
sys.stdout.flush()
result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
print("STDERR:", result.stderr[-400:])
print("Return:", result.returncode)
if result.returncode == 0:
    mb = os.path.getsize(VIDEO_OUT) / (1024*1024)
    print(f"\nSUCCESS → {VIDEO_OUT}  ({mb:.1f} MB)")
else:
    print("FAILED")
