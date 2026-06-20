#!/usr/bin/env python3
"""
Elvis Photo Library Sync + Restore
==================================
Downloads the configured Google Drive zip file, extracts every image into a
local source pool, and rebuilds Quickkick Upscale/batch_full/ using OpenAI
image edits.

The source zip is cached locally and the output folder is resumable while the
Drive file stays the same. If the Drive file changes, the derived local pool
and restored outputs are rebuilt from that new source.
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import os
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

from openai import OpenAI
from PIL import Image, ImageFilter, ImageOps


QUICKKICK_DIR = Path(__file__).resolve().parent
HERMES_HOME = Path(r"C:\Users\erick\AppData\Local\hermes")
POOL_ROOT = QUICKKICK_DIR / "Quickkick Upscale"
SOURCE_ROOT = POOL_ROOT / "_source_pool"
ZIP_CACHE = SOURCE_ROOT / "library_source.zip"
EXTRACT_ROOT = SOURCE_ROOT / "extracted"
STATE_FILE = SOURCE_ROOT / "source_state.json"
OUT_FOLDER = POOL_ROOT / "batch_full"
MANIFEST_FILE = OUT_FOLDER / "manifest.csv"
LOG_FILE = QUICKKICK_DIR / "_runs" / "upscale_library.log"
GOOGLE_TOKEN_PATH = HERMES_HOME / "google_token.json"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

DEFAULT_DRIVE_URL = (
    "https://drive.google.com/file/d/1WCrpDxbBftqcxxfnI9QP3KwlPcaklZF8/view?usp=drivesdk"
)

RESTORE_PROMPT = """Modernize and restore these vintage photographs to perfection.
- Remove scratches, dust, and blemishes.
- Sharpen facial features and clothing details naturally.
- Balance colors for accurate, vibrant tones while keeping authenticity.
- Correct lighting and contrast for a modern, polished look.
- Enhance textures while avoiding over-smoothing.
- Maintain natural skin tones, realistic shadows, and a clean background.
- Deliver a high-resolution result (8K, print-ready).
- Extend the photo vertically to a full-frame 9:16 composition.
- Preserve the original subject, era authenticity, and identity.
- Single photo only. No collage, no split panels, no added text."""


def _load_env(env_path: Path, override: bool = False) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and (override or key not in os.environ):
            os.environ[key] = value


_load_env(QUICKKICK_DIR / ".env", override=True)
_load_env(HERMES_HOME / ".env")

IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1").strip() or "gpt-image-1"
# FAL is the restore fallback when OpenAI fails (quota/billing). OpenRouter
# was tried here previously but doesn't work: OpenRouter has no images/edit
# endpoint at all (it's a chat-completions proxy), so any model string there
# 404s regardless of name. FAL's clarity-upscaler does real image-to-image
# enhancement, which is the closer match to what this restore step needs.
FAL_RESTORE_MODEL = os.getenv("FAL_RESTORE_MODEL", "fal-ai/clarity-upscaler").strip() or "fal-ai/clarity-upscaler"
FAL_POLL_INTERVAL_SECS = float(os.getenv("FAL_POLL_INTERVAL_SECS", "3"))
FAL_POLL_TIMEOUT_SECS = float(os.getenv("FAL_POLL_TIMEOUT_SECS", "180"))
TARGET_SIZE = os.getenv("ELVIS_LIBRARY_IMAGE_SIZE", "1024x1536").strip() or "1024x1536"
IMAGE_QUALITY = os.getenv("ELVIS_LIBRARY_IMAGE_QUALITY", "high").strip() or "high"
MAX_RETRIES = int(os.getenv("ELVIS_LIBRARY_MAX_RETRIES", "3"))
DELAY_SECS = float(os.getenv("ELVIS_LIBRARY_DELAY_SECS", "1.0"))
FINAL_SIZE = os.getenv("ELVIS_LIBRARY_FINAL_SIZE", "1080x1920").strip() or "1080x1920"


def parse_size(size_value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)x(\d+)", size_value)
    if not match:
        raise ValueError(f"Invalid size value: {size_value!r}")
    return int(match.group(1)), int(match.group(2))


FINAL_WIDTH, FINAL_HEIGHT = parse_size(FINAL_SIZE)
OUTPUT_PROFILE = f"{IMAGE_MODEL}:{TARGET_SIZE}->{FINAL_WIDTH}x{FINAL_HEIGHT}:v2"


def log(message: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def natural_key(value: str) -> list[object]:
    parts = re.split(r"(\d+)", value.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def parse_drive_file_id(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[-\w]{20,}", value):
        return value

    patterns = [
        r"/file/d/([-\w]+)",
        r"[?&]id=([-\w]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    raise ValueError(f"Could not parse Drive file ID from: {value}")


def get_drive_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_data = json.loads(GOOGLE_TOKEN_PATH.read_text(encoding="utf-8"))
    stored_scopes = token_data.get("scopes") or DRIVE_SCOPES
    creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_PATH), stored_scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        refreshed = json.loads(creds.to_json())
        if not refreshed.get("type"):
            refreshed["type"] = "authorized_user"
        GOOGLE_TOKEN_PATH.write_text(json.dumps(refreshed, indent=2), encoding="utf-8")
    return build("drive", "v3", credentials=creds)


def get_source_reference() -> str:
    ref = os.getenv("ELVIS_LIBRARY_DRIVE_URL", "").strip()
    if ref:
        return ref
    ref = os.getenv("ELVIS_LIBRARY_DRIVE_FILE_ID", "").strip()
    if ref:
        return ref
    return DEFAULT_DRIVE_URL


def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not found in environment.")
    return OpenAI(api_key=api_key)


def get_fal_key() -> str:
    api_key = os.getenv("FAL_KEY", "").strip()
    if not api_key:
        raise RuntimeError("FAL_KEY not found in environment.")
    return api_key


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(data: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def clear_directory_contents(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def fetch_drive_metadata(service, file_id: str) -> dict:
    return service.files().get(
        fileId=file_id,
        fields="id,name,mimeType,size,modifiedTime",
        supportsAllDrives=True,
    ).execute()


def download_drive_zip(service, file_id: str, dest: Path) -> None:
    from googleapiclient.http import MediaIoBaseDownload

    dest.parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    with dest.open("wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        last_percent = -1
        while not done:
            status, done = downloader.next_chunk()
            if status is None:
                continue
            percent = int(status.progress() * 100)
            if percent != last_percent:
                log(f"Download {percent}%")
                last_percent = percent


def extract_zip_images(zip_path: Path, extract_root: Path) -> list[Path]:
    clear_directory_contents(extract_root)
    images: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        infos = [
            info
            for info in zf.infolist()
            if not info.is_dir()
            and Path(info.filename).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        ]
        infos.sort(key=lambda item: natural_key(item.filename))

        for info in infos:
            relative = Path(*[part for part in Path(info.filename).parts if part not in ("", ".", "..")])
            dest = extract_root / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, dest.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            images.append(dest)
    return images


def list_extracted_images(extract_root: Path) -> list[Path]:
    images = [
        path
        for path in extract_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    ]
    return sorted(images, key=lambda item: natural_key(str(item.relative_to(extract_root))))


def build_output_name(index: int, src_path: Path) -> str:
    relative = src_path.relative_to(EXTRACT_ROOT).with_suffix("")
    flat = "__".join(relative.parts)
    flat = re.sub(r"[^A-Za-z0-9._-]+", "_", flat)
    flat = re.sub(r"_+", "_", flat).strip("._")
    return f"{index:03d}_{flat}.png"


def decode_and_write_image(resp, dest: Path) -> None:
    item = resp.data[0]
    b64_json = getattr(item, "b64_json", None)
    if b64_json:
        dest.write_bytes(base64.b64decode(b64_json))
        return

    url = getattr(item, "url", None)
    if not url:
        raise RuntimeError("Image response did not include b64_json or url.")

    import urllib.request

    with urllib.request.urlopen(url) as response:
        dest.write_bytes(response.read())


def finalize_vertical_canvas(temp_path: Path, dest: Path) -> None:
    with Image.open(temp_path) as image_file:
        source = image_file.convert("RGBA")

    canvas_size = (FINAL_WIDTH, FINAL_HEIGHT)
    background = ImageOps.fit(
        source,
        canvas_size,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    background = background.filter(ImageFilter.GaussianBlur(radius=max(18, FINAL_WIDTH // 48)))

    foreground = ImageOps.contain(
        source,
        canvas_size,
        method=Image.Resampling.LANCZOS,
    )

    composite = background.copy()
    offset = ((FINAL_WIDTH - foreground.width) // 2, (FINAL_HEIGHT - foreground.height) // 2)
    composite.alpha_composite(foreground, offset)
    composite.convert("RGB").save(dest, format="PNG", optimize=True)


def restore_one(client: OpenAI, src_path: Path, dest: Path, *, model: str = IMAGE_MODEL) -> tuple[str, int, str]:
    last_error = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            image_bytes = src_path.read_bytes()
            image_stream = io.BytesIO(image_bytes)
            image_stream.name = src_path.name
            response = client.images.edit(
                model=model,
                image=image_stream,
                prompt=RESTORE_PROMPT,
                size=TARGET_SIZE,
                quality=IMAGE_QUALITY,
                input_fidelity="high",
            )
            temp_dest = dest.with_suffix(".tmp.png")
            decode_and_write_image(response, temp_dest)
            finalize_vertical_canvas(temp_dest, dest)
            temp_dest.unlink(missing_ok=True)
            return "ok", attempt, ""
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            log(f"ERROR attempt {attempt}/{MAX_RETRIES} for {src_path.name}: {last_error}")
            dest.unlink(missing_ok=True)
            dest.with_suffix(".tmp.png").unlink(missing_ok=True)
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)
    return "error", MAX_RETRIES, last_error


def _restore_or_raise(client: OpenAI, src_path: Path, dest: Path, *, model: str) -> Path:
    status, _attempts, error = restore_one(client, src_path, dest, model=model)
    if status != "ok":
        raise RuntimeError(error or f"Restore failed for {src_path.name}")
    return dest


def restore_with_openai(src_path: Path, dest_path: Path) -> Path:
    return _restore_or_raise(get_openai_client(), src_path, dest_path, model=IMAGE_MODEL)


def _image_to_data_uri(src_path: Path) -> str:
    import mimetypes

    mime, _ = mimetypes.guess_type(str(src_path))
    mime = mime or "image/png"
    encoded = base64.b64encode(src_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def restore_with_fal(src_path: Path, dest_path: Path) -> Path:
    """Restore fallback via FAL's clarity-upscaler (queue API), used when
    OpenAI's images.edit hits quota/billing limits. See FAL_RESTORE_MODEL
    comment above for why OpenRouter isn't an option here."""
    import httpx

    api_key = get_fal_key()
    headers = {"Authorization": f"Key {api_key}"}
    last_error = ""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            payload = {
                "image_url": _image_to_data_uri(src_path),
                "prompt": (
                    "Restore this vintage photograph: remove scratches, dust, and "
                    "blemishes; balance colors for accurate, vibrant tones; correct "
                    "lighting and contrast; sharpen facial features and clothing "
                    "details naturally; preserve the original subject, era "
                    "authenticity, and identity."
                ),
                "upscale_factor": 2,
                "creativity": 0.3,
                "resemblance": 0.75,
            }
            submit_resp = httpx.post(
                f"https://queue.fal.run/{FAL_RESTORE_MODEL}",
                headers=headers,
                json=payload,
                timeout=30.0,
            )
            submit_resp.raise_for_status()
            submission = submit_resp.json()
            status_url = submission["status_url"]
            response_url = submission["response_url"]

            deadline = time.time() + FAL_POLL_TIMEOUT_SECS
            status = None
            while time.time() < deadline:
                status_resp = httpx.get(status_url, headers=headers, timeout=30.0)
                status_resp.raise_for_status()
                status = status_resp.json().get("status")
                if status == "COMPLETED":
                    break
                if status in ("IN_QUEUE", "IN_PROGRESS"):
                    time.sleep(FAL_POLL_INTERVAL_SECS)
                    continue
                raise RuntimeError(f"FAL restore returned unexpected status: {status}")
            if status != "COMPLETED":
                raise RuntimeError(f"FAL restore timed out after {FAL_POLL_TIMEOUT_SECS}s")

            result_resp = httpx.get(response_url, headers=headers, timeout=30.0)
            result_resp.raise_for_status()
            result = result_resp.json()
            image_url = (result.get("image") or {}).get("url")
            if not image_url:
                raise RuntimeError(f"FAL restore response missing image URL: {result}")

            image_resp = httpx.get(image_url, timeout=60.0)
            image_resp.raise_for_status()

            temp_dest = dest_path.with_suffix(".tmp.png")
            temp_dest.write_bytes(image_resp.content)
            finalize_vertical_canvas(temp_dest, dest_path)
            temp_dest.unlink(missing_ok=True)
            return dest_path
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            log(f"ERROR (FAL) attempt {attempt}/{MAX_RETRIES} for {src_path.name}: {last_error}")
            dest_path.unlink(missing_ok=True)
            dest_path.with_suffix(".tmp.png").unlink(missing_ok=True)
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)

    raise RuntimeError(last_error or f"FAL restore failed for {src_path.name}")


