from __future__ import annotations

import logging
from pathlib import Path

try:
    from .upscale_library import restore_with_openai, restore_with_openrouter
except ImportError:  # pragma: no cover - direct script execution
    from quickkick_bot.upscale_library import restore_with_openai, restore_with_openrouter


logger = logging.getLogger(__name__)


def prepare_selected_images(selection_plan: dict, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared_paths: list[Path] = []

    for index, selection in enumerate(selection_plan.get("selections", []), start=1):
        src_path = Path(selection["path"])
        dest_path = output_dir / f"scene_{index:02d}.png"
        try:
            prepared_paths.append(restore_with_openai(src_path, dest_path))
        except Exception as openai_error:
            logger.warning("OpenAI image restore failed for %s: %s", src_path.name, openai_error)
            try:
                prepared_paths.append(restore_with_openrouter(src_path, dest_path))
            except Exception as openrouter_error:
                logger.warning("OpenRouter image restore failed for %s: %s", src_path.name, openrouter_error)
                raise

    return prepared_paths
