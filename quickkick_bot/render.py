from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from quickkick_bot.planner import target_image_count
from quickkick_bot.settings import Settings


def build_slideshow_filter(
    image_count: int,
    seconds_per_image: list[float],
    crossfade_seconds: float = 0.35,
) -> str:
    if image_count <= 0:
        raise ValueError("image_count must be positive")
    if len(seconds_per_image) != image_count:
        raise ValueError("seconds_per_image length must match image_count")

    chains: list[str] = []
    fps = 25
    for index in range(image_count):
        frame_count = max(1, round(seconds_per_image[index] * fps))
        chains.append(
            f"[{index}:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,zoompan=z='min(zoom+0.0008,1.08)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frame_count}:"
            f"s=1080x1920:fps={fps},setsar=1[v{index}]"
        )

    current = "[v0]"
    offset = max(0.0, seconds_per_image[0] - crossfade_seconds)
    for index in range(1, image_count):
        next_label = f"[x{index}]"
        chains.append(
            f"{current}[v{index}]xfade=transition=fade:duration={crossfade_seconds}:"
            f"offset={offset:.3f}{next_label}"
        )
        current = next_label
        offset += max(0.0, seconds_per_image[index] - crossfade_seconds)

    chains.append(f"{current}format=yuv420p[video]")
    return ";".join(chains)


def assemble_motion_video(
    image_paths: list[Path],
    audio_path: Path,
    out_path: Path,
    settings: Settings,
) -> None:
    if not image_paths:
        raise ValueError("image_paths must not be empty")

    ffmpeg = _ffmpeg_bin()
    duration = _probe_audio_duration(audio_path, ffmpeg=ffmpeg)
    image_paths = reconcile_image_paths(image_paths, duration, settings)
    seconds_per_image = _seconds_per_image(duration, len(image_paths))
    filter_text = build_slideshow_filter(len(image_paths), seconds_per_image)

    command = [ffmpeg, "-y"]
    for index, image_path in enumerate(image_paths):
        still_duration = seconds_per_image[index] + 0.35
        command.extend(["-loop", "1", "-t", f"{still_duration:.3f}", "-i", str(image_path)])
    command.extend(
        [
            "-i",
            str(audio_path),
            "-filter_complex",
            filter_text,
            "-map",
            "[video]",
            "-map",
            f"{len(image_paths)}:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(out_path),
        ]
    )
    subprocess.run(command, check=True)


def reconcile_image_paths(
    image_paths: list[Path],
    narration_seconds: float,
    settings: Settings,
) -> list[Path]:
    if not image_paths:
        raise ValueError("image_paths must not be empty")

    target_count = target_image_count(len(image_paths), narration_seconds, settings)
    return [image_paths[index % len(image_paths)] for index in range(target_count)]


def _seconds_per_image(duration: float, image_count: int) -> list[float]:
    if image_count <= 0:
        raise ValueError("image_count must be positive")
    per_image = max(0.1, duration / image_count) if duration > 0 else 0.1
    return [per_image] * image_count


def _ffmpeg_bin() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        return get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - fallback path
        raise RuntimeError(
            "ffmpeg not found on PATH or via imageio_ffmpeg"
        ) from exc


def _probe_audio_duration(audio_path: Path, ffmpeg: str | None = None) -> float:
    ffmpeg = ffmpeg or _ffmpeg_bin()
    probe = subprocess.run(
        [ffmpeg, "-i", str(audio_path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    duration = 60.0
    for line in probe.stderr.splitlines():
        if "Duration:" not in line:
            continue
        try:
            parts = line.split("Duration:")[1].split(",")[0].strip()
            hours, minutes, seconds = parts.split(":")
            duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except Exception:
            pass
        break
    return duration
