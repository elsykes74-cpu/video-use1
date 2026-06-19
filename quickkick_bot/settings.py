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
