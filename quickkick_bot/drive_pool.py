from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import io
import json
from pathlib import Path
import re
import zipfile

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


@dataclass(frozen=True)
class DriveCandidate:
    file_id: str
    name: str
    score_hint: float
    source_tier: str
    local_cache_path: Path | None


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _name_similarity(query_text: str, name: str) -> float:
    normalized_query = _normalize(query_text)
    normalized_name = _normalize(name)
    if not normalized_query or not normalized_name:
        return 0.0
    query_tokens = set(normalized_query.split())
    name_tokens = set(normalized_name.split())
    overlap = len(query_tokens & name_tokens) / max(len(query_tokens), 1)
    ratio = SequenceMatcher(None, normalized_query, normalized_name).ratio()
    return max(overlap, ratio)


def _cache_root() -> Path:
    root = Path.home() / ".quickkick" / "drive_match_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned or "file"


def _regular_image_cache_path(file_id: str, name: str) -> Path:
    return _cache_root() / "drive_files" / f"{file_id}_{_safe_name(name)}"


def _zip_cache_dir(file_id: str) -> Path:
    return _cache_root() / "zip_files" / file_id


def _get_drive_service():
    token_path = Path.home() / "AppData" / "Local" / "hermes" / "google_token.json"
    token_data = json.loads(token_path.read_text(encoding="utf-8"))
    stored_scopes = token_data.get("scopes") or DRIVE_SCOPES
    creds = Credentials.from_authorized_user_file(str(token_path), stored_scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        refreshed = json.loads(creds.to_json())
        if not refreshed.get("type"):
            refreshed["type"] = "authorized_user"
        token_path.write_text(json.dumps(refreshed, indent=2), encoding="utf-8")
    return build("drive", "v3", credentials=creds)


def _list_drive_files(service, query: str) -> list[dict]:
    files: list[dict] = []
    page_token: str | None = None
    while True:
        response = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType)",
            pageSize=200,
            pageToken=page_token,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute()
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return files


def _download_drive_file(service, file_id: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    with dest.open("wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return dest


def ensure_candidate_cached(candidate: DriveCandidate, service=None) -> Path:
    if candidate.local_cache_path is None:
        raise ValueError(f"Drive candidate has no cache path: {candidate.name}")
    if candidate.local_cache_path.exists():
        return candidate.local_cache_path
    if candidate.source_tier == "drive-zip-image":
        raise FileNotFoundError(f"Cached zip image is missing: {candidate.local_cache_path}")
    service = service or _get_drive_service()
    return _download_drive_file(service, candidate.file_id, candidate.local_cache_path)


def enumerate_zip_images(service, file_id: str, file_name: str) -> list[dict]:
    cache_dir = _zip_cache_dir(file_id)
    zip_path = cache_dir / _safe_name(file_name)
    extract_root = cache_dir / "extracted"
    _download_drive_file(service, file_id, zip_path)
    extract_root.mkdir(parents=True, exist_ok=True)

    images: list[dict] = []
    with zipfile.ZipFile(zip_path) as archive:
        for info in sorted(archive.infolist(), key=lambda item: item.filename.lower()):
            if info.is_dir():
                continue
            entry_path = Path(info.filename)
            if entry_path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            relative = Path(*[part for part in entry_path.parts if part not in ("", ".", "..")])
            dest = extract_root / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, dest.open("wb") as dst:
                dst.write(src.read())
            images.append({"entry_name": relative.as_posix(), "cache_path": dest})
    return images


def collect_drive_candidates(query_text: str, approved_folder_name: str) -> list[DriveCandidate]:
    service = _get_drive_service()
    candidates: list[DriveCandidate] = []
    seen_regular_ids: set[str] = set()
    seen_zip_entries: set[tuple[str, str]] = set()

    approved_query = (
        f"name = '{approved_folder_name}' and "
        "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    for folder in _list_drive_files(service, approved_query):
        folder_files = _list_drive_files(
            service,
            f"'{folder['id']}' in parents and mimeType contains 'image/' and trashed = false",
        )
        for item in folder_files:
            seen_regular_ids.add(item["id"])
            similarity = _name_similarity(query_text, item["name"])
            candidates.append(
                DriveCandidate(
                    file_id=item["id"],
                    name=item["name"],
                    score_hint=min(0.99, 0.9 + (0.09 * similarity)),
                    source_tier="approved-drive",
                    local_cache_path=_regular_image_cache_path(item["id"], item["name"]),
                )
            )

    for item in _list_drive_files(service, "mimeType contains 'image/' and trashed = false"):
        if item["id"] in seen_regular_ids:
            continue
        seen_regular_ids.add(item["id"])
        similarity = _name_similarity(query_text, item["name"])
        candidates.append(
            DriveCandidate(
                file_id=item["id"],
                name=item["name"],
                score_hint=min(0.95, 0.6 + (0.25 * similarity)),
                source_tier="drive-file",
                local_cache_path=_regular_image_cache_path(item["id"], item["name"]),
            )
        )

    for item in _list_drive_files(service, "mimeType = 'application/zip' and trashed = false"):
        for zip_image in enumerate_zip_images(service, item["id"], item["name"]):
            zip_key = (item["id"], zip_image["entry_name"])
            if zip_key in seen_zip_entries:
                continue
            seen_zip_entries.add(zip_key)
            similarity = _name_similarity(query_text, zip_image["entry_name"])
            candidates.append(
                DriveCandidate(
                    file_id=item["id"],
                    name=zip_image["entry_name"],
                    score_hint=min(0.9, 0.55 + (0.25 * similarity)),
                    source_tier="drive-zip-image",
                    local_cache_path=Path(zip_image["cache_path"]),
                )
            )

    tier_order = {"approved-drive": 0, "drive-file": 1, "drive-zip-image": 2}
    return sorted(
        candidates,
        key=lambda candidate: (
            tier_order.get(candidate.source_tier, 99),
            -candidate.score_hint,
            candidate.name.lower(),
        ),
    )
