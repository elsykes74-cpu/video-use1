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

    def test_matcher_uses_drive_when_local_match_is_weak(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_dir = Path(tmpdir) / "local"
            local_dir.mkdir()
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            local_path = local_dir / "totally-unrelated.png"
            local_path.write_bytes(b"fake")
            drive_path = cache_dir / "elvis-stage.png"
            drive_path.write_bytes(b"fake")
            scenes = [{"scene": 1, "description": "Elvis on stage"}]
            drive_candidates = [
                DriveCandidate("drive-1", "elvis-stage.png", 0.9, "drive-file", drive_path),
            ]

            result = match_scene_images(
                scenes,
                [local_dir],
                drive_candidates,
                weak_threshold=0.55,
            )

        self.assertEqual(result["selections"][0]["source_tier"], "drive-file")
        self.assertEqual(result["weak_scenes"], [])

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

    def test_collect_scene_images_supplements_partial_local_coverage_from_drive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / "scene_01.png"
            local_path.write_bytes(b"local")
            drive_path = Path(tmpdir) / "drive_02.png"
            drive_path.write_bytes(b"drive")
            scenes = [
                {"scene": 1, "description": "Elvis enters"},
                {"scene": 2, "description": "Elvis waves"},
            ]

            with patch.object(
                pipeline, "_clip_select_images", return_value=[local_path]
            ), patch.object(
                pipeline, "collect_drive_candidates", return_value=[DriveCandidate("drive-2", "drive_02.png", 0.9, "drive-file", drive_path)]
            ) as mock_collect, patch.object(
                pipeline,
                "match_scene_images",
                return_value={
                    "selections": [
                        {
                            "scene": 1,
                            "path": str(local_path),
                            "local_cache_path": str(local_path),
                            "score": 1.0,
                            "source_tier": "local",
                            "file_id": "",
                            "name": local_path.name,
                        },
                        {
                            "scene": 2,
                            "path": str(drive_path),
                            "local_cache_path": str(drive_path),
                            "score": 0.9,
                            "source_tier": "drive-file",
                            "file_id": "drive-2",
                            "name": "drive_02.png",
                        },
                    ],
                    "weak_scenes": [],
                },
            ), patch.object(
                pipeline, "ensure_candidate_cached", side_effect=lambda candidate: candidate.local_cache_path
            ) as mock_cache:
                paths = pipeline._collect_scene_images("Elvis Test", scenes)

        self.assertEqual(paths, [local_path, drive_path])
        mock_collect.assert_called_once()
        mock_cache.assert_called_once()

    def test_collect_scene_images_skips_drive_when_local_coverage_is_strong(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_dir = Path(tmpdir) / "local"
            local_dir.mkdir()
            first_local = local_dir / "elvis-enters.png"
            second_local = local_dir / "elvis-waves.png"
            first_local.write_bytes(b"local")
            second_local.write_bytes(b"local")
            scenes = [
                {"scene": 1, "description": "Elvis enters"},
                {"scene": 2, "description": "Elvis waves"},
            ]

            with patch.object(
                pipeline, "_clip_select_images", return_value=[first_local, second_local]
            ), patch.object(
                pipeline,
                "_local_image_dirs",
                return_value=[local_dir],
            ), patch.object(
                pipeline,
                "collect_drive_candidates",
                side_effect=AssertionError("Drive should not be queried for strong local coverage"),
            ):
                paths = pipeline._collect_scene_images("Elvis Test", scenes)

        self.assertEqual(paths, [first_local, second_local])

    def test_collect_scene_images_does_not_trust_fallback_local_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_dir = Path(tmpdir) / "local"
            local_dir.mkdir()
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            first_local = local_dir / "elvis-enters.png"
            second_local = local_dir / "b.png"
            first_local.write_bytes(b"local")
            second_local.write_bytes(b"local")
            drive_path = cache_dir / "elvis-stage.png"
            drive_path.write_bytes(b"drive")
            scenes = [
                {"scene": 1, "description": "Elvis enters"},
                {"scene": 2, "description": "Elvis on stage"},
            ]

            with patch.object(
                pipeline,
                "_clip_select_images",
                return_value=[first_local, second_local],
            ), patch.object(
                pipeline,
                "_local_image_dirs",
                return_value=[local_dir],
            ), patch.object(
                pipeline,
                "_LAST_CLIP_SELECTION_TRUSTED",
                False,
            ), patch.object(
                pipeline,
                "collect_drive_candidates",
                return_value=[DriveCandidate("drive-1", "elvis-stage.png", 0.9, "drive-file", drive_path)],
            ) as mock_collect:
                paths = pipeline._collect_scene_images("Elvis Test", scenes)

        self.assertEqual(paths[0], first_local)
        self.assertEqual(paths[1], drive_path)
        mock_collect.assert_called_once()

    def test_pipeline_uses_matching_path_for_generated_topics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "run"
            matched_path = Path(tmpdir) / "matched.png"
            matched_path.write_bytes(b"matched")

            with patch("quickkick_bot.pipeline._call_openai", side_effect=[
                "polished narration",
                '[{"scene": 1, "description": "Elvis enters the stage"}]',
            ]), patch.object(
                pipeline, "_collect_scene_images", return_value=[matched_path]
            ) as mock_collect, patch(
                "quickkick_bot.pipeline._synthesize_speech",
                side_effect=lambda narration, audio_path: audio_path.write_bytes(b"audio"),
            ), patch("quickkick_bot.pipeline._probe_audio_duration", return_value=40.0), patch(
                "quickkick_bot.pipeline.assemble_motion_video"
            ) as mock_assemble, patch(
                "quickkick_bot.pipeline._youtube_upload", return_value=""
            ), patch("quickkick_bot.pipeline.time.sleep"), patch(
                "quickkick_bot.pipeline._record_run"
            ):
                result = pipeline._run_pipeline_sync("Elvis Test", out_dir, initial_script="seed script")

        self.assertEqual(result["status"], "finished")
        mock_collect.assert_called_once()
        render_inputs = mock_assemble.call_args.args[0]
        self.assertGreaterEqual(len(render_inputs), 1)
        self.assertTrue(all(path.name == "scene_01.png" for path in render_inputs))


if __name__ == "__main__":
    unittest.main()
