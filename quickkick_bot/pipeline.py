"""
QuickKick — Telegram bot + HTTP API with YouTube Shorts video generation pipeline.

COST OPTIMIZATION (marked [COST-XX]):
  COST-01  OpenAI client for video gen; Ollama for chat (untouched)
  COST-02  Model routing: gpt-4o-mini drafts, gpt-4o polish, gpt-image-1 scenes+thumbnail, tts-1 voiceover
  COST-03  Static system prompts defined at module level
  COST-04  Fresh context per run — no cross-run history
  COST-05  max_tokens cap on every OpenAI call
  COST-06  Per-run token counter
  COST-07  Usage logged to ~/.quickkick/quickkick_usage.log
  COST-08  Daily run cap (DAILY_VIDEO_CAP)
  COST-09  API_COOLDOWN seconds between pipeline calls

PIPELINE: draft→polish→scenes→15×gpt-image-1→tts→(thumbnail for >2 min only)→ffmpeg→YouTube(private)
API:      POST /generate, GET /runs/{id}, GET /health  (Bearer auth, port 8642)
"""

import asyncio
import base64
import csv
import json
import logging
import os
import random
import shutil
import subprocess
import time
import re
import urllib.request
import uuid
import zipfile
from collections import defaultdict, deque
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import httpx
from aiohttp import web
from dotenv import load_dotenv
from openai import OpenAI
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()
try:
    from .planner import plan_image_beats
    from .render import assemble_motion_video, reconcile_image_paths
    from .settings import load_settings
except ImportError:  # pragma: no cover - direct script execution
    from quickkick_bot.planner import plan_image_beats
    from quickkick_bot.render import assemble_motion_video, reconcile_image_paths
    from quickkick_bot.settings import load_settings

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ── Config: Ollama ────────────────────────────────────────────────────────────
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "You are Quickkick, a helpful, concise assistant in a Telegram chat. Keep replies short and to the point.")
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "10"))

# ── Config: OpenAI ────────────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-5.4-mini")
OPENROUTER_CLIENT = (
    OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")
    if OPENROUTER_API_KEY else None
)

# ── Config: Bot + pipeline ────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DAILY_VIDEO_CAP = int(os.getenv("DAILY_VIDEO_CAP", "10"))
API_COOLDOWN = int(os.getenv("API_COOLDOWN", "30"))
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "openai").strip().lower() or "openai"
TTS_VOICE = os.getenv("TTS_VOICE", "onyx")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip() or "eleven_multilingual_v2"
ELEVENLABS_OUTPUT_FORMAT = os.getenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128").strip() or "mp3_44100_128"
YOUTUBE_TOKEN_PATH = os.getenv("YOUTUBE_TOKEN_PATH", str(Path.home() / ".verticals" / "youtube_token_elvis.json"))
SETTINGS = load_settings()
THUMBNAIL_MIN_SECONDS = SETTINGS.thumbnail_min_seconds
_ELEVENLABS_VOICE_CACHE: dict[str, str] = {}

# ── Config: HTTP API server ───────────────────────────────────────────────────
API_SERVER_KEY = os.getenv("API_SERVER_KEY", "")
API_SERVER_HOST = os.getenv("API_SERVER_HOST", "0.0.0.0")
API_SERVER_PORT = int(os.getenv("API_SERVER_PORT", "8642"))

# ── Output paths ──────────────────────────────────────────────────────────────
def _desktop_root() -> Path:
    p = Path.home() / "OneDrive" / "Desktop"
    return p if p.exists() else Path.home() / "Desktop"

VISUALS_ROOT = _desktop_root() / "Quickkick Visuals"
VISUALS_ARCHIVE = _desktop_root() / "Quickkick Visuals Archive.zip"
SCRIPT_INBOX = Path.home() / ".quickkick" / "scripts"
ELVIS_UPSCALE_ROOT = Path(__file__).resolve().parent / "Quickkick Upscale"
ELVIS_BATCH_FULL_ROOT    = ELVIS_UPSCALE_ROOT / "batch_full"         # Drive-synced restored 9:16 library (preferred)
ELVIS_BATCH_AUTOCROP_ROOT = ELVIS_UPSCALE_ROOT / "batch_autocropped" # 125-photo face-cropped library
ELVIS_BATCH_ROOT         = ELVIS_UPSCALE_ROOT / "batch_001"          # original 24-photo subset
ELVIS_BATCH_CROPPED_ROOT = ELVIS_UPSCALE_ROOT / "batch_001_cropped"  # cropped subset

