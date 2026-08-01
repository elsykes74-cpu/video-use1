"""NotebookLM-style research using Gemini API.

Researches a topic deeply and outputs a structured JSON file with:
  - summary, key moments, emotional angles, voiceover scripts, TikTok hooks

Usage:
    python helpers/notebooklm_research.py "MJ HIStory tour fan on stage moments"
    python helpers/notebooklm_research.py "Michael Jackson Dangerous tour 1992" --scripts 3
    python helpers/notebooklm_research.py "MJ moonwalk origin" --out custom_output.json

Output: research/<slug>.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent


def _load_env() -> None:
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")[:60]


def _gemini_generate(api_key: str, prompt: str, model: str = "gemini-1.5-pro") -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    r = requests.post(
        url,
        params={"key": api_key},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096}},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def research(api_key: str, topic: str, num_scripts: int = 3) -> dict:
    """Run full NotebookLM-style research on a topic. Returns structured dict."""

    print(f"[research] Topic: {topic}")

    # ── 1. Deep research pass ────────────────────────────────────────────────
    print("[research] Running deep research pass...")
    research_prompt = f"""You are a music historian and cultural analyst specializing in Michael Jackson.
Research this topic thoroughly: "{topic}"

Provide a detailed analysis covering:
1. Historical context and timeline
2. Key moments and events (with approximate dates/locations where known)
3. Eyewitness/fan accounts and documented reactions
4. Why this moment/era resonated emotionally with audiences
5. Cultural significance and legacy
6. Lesser-known facts that would surprise even dedicated fans

Be specific. Use real documented details. Format as flowing prose, not bullets."""

    research_text = _gemini_generate(api_key, research_prompt)

    # ── 2. Emotional angles pass ─────────────────────────────────────────────
    print("[research] Extracting emotional angles...")
    angles_prompt = f"""Based on this research about "{topic}":

{research_text}

Extract 5 distinct emotional angles that could each anchor a different TikTok video.
For each angle provide:
- angle_name: (2-4 words)
- hook: (one sentence that opens a video with this angle — second person "you" perspective)
- core_emotion: (one word: awe / grief / joy / disbelief / nostalgia / reverence)
- best_for: (what type of footage this angle works best with)

Return ONLY valid JSON array, no prose:
[{{"angle_name": "...", "hook": "...", "core_emotion": "...", "best_for": "..."}}]"""

    angles_raw = _gemini_generate(api_key, angles_prompt)
    angles_json = re.search(r"\[.*\]", angles_raw, re.DOTALL)
    angles = json.loads(angles_json.group()) if angles_json else []

    # ── 3. Voiceover scripts ─────────────────────────────────────────────────
    print(f"[research] Writing {num_scripts} voiceover scripts...")
    scripts = []
    for i in range(num_scripts):
        angle_hint = f"Use this emotional angle: {angles[i]['angle_name']} — {angles[i]['hook']}" if i < len(angles) else ""
        script_prompt = f"""Write a TikTok voiceover script about: "{topic}"
{angle_hint}

Rules:
- 25-35 seconds when read aloud at a slow, cinematic pace
- Second person "you" perspective — put the viewer IN the moment
- Short punchy sentences. No filler words.
- Structure: hook question OR statement → what's happening → emotional gut-punch → legacy/timeless closer
- Do NOT mention specific song titles or exact dates
- End with a line about why we still feel this today
- Cinematic and reverent tone — like a documentary narrator

Return ONLY the script text, no labels or intro."""

        script_text = _gemini_generate(api_key, script_prompt)
        scripts.append({
            "script_id": i + 1,
            "angle": angles[i]["angle_name"] if i < len(angles) else f"Script {i+1}",
            "core_emotion": angles[i]["core_emotion"] if i < len(angles) else "",
            "text": script_text.strip(),
            "word_count": len(script_text.split()),
            "est_duration_sec": round(len(script_text.split()) / 2.8),  # ~2.8 words/sec cinematic pace
        })

    # ── 4. TikTok copy ──────────────────────────────────────────────────────
    print("[research] Generating TikTok copy...")
    copy_prompt = f"""Based on research about "{topic}", generate TikTok post copy.

Return ONLY valid JSON, no prose:
{{
  "titles": ["title1", "title2", "title3"],
  "description": "full TikTok description (3-5 short paragraphs, emotional)",
  "hashtags": ["tag1", "tag2"],
  "pinned_comment": "question to pin that drives replies and emoji engagement"
}}"""

    copy_raw = _gemini_generate(api_key, copy_prompt)
    copy_json = re.search(r"\{.*\}", copy_raw, re.DOTALL)
    tiktok_copy = json.loads(copy_json.group()) if copy_json else {}

    # ── 5. Assemble output ───────────────────────────────────────────────────
    return {
        "topic": topic,
        "research_summary": research_text,
        "emotional_angles": angles,
        "voiceover_scripts": scripts,
        "tiktok_copy": tiktok_copy,
        "elevenlabs_voice": {
            "name": "Young Jamal",
            "voice_id": "6OzrBCQf8cjERkYgzSg8",
            "settings": {
                "stability": 0.45,
                "similarity_boost": 0.80,
                "style": 0.35,
                "use_speaker_boost": True
            }
        }
    }


def main() -> None:
    _load_env()

    ap = argparse.ArgumentParser(description="NotebookLM-style MJ research via Gemini")
    ap.add_argument("topic", help="Research topic (e.g. 'MJ HIStory tour fan on stage')")
    ap.add_argument("--scripts", type=int, default=3, help="Number of voiceover scripts to generate (default 3)")
    ap.add_argument("--out", default="", help="Output JSON path (default: research/<slug>.json)")
    ap.add_argument("--api-key", default=os.environ.get("GEMINI_API_KEY", ""))
    args = ap.parse_args()

    if not args.api_key:
        sys.exit("Set GEMINI_API_KEY in .env or pass --api-key")

    out_dir = ROOT / "research"
    out_dir.mkdir(exist_ok=True)
    out_path = Path(args.out) if args.out else out_dir / f"{_slug(args.topic)}.json"

    result = research(args.api_key, args.topic, args.num_scripts if hasattr(args, 'num_scripts') else args.scripts)

    out_path.write_text(json.dumps(result, indent=2))
    print(f"\n✓ Research saved → {out_path}")
    print(f"  {len(result['voiceover_scripts'])} scripts | {len(result['emotional_angles'])} angles | TikTok copy included")
    print(f"\nBest script ({result['voiceover_scripts'][0]['est_duration_sec']}s est.):")
    print("─" * 60)
    print(result['voiceover_scripts'][0]['text'])


if __name__ == "__main__":
    main()
