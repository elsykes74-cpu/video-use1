from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
import re

from quickkick_bot.drive_pool import DriveCandidate

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _string_similarity(left: str, right: str) -> float:
    normalized_left = _normalize(left)
    normalized_right = _normalize(right)
    if not normalized_left or not normalized_right:
        return 0.0
    left_tokens = set(normalized_left.split())
    right_tokens = set(normalized_right.split())
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens), 1)
    ratio = SequenceMatcher(None, normalized_left, normalized_right).ratio()
    return max(overlap, ratio)


def _gather_local_images(local_dirs: list[Path]) -> list[Path]:
    images: list[Path] = []
    for folder in local_dirs:
        if not folder.exists():
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                images.append(path)
    return images


def _select_local_matches(scene_beats: list[dict], local_dirs: list[Path]) -> list[Path]:
    for folder in local_dirs:
        if not folder.exists():
            continue
        try:
            from quickkick_bot.clip_selector import select_images_by_scenes

            descriptions = [
                beat.get("narration") or beat.get("description") or f"Scene {index + 1}"
                for index, beat in enumerate(scene_beats)
            ]
            selected = select_images_by_scenes(descriptions, folder)
            if selected:
                return selected
        except Exception:
            break

    images = _gather_local_images(local_dirs)
    if not images:
        return []

    used: set[int] = set()
    selections: list[Path] = []
    for beat in scene_beats:
        description = beat.get("narration") or beat.get("description") or ""
        ranked = sorted(
            range(len(images)),
            key=lambda index: _string_similarity(description, images[index].stem),
            reverse=True,
        )
        chosen = next((index for index in ranked if index not in used), None)
        if chosen is None:
            break
        used.add(chosen)
        selections.append(images[chosen])
    return selections


def _score_drive_candidate(description: str, candidate: DriveCandidate) -> float:
    similarity = _string_similarity(description, Path(candidate.name).stem)
    return (candidate.score_hint * 0.7) + (similarity * 0.3)


def match_scene_images(
    scene_beats: list[dict],
    local_dirs: list[Path],
    drive_candidates: list[DriveCandidate],
    weak_threshold: float,
) -> dict:
    local_matches = _select_local_matches(scene_beats, local_dirs)
    selections: list[dict] = []
    weak_scenes: list[int] = []
    used_drive_indexes: set[int] = set()

    for index, beat in enumerate(scene_beats):
        scene_number = int(beat.get("scene", index + 1))
        description = beat.get("narration") or beat.get("description") or f"Scene {scene_number}"

        if index < len(local_matches):
            local_path = local_matches[index]
            selections.append(
                {
                    "scene": scene_number,
                    "path": str(local_path),
                    "score": 1.0,
                    "source_tier": "local",
                    "file_id": "",
                    "name": local_path.name,
                    "local_cache_path": str(local_path),
                }
            )
            continue

        ranked_drive_indexes = sorted(
            range(len(drive_candidates)),
            key=lambda candidate_index: _score_drive_candidate(description, drive_candidates[candidate_index]),
            reverse=True,
        )
        chosen_index = next((candidate_index for candidate_index in ranked_drive_indexes if candidate_index not in used_drive_indexes), None)

        if chosen_index is None:
            selections.append(
                {
                    "scene": scene_number,
                    "path": "",
                    "score": 0.0,
                    "source_tier": "none",
                    "file_id": "",
                    "name": "",
                    "local_cache_path": "",
                }
            )
            weak_scenes.append(scene_number)
            continue

        used_drive_indexes.add(chosen_index)
        candidate = drive_candidates[chosen_index]
        score = _score_drive_candidate(description, candidate)
        materialized_path = str(candidate.local_cache_path or candidate.name)
        selections.append(
            {
                "scene": scene_number,
                "path": materialized_path,
                "score": score,
                "source_tier": candidate.source_tier,
                "file_id": candidate.file_id,
                "name": candidate.name,
                "local_cache_path": str(candidate.local_cache_path) if candidate.local_cache_path else "",
            }
        )
        if score < weak_threshold:
            weak_scenes.append(scene_number)

    return {"selections": selections, "weak_scenes": weak_scenes}
