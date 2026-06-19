from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quickkick_bot.drive_pool import DriveCandidate, collect_drive_candidates
from quickkick_bot.image_matcher import match_scene_images
import quickkick_bot.pipeline as pipeline


class _FakeExecute:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def execute(self) -> dict:
        return self._payload


class _FakeFilesResource:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.queries: list[str] = []

    def list(self, **kwargs):
        self.queries.append(kwargs.get("q", ""))
        return _FakeExecute(self._responses.pop(0))


class _FakeDriveService:
    def __init__(self, responses: list[dict]) -> None:
        self._files = _FakeFilesResource(responses)

    def files(self) -> _FakeFilesResource:
        return self._files


class DrivePoolAndMatcherTests(unittest.TestCase):
    def test_collect_drive_candidates_expands_regular_and_zip_images(self) -> None:
        service = _FakeDriveService(
            [
                {"files": [{"id": "approved-folder", "name": "Elvis Approved Images"}]},
                {"files": [{"id": "approved-1", "name": "approved-stage.png"}]},
                {"files": [{"id": "drive-1", "name": "cadillac-showroom.jpg"}]},
                {"files": [{"id": "zip-1", "name": "archive.zip"}]},
            ]
        )
        zip_images = [
            {"entry_name": "showroom/elvis-cadillac.png", "cache_path": Path("cache/elvis-cadillac.png")},
        ]

        with patch("quickkick_bot.drive_pool._get_drive_service", return_value=service), patch(
            "quickkick_bot.drive_pool.enumerate_zip_images", return_value=zip_images
        ) as mock_zip_enum:
            candidates = collect_drive_candidates("Elvis in a Cadillac showroom", "Elvis Approved Images")

        self.assertEqual(
            [candidate.source_tier for candidate in candidates],
            ["approved-drive", "drive-file", "drive-zip-image"],
        )
        self.assertEqual(candidates[0].name, "approved-stage.png")
        self.assertEqual(candidates[1].name, "cadillac-showroom.jpg")
        self.assertEqual(candidates[2].name, "showroom/elvis-cadillac.png")
        self.assertEqual(candidates[2].local_cache_path, Path("cache/elvis-cadillac.png"))
        self.assertNotIn("archive.zip", [candidate.name for candidate in candidates])
        mock_zip_enum.assert_called_once_with(service, "zip-1", "archive.zip")
        self.assertTrue(any("mimeType contains 'image/'" in query for query in service.files().queries))
        self.assertTrue(any("application/zip" in query for query in service.files().queries))

    def test_matcher_prefers_local_then_drive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / "elvis-cadillac.png"
            local_path.write_bytes(b"fake")
            scenes = [{"scene": 1, "description": "Elvis in a Cadillac showroom"}]
            drive_candidates = [
                DriveCandidate("drive-1", "drive.png", 0.91, "drive-file", None),
            ]

            result = match_scene_images(
                scenes,
                [Path(tmpdir)],
                drive_candidates,
                weak_threshold=0.55,
            )

        self.assertEqual(result["selections"][0]["source_tier"], "local")
        self.assertEqual(result["weak_scenes"], [])

    def test_matcher_flags_any_weak_scene(self) -> None:
        scenes = [
            {"scene": 1, "description": "Elvis at the microphone"},
            {"scene": 2, "description": "Blue suede shoes close-up"},
        ]
        drive_candidates = [
            DriveCandidate("drive-1", "microphone-stage.png", 0.92, "approved-drive", None),
            DriveCandidate("drive-2", "completely-unrelated.png", 0.22, "drive-file", None),
        ]

        result = match_scene_images(scenes, [], drive_candidates, weak_threshold=0.5)

        self.assertEqual([selection["scene"] for selection in result["selections"]], [1, 2])
        self.assertEqual(result["weak_scenes"], [2])
        self.assertLess(result["selections"][1]["score"], 0.5)

    def test_pipeline_stops_when_any_scene_match_is_weak(self) -> None:
        production_doc = """Topic: Elvis Test

FULL SCRIPT:
Original short script

SCENE BREAKDOWN:
Scene 1 | 0:00-0:03
Elvis enters
Visual Direction: Elvis enters
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "run"

            with patch("quickkick_bot.pipeline._call_openai", return_value="brief narration"), patch.object(
                pipeline, "collect_drive_candidates", return_value=[]
            , create=True), patch.object(
                pipeline,
                "match_scene_images",
                return_value={
                    "selections": [{"scene": 1, "path": "", "score": 0.2, "source_tier": "none"}],
                    "weak_scenes": [1],
                },
                create=True,
            ), patch(
                "quickkick_bot.pipeline.assemble_motion_video"
            ) as mock_assemble, patch("quickkick_bot.pipeline.time.sleep"), patch(
                "quickkick_bot.pipeline._record_run"
            ):
                with self.assertRaisesRegex(RuntimeError, "weak scene"):
                    pipeline._run_pipeline_sync("Elvis Test", out_dir, production_doc)

        mock_assemble.assert_not_called()


if __name__ == "__main__":
    unittest.main()