# ── Static system prompts [COST-03] ───────────────────────────────────────────
_SP_DRAFT = ("You are an expert YouTube Shorts scriptwriter. Write punchy, engaging scripts "
             "for the Elvis & MJ tribute channel. Keep narration under 60 seconds when read aloud. "
             "Respond with plain script text only.")
_SP_POLISH = ("You are a professional narrator and copyeditor. Polish the following script for "
              "clarity and vocal flow. Return only the improved script, nothing else.")
_SP_SCENES = ("You are a video director. Given a narration script, break it into exactly 15 visual scenes. "
              "For each scene output a JSON object with keys: scene (int), description (str, max 20 words). "
              "Return a JSON array of 15 objects, no other text.")
_SP_THUMB = ("You are a thumbnail art director for a music tribute YouTube channel. Create a vivid image prompt "
             "for a YouTube thumbnail that captures the video theme. Describe the scene, mood, lighting, and style "
             "in cinematic terms — do NOT name any real people or celebrities. Output only the prompt, under 200 characters.")
_SP_IMG = ("You are a music video art director for a classic rock and soul tribute channel. Generate an image prompt "
           "for the scene description (under 150 chars). Describe the performer as 'a legendary rock and roll performer' "
           "or 'a classic soul entertainer' — never use real names of living or deceased celebrities. "
           "Output only the prompt.")

# ── Default topics ────────────────────────────────────────────────────────────
_DEFAULT_TOPICS = [
    "Elvis Presley's legendary Las Vegas residency",
    "The story behind 'Suspicious Minds'",
    "Michael Jackson's Moonwalk origin story",
    "Elvis and MJ: the phone call that changed music history",
    "Behind the scenes of 'Thriller'",
    "Elvis Presley's influence on rock and roll",
    "MJ's Off the Wall era: the transition to superstardom",
    "Elvis's Gospel recordings and his spiritual side",
    "Graceland: inside Elvis's legendary home",
    "The making of 'Jailhouse Rock'",
    "Michael Jackson's Motown 25 performance",
    "Elvis's film career: from heartbreak to Hollywood",
    "MJ's Bad album: the untold story",
    "Elvis and the birth of rock and roll",
    "The King meets The King of Pop",
]

# ── Daily run tracking [COST-08] ──────────────────────────────────────────────
_run_log: dict = defaultdict(list)

def _daily_run_count() -> int:
    return len(_run_log.get(date.today().isoformat(), []))

def _record_run() -> None:
    _run_log[date.today().isoformat()].append(time.time())

# ── Chat history ──────────────────────────────────────────────────────────────
_chat_history: dict = defaultdict(lambda: deque(maxlen=HISTORY_TURNS * 2))

# ── Background tasks ──────────────────────────────────────────────────────────
_bg_tasks: set = set()

# ── Usage logging [COST-06/07] ────────────────────────────────────────────────
_USAGE_LOG = Path.home() / ".quickkick" / "quickkick_usage.log"
_COST_TABLE = {"gpt-4o-mini": (0.00015, 0.0006), "gpt-4o": (0.0025, 0.01), "gpt-5.4-mini": (0.00015, 0.0006)}

def _log_usage(model: str, in_tok: int, out_tok: int) -> None:
    rates = _COST_TABLE.get(model.split("/")[-1], (0.003, 0.006))
    cost = (in_tok / 1000 * rates[0]) + (out_tok / 1000 * rates[1])
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        _USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_USAGE_LOG, "a") as f:
            f.write(f"[{ts}] | {model} | {in_tok} | {out_tok} | ${cost:.5f}\n")
    except Exception:
        pass

# ── LLM helpers ───────────────────────────────────────────────────────────────
def _call_openrouter(system: str, user: str, max_tokens: int = 2000) -> str:
    if not OPENROUTER_CLIENT:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    resp = OPENROUTER_CLIENT.chat.completions.create(
        model=OPENROUTER_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
    )
    if resp.usage:
        _log_usage(OPENROUTER_MODEL, resp.usage.prompt_tokens, resp.usage.completion_tokens)
    return resp.choices[0].message.content.strip()

