import tempfile
from pathlib import Path
import unittest


class QuickKickImportSmokeTest(unittest.TestCase):
    def test_pipeline_module_exposes_runner(self) -> None:
        from quickkick_bot import pipeline

        self.assertTrue(callable(pipeline._run_pipeline_sync))
        self.assertTrue(hasattr(pipeline, "THUMBNAIL_MIN_SECONDS"))

    def test_clip_selector_returns_zero_tensor_when_all_images_fail(self) -> None:
        from quickkick_bot.clip_selector import _encode_images

        with tempfile.TemporaryDirectory() as tmpdir:
            img1 = Path(tmpdir) / "one.png"
            img2 = Path(tmpdir) / "two.jpg"
            img1.write_text("not an image", encoding="utf-8")
            img2.write_text("still not an image", encoding="utf-8")

            encoded = _encode_images([img1, img2], preprocess=lambda image: image, model=object())

        self.assertEqual(encoded.shape, (2, 512))
        self.assertTrue((encoded == 0).all().item())


if __name__ == "__main__":
    unittest.main()