def sync_source(force_download: bool = False) -> tuple[dict, list[Path], bool]:
    source_ref = get_source_reference()
    file_id = parse_drive_file_id(source_ref)
    service = get_drive_service()
    metadata = fetch_drive_metadata(service, file_id)

    prior_state = load_state()
    cache_stale = (
        force_download
        or prior_state.get("file_id") != metadata["id"]
        or prior_state.get("modified_time") != metadata["modifiedTime"]
        or prior_state.get("file_name") != metadata["name"]
        or not ZIP_CACHE.exists()
        or not EXTRACT_ROOT.exists()
    )
    outputs_need_rebuild = (
        prior_state.get("output_ready_modified_time") != metadata["modifiedTime"]
        or prior_state.get("output_profile") != OUTPUT_PROFILE
        or not OUT_FOLDER.exists()
    )

    log(f"Drive source: {metadata['name']} ({metadata['id']})")
    log(f"Modified: {metadata['modifiedTime']} | Mime: {metadata['mimeType']}")

    if cache_stale:
        log("Source changed or cache missing - downloading fresh zip.")
        download_drive_zip(service, file_id, ZIP_CACHE)
        extracted = extract_zip_images(ZIP_CACHE, EXTRACT_ROOT)
        save_state(
            {
                "file_id": metadata["id"],
                "file_name": metadata["name"],
                "modified_time": metadata["modifiedTime"],
                "source_ref": source_ref,
                "extracted_image_count": len(extracted),
                "output_profile": prior_state.get("output_profile", ""),
                "output_ready_modified_time": (
                    metadata["modifiedTime"]
                    if prior_state.get("output_ready_modified_time") == metadata["modifiedTime"]
                    and prior_state.get("output_profile") == OUTPUT_PROFILE
                    else ""
                ),
                "synced_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    else:
        log("Source unchanged - reusing cached zip and extracted images.")

    extracted_images = list_extracted_images(EXTRACT_ROOT)
    return metadata, extracted_images, outputs_need_rebuild


def write_manifest(rows: list[dict]) -> None:
    OUT_FOLDER.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "index",
        "input_relative",
        "input_file",
        "output_file",
        "status",
        "attempts",
        "bytes",
        "error",
    ]
    with MANIFEST_FILE.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="Download/extract the Drive zip and report image count without calling OpenAI.",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=0,
        help="Optional limit for testing. Default processes every image in the pool.",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Ignore cached source state and re-download the Drive zip.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    metadata, extracted_images, outputs_need_rebuild = sync_source(force_download=args.force_download)

    if not extracted_images:
        log(f"No image files found in {metadata['name']}")
        return 1

    total_images = len(extracted_images)
    if args.max_images > 0:
        extracted_images = extracted_images[: args.max_images]

    log(f"Source image count: {total_images}")
    log(f"Selected for this run: {len(extracted_images)}")
    log(f"Extracted source root: {EXTRACT_ROOT}")
    log(f"Output folder: {OUT_FOLDER}")
    log(f"Final output size: {FINAL_WIDTH}x{FINAL_HEIGHT}")

    if args.inventory_only:
        return 0

    if outputs_need_rebuild:
        log("Source pool changed - clearing batch_full so only this Drive pool is used.")
        clear_directory_contents(OUT_FOLDER)

    OUT_FOLDER.mkdir(parents=True, exist_ok=True)
    client = get_openai_client()
    rows: list[dict] = []
    ok_count = 0
    skip_count = 0
    error_count = 0

    for index, src_path in enumerate(extracted_images, start=1):
        output_name = build_output_name(index, src_path)
        dest = OUT_FOLDER / output_name
        relative = src_path.relative_to(EXTRACT_ROOT).as_posix()

        if dest.exists():
            log(f"[{index}/{len(extracted_images)}] SKIP {relative} -> {output_name}")
            rows.append(
                {
                    "index": index,
                    "input_relative": relative,
                    "input_file": str(src_path),
                    "output_file": str(dest),
                    "status": "skip",
                    "attempts": 0,
                    "bytes": dest.stat().st_size,
                    "error": "",
                }
            )
            skip_count += 1
            continue

        log(f"[{index}/{len(extracted_images)}] RESTORE {relative}")
        status, attempts, error = restore_one(client, src_path, dest)
        row = {
            "index": index,
            "input_relative": relative,
            "input_file": str(src_path),
            "output_file": str(dest),
            "status": status,
            "attempts": attempts,
            "bytes": dest.stat().st_size if dest.exists() else 0,
            "error": error,
        }
        rows.append(row)

        if status == "ok":
            ok_count += 1
            log(f"[{index}/{len(extracted_images)}] SAVED {output_name}")
        else:
            error_count += 1
            log(f"[{index}/{len(extracted_images)}] FAILED {relative}")

        if index < len(extracted_images):
            time.sleep(DELAY_SECS)

    write_manifest(rows)
    if error_count == 0:
        state = load_state()
        state["output_ready_modified_time"] = metadata["modifiedTime"]
        state["output_profile"] = OUTPUT_PROFILE
        state["output_ready_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_state(state)
    log(f"Done. ok={ok_count} skip={skip_count} error={error_count}")
    log(f"Manifest: {MANIFEST_FILE}")
    return 1 if error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