def _call_openai(system: str, user: str, model: str = "gpt-4o-mini", max_tokens: int = 2000) -> str:
    if not openai_client:
        raise RuntimeError("OPENAI_API_KEY not set")
    resp = openai_client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
    )
    if resp.usage:
        _log_usage(model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
    return resp.choices[0].message.content.strip()

# ── Manifest helpers ──────────────────────────────────────────────────────────
def _write_manifest(out_dir: Path, data: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

def _update_manifest(out_dir: Path, **kwargs) -> None:
    p = out_dir / "manifest.json"
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    data.update(kwargs)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")

# ── Visuals archive ───────────────────────────────────────────────────────────
def _archive_old_visuals(root: Path, archive_zip: Path, days: int = 30) -> None:
    if not root.exists():
        return
    cutoff = time.time() - (days * 86400)
    root.mkdir(parents=True, exist_ok=True)
    archive_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_zip, mode="a", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(root.iterdir()):
            if not item.is_dir():
                continue
            if item.stat().st_mtime >= cutoff:
                continue
            for file_path in item.rglob("*"):
                if file_path.is_file():
                    zf.write(file_path, arcname=str(file_path.relative_to(root)))
            shutil.rmtree(item, ignore_errors=True)

def _is_production_doc(text: str) -> bool:
    return "FULL SCRIPT:" in text and "SCENE BREAKDOWN:" in text

def _parse_production_doc(text: str) -> dict:
    topic_match = re.search(r"(?im)^Topic:\s*(.+?)\s*$", text)
    topic = topic_match.group(1).strip() if topic_match else ""

    script = text.strip()
    if "FULL SCRIPT:" in text:
        after = text.split("FULL SCRIPT:", 1)[1]
        if "SCENE BREAKDOWN:" in after:
            script = after.split("SCENE BREAKDOWN:", 1)[0].strip()
        else:
            script = after.strip()

    scenes = []
    scene_matches = list(re.finditer(
        r"(?ms)^Scene\s+(\d+)\s*\|\s*([^\n]+)\n(.*?)(?=^Scene\s+\d+\s*\||^=+\s*$|\Z)",
        text,
    ))
    for m in scene_matches:
        scene_num = int(m.group(1))
        time_range = m.group(2).strip()
        block = [line.strip() for line in m.group(3).splitlines() if line.strip()]
        narration = next((line for line in block if not line.lower().startswith("visual direction:")), "")
        visual = next((line.split(":", 1)[1].strip() for line in block if line.lower().startswith("visual direction:") and ":" in line), "")
        scenes.append({
            "scene": scene_num,
            "time": time_range,
            "description": visual or narration,
            "narration": narration,
            "visual_direction": visual,
        })

    return {"topic": topic, "script": script, "scenes": scenes}

def _load_local_elvis_images(limit: int) -> list[Path]:
    for folder in (ELVIS_BATCH_FULL_ROOT, ELVIS_BATCH_AUTOCROP_ROOT, ELVIS_BATCH_CROPPED_ROOT, ELVIS_BATCH_ROOT):
        if folder.exists():
            images = sorted(folder.glob("*.png")) + sorted(folder.glob("*.jpg"))
            if images:
                return images[:limit]

    manifest = ELVIS_BATCH_ROOT / "manifest.csv"
    if manifest.exists():
        rows = []
        with manifest.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if row.get("status") == "ok" and row.get("output"):
                    p = Path(row["output"])
                    if p.exists():
                        rows.append(p)
        if rows:
            return rows[:limit]

    return []


def _clip_select_images(scenes: list, limit: int) -> list[Path]:
    """Pick local Elvis photos matched to scene descriptions using CLIP.
    Falls back to alphabetical selection if open-clip-torch is not installed."""
    # Locate source folder — batch_full (125 upscaled) wins if it exists
    src_folder: Optional[Path] = None
    for folder in (ELVIS_BATCH_FULL_ROOT, ELVIS_BATCH_AUTOCROP_ROOT, ELVIS_BATCH_CROPPED_ROOT, ELVIS_BATCH_ROOT):
        imgs = list(folder.glob("*.png")) + list(folder.glob("*.jpg")) if folder.exists() else []
        if imgs:
            src_folder = folder
            break

    if not src_folder:
        return _load_local_elvis_images(limit)

    try:
        from quickkick_bot.clip_selector import select_images_by_scenes
        # Pull narration text first, fall back to visual direction, then generic label
        descs = [
            (s.get("narration") or s.get("description") or f"Elvis Presley scene {i + 1}")
            for i, s in enumerate(scenes[:limit])
        ]
        logger.info(f"[5a] CLIP selecting {len(descs)} scenes from {src_folder.name}/")
        return select_images_by_scenes(descs, src_folder)
    except ImportError:
        logger.info("[5a] open-clip-torch not installed — run setup_clip.bat. Using alphabetical fallback.")
        return _load_local_elvis_images(limit)
    except Exception as clip_err:
        logger.warning(f"[5a] CLIP selection failed ({clip_err}) — using alphabetical fallback")
        return _load_local_elvis_images(limit)

# ── Script inbox ──────────────────────────────────────────────────────────────
def _infer_topic_from_script(script: str) -> str:
    topic_match = re.search(r"(?im)^Topic:\s*(.+?)\s*$", script)
    if topic_match:
        return topic_match.group(1).strip()[:80]
    lines = [l.strip() for l in script.splitlines() if l.strip()]
    return lines[0][:80] if lines else "Elvis & MJ tribute"

def _load_inbox_script() -> Optional[str]:
    SCRIPT_INBOX.mkdir(parents=True, exist_ok=True)
    for f in sorted(SCRIPT_INBOX.glob("*.txt")):
        text = f.read_text(encoding="utf-8").strip()
        f.unlink()
        if text:
            return text
    return None

# ── YouTube upload ────────────────────────────────────────────────────────────
def _youtube_upload(video_path: Path, title: str, description: str = "") -> str:
    import google.oauth2.credentials
    import googleapiclient.discovery
    import googleapiclient.http

    token_path = Path(YOUTUBE_TOKEN_PATH)
    if not token_path.exists():
        raise FileNotFoundError(f"YouTube OAuth token not found: {token_path}")

    td = json.loads(token_path.read_text())
    creds = google.oauth2.credentials.Credentials(
        token=td.get("token"),
        refresh_token=td.get("refresh_token"),
        token_uri=td.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=td.get("client_id"),
        client_secret=td.get("client_secret"),
        scopes=td.get("scopes", ["https://www.googleapis.com/auth/youtube.upload"]),
    )
    yt = googleapiclient.discovery.build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": ["Elvis Presley", "Michael Jackson", "tribute", "Shorts"],
            "categoryId": "10",
        },
        "status": {"privacyStatus": "private"},
    }
    media = googleapiclient.http.MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True, chunksize=1024*1024)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = req.next_chunk()
    return f"https://youtu.be/{response['id']}"

