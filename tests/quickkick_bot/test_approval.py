from pathlib import Path
from unittest import mock
import tempfile
import unittest

from PIL import Image

from quickkick_bot.approval import (
    mark_run_approved,
    mark_run_rejected,
    request_approval,
    wait_for_approval,
)
from quickkick_bot.contact_sheet import build_contact_sheet
from quickkick_bot.state import ApprovalState, load_approval_state, save_approval_state


class ContactSheetTests(unittest.TestCase):
    def test_build_contact_sheet_creates_preview_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            images = []
            for index in range(5):
                path = root / f"img_{index}.png"
                Image.new("RGB", (1080, 1920), (index * 20, index * 20, index * 20)).save(path)
                images.append(path)
            output = build_contact_sheet(images, root / "contact_sheet.png", [f"Scene {i + 1}" for i in range(5)])
            self.assertTrue(output.exists())

    def test_build_contact_sheet_handles_more_than_six_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            images = []
            for index in range(15):
                path = root / f"img_{index}.png"
                Image.new("RGB", (1080, 1920), (10, 10, 10)).save(path)
                images.append(path)
            output = build_contact_sheet(images, root / "contact_sheet.png", [f"Scene {i + 1}" for i in range(15)])
            self.assertTrue(output.exists())
            with Image.open(output) as img:
                self.assertGreater(img.size[0], 0)
                self.assertGreater(img.size[1], 0)


class ApprovalStateTests(unittest.TestCase):
    def test_mark_run_approved_updates_saved_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            save_approval_state(ApprovalState("run-123", "topic", [2], "waiting", False), root)
            mark_run_approved("run-123", root)
            loaded = load_approval_state("run-123", root)
            self.assertTrue(loaded.approved)
            self.assertEqual(loaded.status, "approved")

    def test_mark_run_rejected_updates_saved_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            save_approval_state(ApprovalState("run-456", "topic", [1], "waiting", False), root)
            mark_run_rejected("run-456", root)
            loaded = load_approval_state("run-456", root)
            self.assertFalse(loaded.approved)
            self.assertEqual(loaded.status, "rejected")

    def test_mark_run_approved_raises_for_unknown_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(FileNotFoundError):
                mark_run_approved("does-not-exist", Path(tmpdir))


class WaitForApprovalTests(unittest.TestCase):
    def test_wait_for_approval_returns_true_when_already_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            save_approval_state(ApprovalState("run-789", "topic", [], "approved", True), root)
            self.assertTrue(wait_for_approval("run-789", root, timeout_seconds=1))

    def test_wait_for_approval_returns_false_when_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            save_approval_state(ApprovalState("run-rej", "topic", [], "rejected", False), root)
            self.assertFalse(wait_for_approval("run-rej", root, timeout_seconds=1))

    def test_wait_for_approval_times_out_when_no_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.assertFalse(wait_for_approval("never-requested", root, timeout_seconds=1))


class RequestApprovalTests(unittest.TestCase):
    def test_request_approval_raises_and_marks_delivery_failed_without_telegram_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image_path = root / "scene_1.png"
            Image.new("RGB", (1080, 1920), (5, 5, 5)).save(image_path)

            with self.assertRaises(RuntimeError):
                request_approval(
                    "run-fail",
                    "topic",
                    [image_path],
                    [1],
                    root,
                    bot_token="",
                    chat_id="",
                )
            loaded = load_approval_state("run-fail", root)
            self.assertEqual(loaded.status, "delivery_failed")

    def test_request_approval_raises_immediately_when_no_images_to_preview(self) -> None:
        # Must fail fast rather than parking the run for the full approval
        # timeout when there's nothing to show a reviewer in the first place.
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(RuntimeError):
                request_approval(
                    "run-empty",
                    "topic",
                    [],
                    [1],
                    root,
                    bot_token="fake-token",
                    chat_id="12345",
                )
            loaded = load_approval_state("run-empty", root)
            self.assertEqual(loaded.status, "delivery_failed")

    def test_request_approval_sends_telegram_photo_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image_path = root / "scene_1.png"
            Image.new("RGB", (1080, 1920), (5, 5, 5)).save(image_path)

            with mock.patch("quickkick_bot.approval.requests.post") as mock_post:
                mock_post.return_value = mock.Mock(ok=True)
                state = request_approval(
                    "run-ok",
                    "topic",
                    [image_path],
                    [1],
                    root,
                    bot_token="fake-token",
                    chat_id="12345",
                )
            self.assertEqual(state.status, "waiting")
            mock_post.assert_called_once()
            self.assertIn("fake-token", mock_post.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
