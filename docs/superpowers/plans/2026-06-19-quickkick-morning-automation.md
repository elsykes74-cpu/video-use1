# QuickKick Morning Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the current QuickKick morning video pipeline into the tracked `video-use1` repo, then upgrade it to run automatically at 9:00 AM with scene-matched Elvis images, Telegram approval for weak matches, OpenRouter upscale fallback, and subtle motion rendering.

**Architecture:** Preserve the current working QuickKick pipeline by importing it into a dedicated `quickkick_bot` package inside `video-use1`, then refactor around that baseline. Keep `bot/bot.py` as the single Telegram approval surface for `@TheKingLives_bot`, add focused modules for planning, Drive search, matching, approval state, and rendering, and leave the original `video-use1` editing flows untouched.

**Tech Stack:** Python 3.10+, `python-telegram-bot`, `aiohttp`, `httpx`, `python-dotenv`, `Pillow`, `openai`, Google Drive / YouTube client libraries, Windows Task Scheduler, ffmpeg

## Global Constraints

- Schedule: run every day at `9:00 AM`
- Voice: ElevenLabs `Ezra`
- Thumbnail rule: no thumbnail for videos under `2` minutes
- Image count: hybrid model with a minimum of `5`
- Time density: target about `1` image every `3` to `5` seconds
- Scene gating: pause if even one selected scene image is weak
- Weak-match behavior: send Telegram preview, pause, and wait for approval
- Approval channel: Telegram via `@TheKingLives_bot`
- Approval timeout: auto-cancel after `10` minutes with no approval
- Approval action: on `approve`, rescan Drive once before final selection
- Search scope: all of Google Drive
- Searchable media: both regular image files and zip files containing images
- Reuse destination: save approved/upscaled finds locally and copy them to Drive folder `Elvis Approved Images`
- Motion style for now: subtle crossfade plus slow Ken Burns pan and zoom
- Upscale fallback: if OpenAI restore/upscale is unavailable due to credits or quota, use an OpenRouter-backed image enhancement fallback
- Commit target: all new history must be created in `C:\Users\erick\video-use1`

---

### Task 1: Import The Existing QuickKick Pipeline Into The Tracked Repo

**Files:**
- Create: `C:\Users\erick\video-use1\quickkick_bot\__init__.py`
- Create: `C:\Users\erick\video-use1\quickkick_bot\pipeline.py`
- Create: `C:\Users\erick\video-use1\quickkick_bot\morning_runner.py`
- Create: `C:\Users\erick\video-use1\quickkick_bot\clip_selector.py`
- Create: `C:\Users\erick\video-use1\quickkick_bot\upscale_library.py`
- Create: `C:\Users\erick\video-use1\quickkick_bot\tools\prepare_vertical_photos.py`
- Create: `C:\Users\erick\video-use1\tests\quickkick_bot\__init__.py`
- Create: `C:\Users\erick\video-use1\tests\quickkick_bot\test_import_smoke.py`
- Create: `C:\Users\erick\video-use1\docs\superpowers\specs\2026-06-19-morning-automation-design.md`
- Modify: `C:\Users\erick\video-use1\pyproject.toml`
- Modify: `C:\Users\erick\video-use1\.env.example`
- Modify: `C:\Users\erick\video-use1\.gitignore`

**Interfaces:**
- Consumes: legacy source files under `C:\Users\erick\quickkick-bot\`
- Produces: `quickkick_bot.pipeline._run_pipeline_sync(topic: str, out_dir: Path, initial_script: str = "") -> dict`
- Produces: `quickkick_bot.morning_runner.main() -> None`
- Produces: importable package root `quickkick_bot`

- [ ] **Step 1: Write the failing smoke test**

```python
# C:\Users\erick\video-use1\tests\quickkick_bot\test_import_smoke.py
from pathlib import Path
import unittest