# ── ffmpeg assembly ───────────────────────────────────────────────────────────
def _assemble_video(image_paths: list, audio_path: Path, out_path: Path) -> None:
    assemble_motion_video([Path(path) for path in image_paths], audio_path, out_path, SETTINGS)


def _ffmpeg_bin() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        ffmpeg = get_ffmpeg_exe()
        logger.info(f"[ffmpeg] Using imageio_ffmpeg bundled binary: {ffmpeg}")
        return ffmpeg
    except Exception as e:
        logger.warning(f"[ffmpeg] imageio_ffmpeg fallback failed: {e}")
    raise RuntimeError("ffmpeg not found on PATH or via imageio_ffmpeg — install ffmpeg or imageio_ffmpeg")


def _probe_audio_duration(audio_path: Path, ffmpeg: Optional[str] = None) -> float:
    ffmpeg = ffmpeg or _ffmpeg_bin()
    probe = subprocess.run([ffmpeg, "-i", str(audio_path), "-f", "null", "-"], capture_output=True, text=True)
    duration = 60.0
    for line in probe.stderr.splitlines():
        if "Duration:" not in line:
            continue
        try:
            parts = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = parts.split(":")
            duration = int(h) * 3600 + int(m) * 60 + float(s)
        except Exception:
            pass
        break
    return duration


