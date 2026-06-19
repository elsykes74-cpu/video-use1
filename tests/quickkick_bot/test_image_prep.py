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
            selection_plan = {
                "selections": [
                    {
                        "scene": 1,
                        "path": str(src),
                        "score": 0.9,
                        "source_tier": "local",
                    }
                ]
            }

            with patch(
                "quickkick_bot.image_prep.restore_with_openai",
                side_effect=RuntimeError("quota"),
            ):
                with patch(
                    "quickkick_bot.image_prep.restore_with_openrouter",
                    return_value=output_dir / "scene_01.png",
                ):
                    result = prepare_selected_images(selection_plan, output_dir)

            self.assertEqual(result[0].name, "scene_01.png")


if __name__ == "__main__":
    unittest.main()