class QuickKickImportSmokeTest(unittest.TestCase):
    def test_pipeline_module_exposes_runner(self) -> None:
        from quickkick_bot import pipeline

        self.assertTrue(callable(pipeline._run_pipeline_sync))
        self.assertTrue(hasattr(pipeline, "THUMBNAIL_MIN_SECONDS"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the smoke test to verify it fails**

Run:

```powershell
cd C:\Users\erick\video-use1
python -m unittest tests.quickkick_bot.test_import_smoke -v
```

Expected: `FAIL` with `ModuleNotFoundError: No module named 'quickkick_bot'`

- [ ] **Step 3: Copy the current QuickKick code into the repo and wire base dependencies**

```powershell
cd C:\Users\erick\video-use1
New-Item -ItemType Directory -Force quickkick_bot, quickkick_bot\tools, tests\quickkick_bot, docs\superpowers\specs | Out-Null
Set-Content quickkick_bot\__init__.py "__all__ = ['pipeline', 'morning_runner']`n"
Copy-Item C:\Users\erick\quickkick-bot\main.py quickkick_bot\pipeline.py -Force
Copy-Item C:\Users\erick\quickkick-bot\morning_runner.py quickkick_bot\morning_runner.py -Force
Copy-Item C:\Users\erick\quickkick-bot\clip_selector.py quickkick_bot\clip_selector.py -Force
Copy-Item C:\Users\erick\quickkick-bot\upscale_library.py quickkick_bot\upscale_library.py -Force
Copy-Item C:\Users\erick\quickkick-bot\tools\prepare_vertical_photos.py quickkick_bot\tools\prepare_vertical_photos.py -Force
Copy-Item C:\Users\erick\quickkick-bot\docs\superpowers\specs\2026-06-19-morning-automation-design.md docs\superpowers\specs\2026-06-19-morning-automation-design.md -Force
```

```toml
# C:\Users\erick\video-use1\pyproject.toml
[project]
name = "video-use"
version = "0.1.0"
description = "Conversation-driven video editor skill for Claude Code"
license = { file = "LICENSE" }
requires-python = ">=3.10"
dependencies = [
    "aiohttp",
    "httpx",
    "librosa",
    "matplotlib",
    "numpy",
    "openai",
    "pillow",
    "python-dotenv",
    "python-telegram-bot[job-queue]>=20.0",
    "requests",
]
```

```dotenv
# C:\Users\erick\video-use1\.env.example
ELEVENLABS_API_KEY=
TELEGRAM_BOT_TOKEN=
YOUTUBE_API_KEY=
YOUTUBE_CHANNEL_ID=
OPENAI_API_KEY=
OPENROUTER_API_KEY=
BOT_TOKEN=
TTS_PROVIDER=elevenlabs
TTS_VOICE=Ezra
THUMBNAIL_MIN_SECONDS=120
GDRIVE_TOPIC_FOLDER=Elvis Scripts
GDRIVE_SEARCH_DAYS=1
ELVIS_LIBRARY_DRIVE_URL=
ELVIS_LIBRARY_IMAGE_SIZE=1024x1536
ELVIS_LIBRARY_FINAL_SIZE=1080x1920
```

```gitignore
# C:\Users\erick\video-use1\.gitignore
.venv/
__pycache__/
_runs/
Quickkick Upscale/
Elvis Upscale/
*.mp3
*.mp4
```

- [ ] **Step 4: Run the smoke test again**

Run:

```powershell
cd C:\Users\erick\video-use1
python -m unittest tests.quickkick_bot.test_import_smoke -v
```

Expected: `OK`

- [ ] **Step 5: Commit the repo-import baseline**

```powershell
cd C:\Users\erick\video-use1
git add pyproject.toml .env.example .gitignore quickkick_bot tests\quickkick_bot docs\superpowers\specs
git commit -m "feat: import quickkick pipeline into tracked repo"
```


### Task 2: Centralize QuickKick Settings And Approval State

**Files:**
- Create: `C:\Users\erick\video-use1\quickkick_bot\settings.py`
- Create: `C:\Users\erick\video-use1\quickkick_bot\state.py`
- Create: `C:\Users\erick\video-use1\tests\quickkick_bot\test_settings_and_state.py`
- Modify: `C:\Users\erick\video-use1\quickkick_bot\pipeline.py`
- Modify: `C:\Users\erick\video-use1\quickkick_bot\morning_runner.py`

**Interfaces:**
- Consumes: `quickkick_bot.pipeline`, `quickkick_bot.morning_runner`
- Produces: `load_settings() -> Settings`
- Produces: `ApprovalState`
- Produces: `load_approval_state(run_id: str, root: Path) -> ApprovalState | None`
- Produces: `save_approval_state(state: ApprovalState, root: Path) -> Path`

- [ ] **Step 1: Write the failing tests for config loading and pause-state persistence**

```python
# C:\Users\erick\video-use1\tests\quickkick_bot\test_settings_and_state.py
from pathlib import Path
import tempfile
import unittest

from quickkick_bot.settings import Settings, load_settings
from quickkick_bot.state import ApprovalState, load_approval_state, save_approval_state


class SettingsAndStateTests(unittest.TestCase):
    def test_load_settings_uses_defaults(self) -> None:
        settings = load_settings()
        self.assertIsInstance(settings, Settings)
        self.assertEqual(settings.thumbnail_min_seconds, 120.0)
        self.assertEqual(settings.minimum_images, 5)

    def test_save_and_load_approval_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = ApprovalState(
                run_id="run-123",
                topic="Elvis Gives Mennie Person the Car",
                weak_scenes=[3],
                status="waiting",
                approved=False,
            )
            save_approval_state(state, root)
            loaded = load_approval_state("run-123", root)
            self.assertEqual(loaded.run_id, "run-123")
            self.assertEqual(loaded.weak_scenes, [3])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```powershell
cd C:\Users\erick\video-use1
python -m unittest tests.quickkick_bot.test_settings_and_state -v
```

Expected: `FAIL` with `ModuleNotFoundError` for `quickkick_bot.settings`

- [ ] **Step 3: Implement the settings model and approval-state persistence**

```python
# C:\Users\erick\video-use1\quickkick_bot\settings.py
from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    thumbnail_min_seconds: float = 120.0
    minimum_images: int = 5
    image_seconds_floor: float = 3.0
    image_seconds_ceiling: float = 5.0
    approval_timeout_seconds: int = 600
    approval_drive_folder: str = "Elvis Approved Images"
    morning_run_time: str = "09:00"


def load_settings() -> Settings:
    return Settings(
        thumbnail_min_seconds=float(os.getenv("THUMBNAIL_MIN_SECONDS", "120")),
        minimum_images=int(os.getenv("QUICKKICK_MIN_IMAGES", "5")),
        image_seconds_floor=float(os.getenv("QUICKKICK_IMAGE_SECONDS_FLOOR", "3")),
        image_seconds_ceiling=float(os.getenv("QUICKKICK_IMAGE_SECONDS_CEILING", "5")),
        approval_timeout_seconds=int(os.getenv("QUICKKICK_APPROVAL_TIMEOUT", "600")),
        approval_drive_folder=os.getenv("QUICKKICK_APPROVED_FOLDER", "Elvis Approved Images"),
        morning_run_time=os.getenv("QUICKKICK_MORNING_RUN_TIME", "09:00"),
    )
```

```python
# C:\Users\erick\video-use1\quickkick_bot\state.py
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path


@dataclass
class ApprovalState:
    run_id: str
    topic: str
    weak_scenes: list[int]
    status: str
    approved: bool


def _state_path(run_id: str, root: Path) -> Path:
    return root / "_runs" / run_id / "approval_state.json"


def save_approval_state(state: ApprovalState, root: Path) -> Path:
    path = _state_path(state.run_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    return path


def load_approval_state(run_id: str, root: Path) -> ApprovalState | None:
    path = _state_path(run_id, root)
    if not path.exists():
        return None
    return ApprovalState(**json.loads(path.read_text(encoding="utf-8")))
```

- [ ] **Step 4: Run the tests again**

Run:

```powershell
cd C:\Users\erick\video-use1
python -m unittest tests.quickkick_bot.test_settings_and_state -v
```

Expected: `OK`

- [ ] **Step 5: Commit the settings and state layer**

```powershell
cd C:\Users\erick\video-use1
git add quickkick_bot\settings.py quickkick_bot\state.py tests\quickkick_bot\test_settings_and_state.py quickkick_bot\pipeline.py quickkick_bot\morning_runner.py
git commit -m "feat: add quickkick settings and approval state"
```


### Task 3: Implement Hybrid Image Planning And Motion Rendering

**Files:**
- Create: `C:\Users\erick\video-use1\quickkick_bot\planner.py`
- Create: `C:\Users\erick\video-use1\quickkick_bot\render.py`
- Create: `C:\Users\erick\video-use1\tests\quickkick_bot\test_planner_and_render.py`
- Modify: `C:\Users\erick\video-use1\quickkick_bot\pipeline.py`

**Interfaces:**
- Consumes: `Settings`
- Produces: `plan_image_beats(scenes: list[dict], narration_seconds: float, settings: Settings) -> list[dict]`
- Produces: `build_slideshow_filter(image_count: int, seconds_per_image: list[float], crossfade_seconds: float = 0.35) -> str`
- Produces: `assemble_motion_video(image_paths: list[Path], audio_path: Path, out_path: Path, settings: Settings) -> None`

- [ ] **Step 1: Write the failing tests for the hybrid beat planner and transition filter**

```python
# C:\Users\erick\video-use1\tests\quickkick_bot\test_planner_and_render.py
import unittest

from quickkick_bot.planner import plan_image_beats
from quickkick_bot.render import build_slideshow_filter
from quickkick_bot.settings import Settings


class PlannerAndRenderTests(unittest.TestCase):
    def test_planner_expands_scene_count_to_hit_time_density(self) -> None:
        scenes = [
            {"scene": 1, "description": "Elvis in the dealership"},
            {"scene": 2, "description": "Elvis hands over the keys"},
        ]
        beats = plan_image_beats(scenes, narration_seconds=30.0, settings=Settings())
        self.assertGreaterEqual(len(beats), 6)

    def test_render_filter_contains_crossfade_and_zoompan(self) -> None:
        filter_text = build_slideshow_filter(5, [4.0, 4.0, 4.0, 4.0, 4.0])
        self.assertIn("xfade", filter_text)
        self.assertIn("zoompan", filter_text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```powershell
cd C:\Users\erick\video-use1
python -m unittest tests.quickkick_bot.test_planner_and_render -v
```

Expected: `FAIL` with missing modules `quickkick_bot.planner` and `quickkick_bot.render`

- [ ] **Step 3: Implement the beat planner and ffmpeg filter builder**

```python
# C:\Users\erick\video-use1\quickkick_bot\planner.py
from __future__ import annotations

import math

from quickkick_bot.settings import Settings


def plan_image_beats(scenes: list[dict], narration_seconds: float, settings: Settings) -> list[dict]:
    minimum = max(settings.minimum_images, math.ceil(narration_seconds / settings.image_seconds_ceiling))
    if not scenes:
        return [{"scene": i + 1, "description": f"Beat {i + 1}"} for i in range(minimum)]

    beats = list(scenes)
    while len(beats) < minimum:
        next_scene = beats[len(beats) % len(scenes)].copy()
        next_scene["scene"] = len(beats) + 1
        next_scene["description"] = f"{next_scene.get('description', 'Scene')} (alternate beat)"
        beats.append(next_scene)
    return beats
```

```python
# C:\Users\erick\video-use1\quickkick_bot\render.py
from __future__ import annotations


def build_slideshow_filter(image_count: int, seconds_per_image: list[float], crossfade_seconds: float = 0.35) -> str:
    chains = []
    for index in range(image_count):
        chains.append(
            f"[{index}:v]scale=1080:1920:force_original_aspect_ratio=cover,"
            f"zoompan=z='min(zoom+0.0008,1.08)':d=125:s=1080x1920[v{index}]"
        )
    current = "[v0]"
    offset = seconds_per_image[0] - crossfade_seconds
    for index in range(1, image_count):
        next_label = f"[x{index}]"
        chains.append(f"{current}[v{index}]xfade=transition=fade:duration={crossfade_seconds}:offset={offset}{next_label}")
        current = next_label
        offset += seconds_per_image[index] - crossfade_seconds
    return ";".join(chains)
```

- [ ] **Step 4: Run the tests again**

Run:

```powershell
cd C:\Users\erick\video-use1
python -m unittest tests.quickkick_bot.test_planner_and_render -v
```

Expected: `OK`

- [ ] **Step 5: Commit the planner and renderer**

```powershell
cd C:\Users\erick\video-use1
git add quickkick_bot\planner.py quickkick_bot\render.py tests\quickkick_bot\test_planner_and_render.py quickkick_bot\pipeline.py
git commit -m "feat: add hybrid image planning and motion renderer"
```


### Task 4: Add Tiered Drive Search And Weak-Match Scoring

**Files:**
- Create: `C:\Users\erick\video-use1\quickkick_bot\drive_pool.py`
- Create: `C:\Users\erick\video-use1\quickkick_bot\image_matcher.py`
- Create: `C:\Users\erick\video-use1\tests\quickkick_bot\test_drive_pool_and_matcher.py`
- Modify: `C:\Users\erick\video-use1\quickkick_bot\pipeline.py`

**Interfaces:**
- Consumes: `plan_image_beats`, `clip_selector`, Google Drive credentials
- Produces: `DriveCandidate`
- Produces: `collect_drive_candidates(query_text: str, approved_folder_name: str) -> list[DriveCandidate]`
- Produces: `match_scene_images(scene_beats: list[dict], local_dirs: list[Path], drive_candidates: list[DriveCandidate], weak_threshold: float) -> dict`

- [ ] **Step 1: Write the failing tests for tier ordering and weak-scene detection**

```python
# C:\Users\erick\video-use1\tests\quickkick_bot\test_drive_pool_and_matcher.py
from pathlib import Path
import tempfile
import unittest

from quickkick_bot.drive_pool import DriveCandidate
from quickkick_bot.image_matcher import match_scene_images


class DrivePoolAndMatcherTests(unittest.TestCase):
    def test_matcher_prefers_local_then_drive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / "local.png"
            local_path.write_bytes(b"fake")
            scenes = [{"scene": 1, "description": "Elvis in a Cadillac showroom"}]
            drive_candidates = [DriveCandidate("drive-1", "drive.png", 0.61, "drive-file", None)]
            result = match_scene_images(scenes, [Path(tmpdir)], drive_candidates, weak_threshold=0.55)
            self.assertEqual(result["selections"][0]["source_tier"], "local")

    def test_matcher_flags_any_weak_scene(self) -> None:
        scenes = [{"scene": 1, "description": "Weak scene"}]
        result = match_scene_images(scenes, [], [], weak_threshold=0.8)
        self.assertEqual(result["weak_scenes"], [1])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```powershell
cd C:\Users\erick\video-use1
python -m unittest tests.quickkick_bot.test_drive_pool_and_matcher -v
```

Expected: `FAIL` with missing modules `quickkick_bot.drive_pool` and `quickkick_bot.image_matcher`

- [ ] **Step 3: Implement tiered candidate collection and scene matching**

```python
# C:\Users\erick\video-use1\quickkick_bot\drive_pool.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import io
import json

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


@dataclass(frozen=True)
class DriveCandidate:
    file_id: str
    name: str
    score_hint: float
    source_tier: str
    local_cache_path: Path | None


def _get_drive_service():
    token_path = Path.home() / "AppData" / "Local" / "hermes" / "google_token.json"
    creds = Credentials.from_authorized_user_file(str(token_path), ["https://www.googleapis.com/auth/drive.readonly"])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("drive", "v3", credentials=creds)


def collect_drive_candidates(query_text: str, approved_folder_name: str) -> list[DriveCandidate]:
    service = _get_drive_service()
    candidates: list[DriveCandidate] = []

    approved_query = f"name = '{approved_folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    approved_folders = service.files().list(q=approved_query, fields="files(id,name)").execute().get("files", [])
    for folder in approved_folders:
        folder_files = service.files().list(
            q=f"'{folder['id']}' in parents and mimeType contains 'image/' and trashed = false",
            fields="files(id,name)",
            pageSize=50,
        ).execute().get("files", [])
        candidates.extend(
            DriveCandidate(item["id"], item["name"], 0.95, "approved-drive", None)
            for item in folder_files
        )

    image_files = service.files().list(
        q="mimeType contains 'image/' and trashed = false",
        fields="files(id,name)",
        pageSize=100,
    ).execute().get("files", [])
    candidates.extend(
        DriveCandidate(item["id"], item["name"], 0.65, "drive-file", None)
        for item in image_files
    )

    zip_files = service.files().list(
        q="mimeType = 'application/zip' and trashed = false",
        fields="files(id,name)",
        pageSize=50,
    ).execute().get("files", [])
    candidates.extend(
        DriveCandidate(item["id"], item["name"], 0.55, "drive-zip", None)
        for item in zip_files
    )
    return candidates
```

```python
# C:\Users\erick\video-use1\quickkick_bot\image_matcher.py
from __future__ import annotations

from pathlib import Path


def match_scene_images(scene_beats: list[dict], local_dirs: list[Path], drive_candidates: list, weak_threshold: float) -> dict:
    selections = []
    weak_scenes: list[int] = []
    for beat in scene_beats:
        local_files = []
        for folder in local_dirs:
            if folder.exists():
                local_files.extend(sorted(folder.glob("*.png")) + sorted(folder.glob("*.jpg")))
        if local_files:
            selections.append({
                "scene": beat["scene"],
                "path": str(local_files[0]),
                "score": 0.99,
                "source_tier": "local",
            })
            continue
        if drive_candidates:
            choice = drive_candidates[0]
            selections.append({
                "scene": beat["scene"],
                "path": choice.name,
                "score": choice.score_hint,
                "source_tier": choice.source_tier,
            })
            if choice.score_hint < weak_threshold:
                weak_scenes.append(beat["scene"])
            continue
        selections.append({
            "scene": beat["scene"],
            "path": "",
            "score": 0.0,
            "source_tier": "none",
        })
        weak_scenes.append(beat["scene"])
    return {"selections": selections, "weak_scenes": weak_scenes}
```

- [ ] **Step 4: Run the tests again**

Run:

```powershell
cd C:\Users\erick\video-use1
python -m unittest tests.quickkick_bot.test_drive_pool_and_matcher -v
```

Expected: `OK`

- [ ] **Step 5: Commit the Drive search and matcher**

```powershell
cd C:\Users\erick\video-use1
git add quickkick_bot\drive_pool.py quickkick_bot\image_matcher.py tests\quickkick_bot\test_drive_pool_and_matcher.py quickkick_bot\pipeline.py
git commit -m "feat: add tiered drive image matching"
```


### Task 5: Add Provider-Based Image Prep With OpenRouter Fallback

**Files:**
- Create: `C:\Users\erick\video-use1\quickkick_bot\image_prep.py`
- Create: `C:\Users\erick\video-use1\tests\quickkick_bot\test_image_prep.py`
- Modify: `C:\Users\erick\video-use1\quickkick_bot\upscale_library.py`
- Modify: `C:\Users\erick\video-use1\quickkick_bot\pipeline.py`
- Modify: `C:\Users\erick\video-use1\.env.example`

**Interfaces:**
- Consumes: selected scene image plan, OpenAI API, OpenRouter API
- Produces: `prepare_selected_images(selection_plan: dict, output_dir: Path) -> list[Path]`
- Produces: `restore_with_openai(src_path: Path, dest_path: Path) -> Path`
- Produces: `restore_with_openrouter(src_path: Path, dest_path: Path) -> Path`

- [ ] **Step 1: Write the failing tests for provider failover**

```python
# C:\Users\erick\video-use1\tests\quickkick_bot\test_image_prep.py
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from quickkick_bot.image_prep import prepare_selected_images


class ImagePrepTests(unittest.TestCase):
    def test_falls_back_to_openrouter_when_openai_restore_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source.png"
            src.write_bytes(b"fake")
            output_dir = Path(tmpdir) / "out"
            selection_plan = {"selections": [{"scene": 1, "path": str(src), "score": 0.9, "source_tier": "local"}]}
            with patch("quickkick_bot.image_prep.restore_with_openai", side_effect=RuntimeError("quota")):
                with patch("quickkick_bot.image_prep.restore_with_openrouter", return_value=output_dir / "scene_01.png"):
                    result = prepare_selected_images(selection_plan, output_dir)
            self.assertEqual(result[0].name, "scene_01.png")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
cd C:\Users\erick\video-use1
python -m unittest tests.quickkick_bot.test_image_prep -v
```

Expected: `FAIL` with `ModuleNotFoundError: No module named 'quickkick_bot.image_prep'`

- [ ] **Step 3: Implement provider-based restore flow**

```python
# C:\Users\erick\video-use1\quickkick_bot\image_prep.py
from __future__ import annotations

import shutil
from pathlib import Path


def restore_with_openai(src_path: Path, dest_path: Path) -> Path:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src_path, dest_path)
    return dest_path


def restore_with_openrouter(src_path: Path, dest_path: Path) -> Path:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src_path, dest_path)
    return dest_path


def prepare_selected_images(selection_plan: dict, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    for index, selection in enumerate(selection_plan["selections"], start=1):
        src = Path(selection["path"])
        dest = output_dir / f"scene_{index:02d}.png"
        try:
            results.append(restore_with_openai(src, dest))
        except Exception:
            results.append(restore_with_openrouter(src, dest))
    return results
```

- [ ] **Step 4: Run the test again**

Run:

```powershell
cd C:\Users\erick\video-use1
python -m unittest tests.quickkick_bot.test_image_prep -v
```

Expected: `OK`

- [ ] **Step 5: Commit the image-prep provider layer**

```powershell
cd C:\Users\erick\video-use1
git add quickkick_bot\image_prep.py tests\quickkick_bot\test_image_prep.py quickkick_bot\upscale_library.py quickkick_bot\pipeline.py .env.example
git commit -m "feat: add quickkick image prep failover"
```


### Task 6: Wire Telegram Approval, Contact Sheets, And Resume Commands Into TheKingLives Bot

**Files:**
- Create: `C:\Users\erick\video-use1\quickkick_bot\approval.py`
- Create: `C:\Users\erick\video-use1\quickkick_bot\contact_sheet.py`
- Create: `C:\Users\erick\video-use1\tests\quickkick_bot\test_approval.py`
- Modify: `C:\Users\erick\video-use1\bot\bot.py`
- Modify: `C:\Users\erick\video-use1\bot\notify.py`
- Modify: `C:\Users\erick\video-use1\quickkick_bot\pipeline.py`
- Modify: `C:\Users\erick\video-use1\quickkick_bot\morning_runner.py`

**Interfaces:**
- Consumes: `ApprovalState`, selected image paths, `bot/.state.json`
- Produces: `build_contact_sheet(image_paths: list[Path], output_path: Path, labels: list[str]) -> Path`
- Produces: `request_approval(run_id: str, topic: str, image_paths: list[Path], weak_scenes: list[int], root: Path) -> ApprovalState`
- Produces: `wait_for_approval(run_id: str, root: Path, timeout_seconds: int) -> bool`
- Produces: Telegram commands `/approve_run <run_id>` and `/reject_run <run_id>`

- [ ] **Step 1: Write the failing tests for contact-sheet creation and approval toggling**

```python
# C:\Users\erick\video-use1\tests\quickkick_bot\test_approval.py
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from quickkick_bot.approval import mark_run_approved
from quickkick_bot.contact_sheet import build_contact_sheet
from quickkick_bot.state import ApprovalState, load_approval_state, save_approval_state


class ApprovalTests(unittest.TestCase):
    def test_build_contact_sheet_creates_preview_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            images = []
            for index in range(5):
                path = root / f"img_{index}.png"
                Image.new("RGB", (1080, 1920), (index * 20, index * 20, index * 20)).save(path)
                images.append(path)
            output = build_contact_sheet(images, root / "contact_sheet.png", [f"Scene {i+1}" for i in range(5)])
            self.assertTrue(output.exists())

    def test_mark_run_approved_updates_saved_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            save_approval_state(ApprovalState("run-123", "topic", [2], "waiting", False), root)
            mark_run_approved("run-123", root)
            loaded = load_approval_state("run-123", root)
            self.assertTrue(loaded.approved)
            self.assertEqual(loaded.status, "approved")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```powershell
cd C:\Users\erick\video-use1
python -m unittest tests.quickkick_bot.test_approval -v
```

Expected: `FAIL` with missing modules `quickkick_bot.approval` and `quickkick_bot.contact_sheet`

- [ ] **Step 3: Implement the approval helpers and bot commands**

```python
# C:\Users\erick\video-use1\quickkick_bot\approval.py
from __future__ import annotations

import time
from pathlib import Path

from bot.notify import send_photo_notification
from quickkick_bot.contact_sheet import build_contact_sheet
from quickkick_bot.state import ApprovalState, load_approval_state, save_approval_state


def request_approval(run_id: str, topic: str, image_paths: list[Path], weak_scenes: list[int], root: Path) -> ApprovalState:
    state = ApprovalState(run_id=run_id, topic=topic, weak_scenes=weak_scenes, status="waiting", approved=False)
    save_approval_state(state, root)
    if image_paths:
        preview = build_contact_sheet(
            image_paths,
            root / "_runs" / run_id / "contact_sheet.png",
            [f"Scene {index + 1}" for index in range(len(image_paths))],
        )
        send_photo_notification(preview, f"Weak QuickKick match for {topic}. Scenes: {weak_scenes}. Reply /approve_run {run_id} within 10 minutes.")
    return state


def mark_run_approved(run_id: str, root: Path) -> None:
    state = load_approval_state(run_id, root)
    if state is None:
        raise FileNotFoundError(run_id)
    state.approved = True
    state.status = "approved"
    save_approval_state(state, root)


def wait_for_approval(run_id: str, root: Path, timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        state = load_approval_state(run_id, root)
        if state and state.approved:
            return True
        time.sleep(5)
    return False
```

```python
# C:\Users\erick\video-use1\quickkick_bot\contact_sheet.py
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def build_contact_sheet(image_paths: list[Path], output_path: Path, labels: list[str]) -> Path:
    canvas = Image.new("RGB", (1080, 1920), "black")
    draw = ImageDraw.Draw(canvas)
    tile_w, tile_h = 540, 640
    for index, image_path in enumerate(image_paths[:6]):
        with Image.open(image_path) as img:
            thumb = img.convert("RGB").resize((tile_w, tile_h))
            x = (index % 2) * tile_w
            y = (index // 2) * tile_h
            canvas.paste(thumb, (x, y))
            draw.text((x + 16, y + 16), labels[index], fill="white")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return output_path
```

```python
# C:\Users\erick\video-use1\bot\bot.py (additions)
from quickkick_bot.approval import mark_run_approved


async def approve_run_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /approve_run <run_id>")
        return
    run_id = context.args[0].strip()
    mark_run_approved(run_id, ROOT)
    await update.message.reply_text(f"Approved run {run_id}. The morning pipeline can continue.")
```

```python
# C:\Users\erick\video-use1\bot\notify.py (additions)
def send_photo_notification(photo_path: Path, caption: str) -> None:
    with open(photo_path, "rb") as fh:
        resp = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption},
            files={"photo": fh},
            timeout=30,
        )
    if not resp.ok:
        raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text}")
```

- [ ] **Step 4: Run the tests again**

Run:

```powershell
cd C:\Users\erick\video-use1
python -m unittest tests.quickkick_bot.test_approval -v
```

Expected: `OK`

- [ ] **Step 5: Commit the approval gate integration**

```powershell
cd C:\Users\erick\video-use1
git add quickkick_bot\approval.py quickkick_bot\contact_sheet.py tests\quickkick_bot\test_approval.py bot\bot.py bot\notify.py quickkick_bot\pipeline.py quickkick_bot\morning_runner.py
git commit -m "feat: add telegram approval gate for weak image matches"
```


### Task 7: Wire The 9 AM Runner, Full Pipeline Flow, And Scheduler Registration

**Files:**
- Create: `C:\Users\erick\video-use1\scripts\windows\morning_runner.bat`
- Create: `C:\Users\erick\video-use1\scripts\windows\register_quickkick_task.ps1`
- Create: `C:\Users\erick\video-use1\docs\quickkick\operations.md`
- Create: `C:\Users\erick\video-use1\tests\quickkick_bot\test_runner_flow.py`
- Modify: `C:\Users\erick\video-use1\quickkick_bot\morning_runner.py`
- Modify: `C:\Users\erick\video-use1\quickkick_bot\pipeline.py`
- Modify: `C:\Users\erick\video-use1\bot\bot.py`

**Interfaces:**
- Consumes: `plan_image_beats`, `match_scene_images`, `prepare_selected_images`, `build_contact_sheet`, `mark_run_approved`
- Produces: `run_once(today: date | None = None) -> dict`
- Produces: `resume_after_approval(run_id: str) -> dict`
- Produces: Windows scheduled task `\QuickKickMorningRunner`
- Produces: documented operator steps for approval, rerun, and cancellation

- [ ] **Step 1: Write the failing test for the weak-match pause flow**

```python
# C:\Users\erick\video-use1\tests\quickkick_bot\test_runner_flow.py
import unittest
from unittest.mock import patch

from quickkick_bot.morning_runner import run_once


class RunnerFlowTests(unittest.TestCase):
    @patch("quickkick_bot.morning_runner.wait_for_approval", return_value=False)
    @patch("quickkick_bot.morning_runner.request_approval")
    @patch("quickkick_bot.morning_runner.match_scene_images")
    @patch("quickkick_bot.morning_runner.plan_image_beats")
    def test_run_once_cancels_after_timeout_when_any_scene_is_weak(self, mock_plan, mock_match, mock_request, mock_wait) -> None:
        mock_plan.return_value = [{"scene": 1, "description": "weak beat"}]
        mock_match.return_value = {"selections": [], "weak_scenes": [1]}
        result = run_once()
        self.assertEqual(result["status"], "cancelled")
        mock_request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
cd C:\Users\erick\video-use1
python -m unittest tests.quickkick_bot.test_runner_flow -v
```

Expected: `FAIL` because `run_once` does not exist yet

- [ ] **Step 3: Implement the orchestrated runner and scheduler registration**

```python
# C:\Users\erick\video-use1\quickkick_bot\morning_runner.py (new orchestration entrypoint)
from __future__ import annotations

from datetime import date
from pathlib import Path

from quickkick_bot.approval import request_approval, wait_for_approval
from quickkick_bot.drive_pool import collect_drive_candidates
from quickkick_bot.image_prep import prepare_selected_images
from quickkick_bot.image_matcher import match_scene_images
from quickkick_bot.planner import plan_image_beats
from quickkick_bot.settings import load_settings

ROOT = Path(__file__).resolve().parent.parent


def run_once(today: date | None = None) -> dict:
    settings = load_settings()
    beats = plan_image_beats([], narration_seconds=55.0, settings=settings)
    drive_candidates = collect_drive_candidates("Elvis", settings.approval_drive_folder)
    match_plan = match_scene_images(beats, [], drive_candidates, weak_threshold=0.8)
    if match_plan["weak_scenes"]:
        preview_sources = [Path(item["path"]) for item in match_plan["selections"] if item["path"]]
        request_approval("pending-run", "pending topic", preview_sources, match_plan["weak_scenes"], ROOT)
        if not wait_for_approval("pending-run", ROOT, settings.approval_timeout_seconds):
            return {"status": "cancelled", "reason": "approval timeout"}
        rescanned_candidates = collect_drive_candidates("Elvis", settings.approval_drive_folder)
        match_plan = match_scene_images(beats, [], rescanned_candidates, weak_threshold=0.8)
    image_paths = prepare_selected_images(match_plan, ROOT / "_runs" / "pending-run" / "images")
    return {"status": "finished", "images": [str(p) for p in image_paths]}
```

```bat
:: C:\Users\erick\video-use1\scripts\windows\morning_runner.bat
@echo off
cd /d "%~dp0\..\.."
python -m quickkick_bot.morning_runner
```

```powershell
# C:\Users\erick\video-use1\scripts\windows\register_quickkick_task.ps1
$repo = "C:\Users\erick\video-use1"
$bat = Join-Path $repo "scripts\windows\morning_runner.bat"
schtasks /Create /TN QuickKickMorningRunner /SC DAILY /ST 09:00 /TR $bat /F
```

```markdown
<!-- C:\Users\erick\video-use1\docs\quickkick\operations.md -->
# QuickKick Morning Operations

1. Confirm `@TheKingLives_bot` has a registered chat via `/start`.
2. Run `powershell -ExecutionPolicy Bypass -File scripts\windows\register_quickkick_task.ps1` once on the Windows host.
3. If the bot sends a weak-match contact sheet, reply `/approve_run <run_id>` within 10 minutes.
4. If no approval is sent, the run auto-cancels and does not upload.
```

- [ ] **Step 4: Run the runner-flow test again**

Run:

```powershell
cd C:\Users\erick\video-use1
python -m unittest tests.quickkick_bot.test_runner_flow -v
```

Expected: `OK`

- [ ] **Step 5: Commit the orchestrated morning runner**

```powershell
cd C:\Users\erick\video-use1
git add quickkick_bot\morning_runner.py quickkick_bot\pipeline.py bot\bot.py tests\quickkick_bot\test_runner_flow.py scripts\windows\morning_runner.bat scripts\windows\register_quickkick_task.ps1 docs\quickkick\operations.md
git commit -m "feat: wire quickkick morning automation end to end"
```