def _estimate_narration_seconds(narration: str) -> float:
    words = len(re.findall(r"\w+", narration))
    return max(1.0, words / 2.5)


def _resolve_elevenlabs_voice_id(voice_name: str, api_key: str) -> str:
    voice_name = (voice_name or "").strip()
    if not voice_name:
        raise ValueError("ElevenLabs voice name is required")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not configured")

    cached = _ELEVENLABS_VOICE_CACHE.get(voice_name.lower())
    if cached:
        return cached

    if re.fullmatch(r"[A-Za-z0-9_-]{8,}", voice_name) and " " not in voice_name:
        _ELEVENLABS_VOICE_CACHE[voice_name.lower()] = voice_name
        return voice_name

    response = httpx.get(
        "https://api.elevenlabs.io/v1/voices",
        headers={"xi-api-key": api_key},
        timeout=30.0,
    )
    response.raise_for_status()
    voices = response.json().get("voices", [])

    exact_match = next(
        (voice for voice in voices if voice.get("name", "").strip().lower() == voice_name.lower()),
        None,
    )
    if exact_match and exact_match.get("voice_id"):
        voice_id = exact_match["voice_id"]
        _ELEVENLABS_VOICE_CACHE[voice_name.lower()] = voice_id
        return voice_id

    partial_match = next(
        (voice for voice in voices if voice_name.lower() in voice.get("name", "").strip().lower()),
        None,
    )
    if partial_match and partial_match.get("voice_id"):
        voice_id = partial_match["voice_id"]
        _ELEVENLABS_VOICE_CACHE[voice_name.lower()] = voice_id
        return voice_id

    raise RuntimeError(f"ElevenLabs voice not found: {voice_name}")


