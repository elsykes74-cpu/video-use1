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


def _local_match_record(path: Path, description: str, trusted: bool = False) -> dict:
    score = 1.0 if trusted else _string_similarity(description, path.stem)
    return {
        "path": path,
        "score": score,
        "source_tier": "local",
    }


def _discover_clip_matches(scene_beats: list[dict], local_dirs: list[Path]) -> list[Path]:
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
    return []


def _select_local_matches(
    scene_beats: list[dict],
    local_dirs: list[Path],
    preferred_local_matches: list[Path] | None = None,
) -> dict[int, dict]:
    descriptions = [
        beat.get("narration") or beat.get("description") or f"Scene {index + 1}"
        for index, beat in enumerate(scene_beats)
    ]
    local_matches: dict[int, dict] = {}
    used_paths: set[Path] = set()

    preferred_paths = preferred_local_matches if preferred_local_matches is not None else _discover_clip_matches(scene_beats, local_dirs)
    for index, path in enumerate(preferred_paths):
        if index >= len(scene_beats):
            break
        resolved = Path(path)
        local_matches[index] = _local_match_record(resolved, descriptions[index], trusted=True)
        used_paths.add(resolved.resolve())

    images = _gather_local_images(local_dirs)
    used_indexes: set[int] = set()
    for scene_index, description in enumerate(descriptions):
        if scene_index in local_matches:
            continue
        ranked = sorted(
            range(len(images)),
            key=lambda image_index: _string_similarity(description, images[image_index].stem),
            reverse=True,
        )
        chosen = next(
            (
                image_index
                for image_index in ranked
                if image_index not in used_indexes and images[image_index].resolve() not in used_paths
            ),
            None,
        )
        if chosen is None:
            continue
        used_indexes.add(chosen)
        chosen_path = images[chosen]
        used_paths.add(chosen_path.resolve())
        local_matches[scene_index] = _local_match_record(chosen_path, description)
    return local_matches


def _score_drive_candidate(description: str, candidate: DriveCandidate) -> float:
    similarity = _string_similarity(description, Path(candidate.name).stem)
    return (candidate.score_hint * 0.7) + (similarity * 0.3)


def match_scene_images(
    scene_beats: list[dict],
    local_dirs: list[Path],
    drive_candidates: list[DriveCandidate],
    weak_threshold: float,
    preferred_local_matches: list[Path] | None = None,
) -> dict:
    local_matches = _select_local_matches(scene_beats, local_dirs, preferred_local_matches=preferred_local_matches)
    selections: list[dict] = []
    weak_scenes: list[int] = []
    used_drive_indexes: set[int] = set()

    for index, beat in enumerate(scene_beats):
        scene_number = int(beat.get("scene", index + 1))
        description = beat.get("narration") or beat.get("description") or f"Scene {scene_number}"

        ranked_drive_indexes = sorted(
            range(len(drive_candidates)),
            key=lambda candidate_index: _score_drive_candidate(description, drive_candidates[candidate_index]),
            reverse=True,
        )
        chosen_index = next((candidate_index for candidate_index in ranked_drive_indexes if candidate_index not in used_drive_indexes), None)
        drive_candidate = drive_candidates[chosen_index] if chosen_index is not None else None
        drive_score = _score_drive_candidate(description, drive_candidate) if drive_candidate is not None else 0.0
        local_match = local_matches.get(index)

        if local_match is not None and (local_match["score"] >= weak_threshold or drive_candidate is None or local_match["score"] >= drive_score):
            local_path = local_match["path"]
            selections.append(
                {
                    "scene": scene_number,
                    "path": str(local_path),
                    "score": local_match["score"],
                    "source_tier": "local",
                    "file_id": "",
                    "name": local_path.name,
                    "local_cache_path": str(local_path),
                }
            )
            if local_match["score"] < weak_threshold:
                weak_scenes.append(scene_number)
            continue

        if drive_candidate is None:
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
        materialized_path = str(drive_candidate.local_cache_path or drive_candidate.name)
        selections.append(
            {
                "scene": scene_number,
                "path": materialized_path,
                "score": drive_score,
                "source_tier": drive_candidate.source_tier,
                "file_id": drive_candidate.file_id,
                "name": drive_candidate.name,
                "local_cache_path": str(drive_candidate.local_cache_path) if drive_candidate.local_cache_path else "",
            }
        )
        if drive_score < weak_threshold:
            weak_scenes.append(scene_number)

    return {"selections": selections, "weak_scenes": weak_scenes}
