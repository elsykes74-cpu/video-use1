from pathlib import Path
import unittest


class QuickKickImportSmokeTest(unittest.TestCase):
    def test_pipeline_module_exposes_runner(self) -> None:
        from quickkick_bot import pipeline

        self.assertTrue(callable(pipeline._run_pipeline_sync))
        self.assertTrue(hasattr(pipeline, "THUMBNAIL_MIN_SECONDS"))


if __name__ == "__main__":
    unittest.main()