def _synthesize_speech(
    text: str,
    out_path: Path,
    provider: Optional[str] = None,
    voice: Optional[str] = None,
    openai_client_override=None,
    elevenlabs_api_key: Optional[str] = None,
) -> None:
    provider_name = (provider or TTS_PROVIDER or "openai").strip().lower()
    voice_name = (voice or TTS_VOICE or "onyx").strip()

    if provider_name == "openai":
        client = openai_client_override or openai_client
        if not client:
            raise RuntimeError("OPENAI_API_KEY required for OpenAI TTS")
        client.audio.speech.create(
            model="tts-1",
            voice=voice_name,
            input=text[:4096],
        ).stream_to_file(str(out_path))
        return

    if provider_name == "elevenlabs":
        api_key = (elevenlabs_api_key or ELEVENLABS_API_KEY).strip()
        voice_id = _resolve_elevenlabs_voice_id(voice_name, api_key)
        response = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
            },
            params={"output_format": ELEVENLABS_OUTPUT_FORMAT},
            json={
                "text": text,
                "model_id": ELEVENLABS_MODEL_ID,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        out_path.write_bytes(response.content)
        return

    raise ValueError(f"Unsupported TTS_PROVIDER: {provider_name}")

# ── Core pipeline ─────────────────────────────────────────────────────────────
def _run_pipeline_sync(topic: str, out_dir: Path, initial_script: str = "") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    parsed_doc = _parse_production_doc(initial_script) if initial_script and _is_production_doc(initial_script) else {"topic": "", "script": "", "scenes": []}
    if parsed_doc.get("topic"):
        topic = parsed_doc["topic"]

    def step(label: str) -> None:
        logger.info(f"[pipeline:{topic[:35]}] {label}")
        _update_manifest(out_dir, step=label, status="started")

    # 1 — Draft
    step("1/8 draft script")
    if parsed_doc.get("script"):
        script = parsed_doc["script"]
    elif initial_script:
        script = initial_script
    elif OPENROUTER_CLIENT:
        script = _call_openrouter(_SP_DRAFT, f"Write a YouTube Shorts script about: {topic}")
    else:
        script = _call_openai(_SP_DRAFT, f"Write a YouTube Shorts script about: {topic}")
    (out_dir / "script_draft.txt").write_text(script, encoding="utf-8")
    time.sleep(API_COOLDOWN)

    # 2 — Polish
    step("2/8 polish narration")
    narration = _call_openai(_SP_POLISH, script, model="gpt-4o", max_tokens=2000)
    (out_dir / "narration.txt").write_text(narration, encoding="utf-8")
    time.sleep(API_COOLDOWN)

    # 3 — Scenes
    step("3/8 scene breakdown")
    if parsed_doc.get("scenes"):
        scenes = parsed_doc["scenes"]
    else:
        raw = _call_openai(_SP_SCENES, narration, max_tokens=2000)
        try:
            s, e = raw.index("["), raw.rindex("]") + 1
            scenes = json.loads(raw[s:e])
        except Exception:
            scenes = [{"scene": i + 1, "description": f"Scene {i + 1}: {topic}"} for i in range(15)]
        scenes = (scenes + [{"scene": i + 16, "description": "Closing scene"} for i in range(15)])[:15]
    scenes = plan_image_beats(scenes, _estimate_narration_seconds(narration), SETTINGS)
    (out_dir / "scenes.json").write_text(json.dumps(scenes, indent=2), encoding="utf-8")
    time.sleep(API_COOLDOWN)

    # 4 — Scene images
    local_images = _clip_select_images(scenes, len(scenes)) if parsed_doc.get("scenes") else []
    if local_images:
        step(f"4/8 local Elvis images x{len(local_images)}")
    else:
        step(f"4/8 scene images gpt-image-1 x{len(scenes)}")
    if not local_images and not openai_client:
        raise RuntimeError("OPENAI_API_KEY required for image generation")
    images_dir = out_dir / "images"
    images_dir.mkdir(exist_ok=True)
    image_paths = []
    _fallback_img: Optional[Path] = None
    if local_images:
        for i, src in enumerate(local_images):
            img_path = images_dir / f"scene_{i + 1:02d}{src.suffix}"
            shutil.copy(src, img_path)
            _fallback_img = img_path
            image_paths.append(img_path)
            logger.info(f"  [5a] {i + 1}/{len(local_images)} copied from {src.name}")
    else:
        for i, scene in enumerate(scenes):
            desc = scene.get("description", f"scene {i + 1}")
            img_path = images_dir / f"scene_{i + 1:02d}.png"
            saved = False
            for attempt in range(3):
                try:
                    img_prompt = _call_openai(_SP_IMG, desc, max_tokens=300)
                    img_resp = openai_client.images.generate(model="gpt-image-1", prompt=img_prompt, size="1024x1536", quality="medium", n=1)
                    img_path.write_bytes(base64.b64decode(img_resp.data[0].b64_json))
                    _fallback_img = img_path
                    saved = True
                    break
                except Exception as img_err:
                    logger.warning(f"  [5a] {i + 1}/{len(scenes)} attempt {attempt + 1} failed: {img_err}")
                    time.sleep(2)
            if not saved:
                if _fallback_img and _fallback_img.exists():
                    import shutil as _shutil
                    _shutil.copy(_fallback_img, img_path)
                    logger.warning(f"  [5a] {i + 1}/{len(scenes)} using fallback image")
                else:
                    logger.warning(f"  [5a] {i + 1}/{len(scenes)} skipped (no fallback available)")
                    continue
            image_paths.append(img_path)
            logger.info(f"  [5a] {i + 1}/{len(scenes)} saved")
            time.sleep(API_COOLDOWN)

    # 5 — TTS
    tts_label = "elevenlabs" if TTS_PROVIDER == "elevenlabs" else "tts-1"
    step(f"5/8 TTS voiceover {tts_label}")
    audio_path = out_dir / "narration.mp3"
    _synthesize_speech(narration, audio_path)
    audio_duration = _probe_audio_duration(audio_path)
    scenes = plan_image_beats(scenes, audio_duration, SETTINGS)
    image_paths = reconcile_image_paths(image_paths, audio_duration, SETTINGS)
    (out_dir / "scenes.json").write_text(json.dumps(scenes, indent=2), encoding="utf-8")
    time.sleep(API_COOLDOWN)

    # 6 — Thumbnail for long-form videos only
    if audio_duration > THUMBNAIL_MIN_SECONDS:
        step("6/8 thumbnail gpt-image-1")
        thumb_prompt = _call_openai(_SP_THUMB, narration, max_tokens=300)
        time.sleep(API_COOLDOWN)

        thumb_path = out_dir / "thumbnail.png"
        try:
            if local_images and image_paths:
                shutil.copy(image_paths[0], thumb_path)
            else:
                req_data = json.dumps({"model": "gpt-image-1", "prompt": thumb_prompt[:400], "size": "1024x1792", "quality": "medium", "n": 1}).encode()
                req = urllib.request.Request(
                    "https://api.openai.com/v1/images/generations", data=req_data,
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}, method="POST"
                )
                with urllib.request.urlopen(req) as r:
                    entry = json.loads(r.read())["data"][0]
                if entry.get("b64_json"):
                    thumb_path.write_bytes(base64.b64decode(entry["b64_json"]))
                else:
                    thumb_path.write_bytes(urllib.request.urlopen(entry["url"]).read())
        except Exception as e:
            logger.warning(f"Thumbnail failed ({e}) — using scene 1")
            if image_paths:
                shutil.copy(image_paths[0], thumb_path)
        time.sleep(API_COOLDOWN)
    else:
        logger.info(
            f"[pipeline:{topic[:35]}] 6/8 thumbnail skipped "
            f"({audio_duration:.1f}s <= {THUMBNAIL_MIN_SECONDS:.0f}s threshold)"
        )
        _update_manifest(
            out_dir,
            thumbnail_skipped=True,
            thumbnail_reason=(
                f"audio duration {audio_duration:.1f}s <= {THUMBNAIL_MIN_SECONDS:.0f}s threshold"
            ),
        )

    # 7 — ffmpeg
    step("7/8 ffmpeg assembly")
    video_path = out_dir / "video.mp4"
    _assemble_video(image_paths, audio_path, video_path)

    # 8 — YouTube
    step("8/8 YouTube upload private")
    title = f"{topic[:80]} | Elvis & MJ Tribute"
    yt_url = ""
    try:
        yt_url = _youtube_upload(video_path, title=title, description=narration[:2000])
        logger.info(f"[pipeline] Upload done: {yt_url}")
    except Exception as e:
        logger.error(f"[pipeline] Upload failed: {e}")

    _record_run()
    final = {"status": "finished", "step": "done", "topic": topic, "title": title,
             "youtube_url": yt_url, "finished_at": datetime.now().isoformat()}
    _update_manifest(out_dir, **final)
    return final

