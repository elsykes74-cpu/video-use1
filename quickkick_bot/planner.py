from __future__ import annotations

import math

from quickkick_bot.settings import Settings


def plan_image_beats(scenes: list[dict], narration_seconds: float, settings: Settings) -> list[dict]:
    minimum = max(
        settings.minimum_images,
        math.ceil(narration_seconds / settings.image_seconds_ceiling),
    )
    maximum = max(minimum, math.floor(narration_seconds / settings.image_seconds_floor))
    target = min(maximum, max(minimum, len(scenes) or minimum))

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
