import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from quickkick_bot.settings import Settings, load_settings
from quickkick_bot.state import ApprovalState, load_approval_state, save_approval_state


class SettingsAndStateTests(unittest.TestCase):
    def test_load_settings_uses_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertIsInstance(settings, Settings)
        self.assertEqual(settings.thumbnail_min_seconds, 120.0)
        self.assertEqual(settings.minimum_images, 5)

    def test_save_and_load_approval_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = ApprovalState(
                run_id="run-123",
                topic="Elvis Gives Mennie Person the Car",
                weak_scenes=[3],
                status="waiting",
                approved=False,
            )
            save_approval_state(state, root)
            loaded = load_approval_state("run-123", root)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.run_id, "run-123")
            self.assertEqual(loaded.weak_scenes, [3])


if __name__ == "__main__":
    unittest.main()