# ── API server ────────────────────────────────────────────────────────────────
def _api_auth(request: web.Request) -> bool:
    return bool(API_SERVER_KEY) and request.headers.get("Authorization", "") == f"Bearer {API_SERVER_KEY}"

async def _api_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "bot": "quickkick", "daily_runs": _daily_run_count(), "daily_cap": DAILY_VIDEO_CAP})

async def _api_run_status(request: web.Request) -> web.Response:
    if not _api_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    manifest = VISUALS_ROOT / request.match_info["run_id"] / "manifest.json"
    if not manifest.exists():
        return web.json_response({"error": "run not found"}, status=404)
    return web.json_response(json.loads(manifest.read_text(encoding="utf-8")))

async def _api_generate_handler(request: web.Request) -> web.Response:
    if not _api_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    if _daily_run_count() >= DAILY_VIDEO_CAP:
        return web.json_response({"error": f"Daily cap reached ({DAILY_VIDEO_CAP}/day)"}, status=429)
    try:
        body = await request.json()
    except Exception:
        body = {}
    topic = str(body.get("topic", "")).strip() or random.choice(_DEFAULT_TOPICS)
    script = str(body.get("script", "")).strip()
    run_id = str(uuid.uuid4())
    out_dir = VISUALS_ROOT / run_id
    _write_manifest(out_dir, {"run_id": run_id, "status": "queued", "step": "queued",
                               "topic": topic, "queued_at": datetime.now().isoformat()})

    async def _bg():
        try:
            await asyncio.to_thread(_run_pipeline_sync, topic, out_dir, script)
        except Exception as e:
            logger.error(f"[api] run {run_id} failed: {e}")
            _update_manifest(out_dir, status="failed", step="error", error=str(e))

    task = asyncio.create_task(_bg())
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return web.json_response({"run_id": run_id, "status": "queued", "topic": topic}, status=202)

