import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from quickkick_bot.planner import plan_image_beats
from quickkick_bot.render import assemble_motion_video, build_slideshow_filter
from quickkick_bot.settings import Settings


class PlannerAndRenderTests(unittest.TestCase):
    def test_planner_expands_scene_count_to_hit_time_density(self) -> None:
        scenes = [
            {"scene": 1, "description": "Elvis in the dealership"},
            {"scene": 2, "description": "Elvis hands over the keys"},
        ]

        beats = plan_image_beats(scenes, narration_seconds=30.0, settings=Settings())

        self.assertGreaterEqual(len(beats), 6)
        self.assertEqual(beats[0]["description"], "Elvis in the dealership")
        self.assertIn("alternate beat", beats[-1]["description"])

    def test_planner_uses_minimum_of_five_images(self) -> None:
        beats = plan_image_beats([], narration_seconds=8.0, settings=Settings())

        self.assertEqual(len(beats), 5)

    def test_planner_trims_scene_count_when_scene_list_is_too_dense(self) -> None:
        scenes = [{"scene": index + 1, "description": f"Scene {index + 1}"} for index in range(15)]

        beats = plan_image_beats(scenes, narration_seconds=30.0, settings=Settings())

        self.assertLessEqual(len(beats), 10)
        self.assertGreaterEqual(len(beats), 6)

    def test_render_filter_contains_crossfade_and_zoompan(self) -> None:
        filter_text = build_slideshow_filter(5, [4.0, 4.0, 4.0, 4.0, 4.0])

        self.assertIn("xfade", filter_text)
        self.assertIn("zoompan", filter_text)

    def test_assemble_motion_video_uses_slideshow_filter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image_paths = []
            for index in range(5):
                image_path = root / f"scene_{index:02d}.png"
                image_path.write_bytes(b"img")
                image_paths.append(image_path)
            audio_path = root / "narration.mp3"
            audio_path.write_bytes(b"audio")
            out_path = root / "video.mp4"

            with patch("quickkick_bot.render._ffmpeg_bin", return_value="ffmpeg"), patch(
                "quickkick_bot.render._probe_audio_duration", return_value=20.0
            ), patch("quickkick_bot.render.subprocess.run") as mock_run:
                assemble_motion_video(image_paths, audio_path, out_path, Settings())

        command = mock_run.call_args.args[0]
        self.assertIn("-filter_complex", command)
        filter_text = command[command.index("-filter_complex") + 1]
        self.assertIn("xfade", filter_text)
        self.assertIn("zoompan", filter_text)


if __name__ == "__main__":
    unittest.main()
