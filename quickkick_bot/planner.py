from __future__ import annotations

import math

from quickkick_bot.settings import Settings


def image_count_bounds(narration_seconds: float, settings: Settings) -> tuple[int, int]:
    minimum = max(
        settings.minimum_images,
        math.ceil(narration_seconds / settings.image_seconds_ceiling),
    )
    maximum = max(minimum, math.floor(narration_seconds / settings.image_seconds_floor))
    return minimum, maximum


def target_image_count(current_count: int, narration_seconds: float, settings: Settings) -> int:
    minimum, maximum = image_count_bounds(narration_seconds, settings)
    baseline = current_count or minimum
    return min(maximum, max(minimum, baseline))


def plan_image_beats(scenes: list[dict], narration_seconds: float, settings: Settings) -> list[dict]:
    target = target_image_count(len(scenes), narration_seconds, settings)

    if not scenes:
        return [{"scene": index + 1, "description": f"Beat {index + 1}"} for index in range(target)]

    if len(scenes) >= target:
        return [scene.copy() for scene in scenes[:target]]

    beats = [scene.copy() for scene in scenes]
    while len(beats) < target:
        next_scene = scenes[len(beats) % len(scenes)].copy()
        next_scene["scene"] = len(beats) + 1
        next_scene["description"] = f"{next_scene.get('description', 'Scene')} (alternate beat)"
        beats.append(next_scene)
    return beats