def _build_api_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", _api_health)
    app.router.add_post("/generate", _api_generate_handler)
    app.router.add_get("/runs/{run_id}", _api_run_status)
    return app

# ── Ollama chat ───────────────────────────────────────────────────────────────
async def _ollama_chat(chat_id: int, user_text: str) -> str:
    history = _chat_history[chat_id]
    history.append({"role": "user", "content": user_text})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(history)
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{OLLAMA_HOST}/api/chat", json={"model": OLLAMA_MODEL, "messages": messages, "stream": False})
        resp.raise_for_status()
    reply = resp.json()["message"]["content"]
    history.append({"role": "assistant", "content": reply})
    return reply

# ── Telegram handlers ─────────────────────────────────────────────────────────
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👑 *QuickKick* is online!\n\n/generate [topic] — make a YouTube Short\n/status — daily run count\nOr just chat.",
        parse_mode="Markdown",
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"📊 Daily runs: *{_daily_run_count()}/{DAILY_VIDEO_CAP}*\nAPI: `http://localhost:{API_SERVER_PORT}/health`",
        parse_mode="Markdown",
    )

async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _daily_run_count() >= DAILY_VIDEO_CAP:
        await update.message.reply_text(f"⛔ Daily cap reached ({DAILY_VIDEO_CAP}/day). Try again tomorrow.")
        return
    topic = " ".join(context.args).strip() if context.args else ""
    inbox_script = _load_inbox_script()
    if inbox_script and not topic:
        topic = _infer_topic_from_script(inbox_script)
    if not topic:
        topic = random.choice(_DEFAULT_TOPICS)
    run_id = str(uuid.uuid4())
    out_dir = VISUALS_ROOT / run_id
    _write_manifest(out_dir, {"run_id": run_id, "status": "queued", "step": "queued",
                               "topic": topic, "queued_at": datetime.now().isoformat()})
    await update.message.reply_text(f"🎬 Generating: *{topic}*\nRun: `{run_id}`", parse_mode="Markdown")

    async def _bg():
        try:
            result = await asyncio.to_thread(_run_pipeline_sync, topic, out_dir, inbox_script or "")
            yt_url = result.get("youtube_url", "")
            msg = f"✅ Done! *{result.get('title', topic)}*"
            if yt_url:
                msg += f"\n🔗 {yt_url}"
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"[telegram] pipeline error: {e}")
            _update_manifest(out_dir, status="failed", error=str(e))
            await update.message.reply_text(f"❌ Pipeline failed: {e}")

    task = asyncio.create_task(_bg())
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    try:
        reply = await _ollama_chat(update.effective_chat.id, update.message.text.strip())
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"[ollama] {e}")
        await update.message.reply_text("⚠️ Chat error — please try again.")

# ── Entry point ───────────────────────────────────────────────────────────────
async def _async_main() -> None:
    try:
        _archive_old_visuals(VISUALS_ROOT, VISUALS_ARCHIVE, days=30)
    except Exception as e:
        logger.warning(f"Archive (non-fatal): {e}")

    ptb_app = ApplicationBuilder().token(BOT_TOKEN).build()
    ptb_app.add_handler(CommandHandler("start", start_command))
    ptb_app.add_handler(CommandHandler("status", status_command))
    ptb_app.add_handler(CommandHandler("generate", generate_command))
    ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))

    api_runner = web.AppRunner(_build_api_app())
    await api_runner.setup()
    await web.TCPSite(api_runner, API_SERVER_HOST, API_SERVER_PORT).start()
    logger.info(f"API server listening on {API_SERVER_HOST}:{API_SERVER_PORT}")

    async with ptb_app:
        await ptb_app.start()
        await ptb_app.updater.start_polling()
        logger.info("QuickKick bot started.")
        try:
            await asyncio.Event().wait()
        finally:
            await ptb_app.updater.stop()
            await ptb_app.stop()
            await api_runner.cleanup()

def main() -> None:
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        logger.info("QuickKick stopped.")

if __name__ == "__main__":
    main()
