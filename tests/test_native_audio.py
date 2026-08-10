"""Unit tests for native-audio mode in the narration pipeline.

Covers the four guarantees from the design spec:
  1. Chooses the supplied source (does not call TTS).
  2. Refreshes voice.mp3 only when the source changes.
  3. Reports a clear error for a missing source.
  4. TTS projects remain unaffected (no regression).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# We test against the helpers directly.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helpers"))

import make_narration
import make_video


# ── fixtures ──────────────────────────────────────────────────────────────────

def _write_manifest(proj: Path, source: str | None = None) -> Path:
    audio: dict = {"narration_script": "script.txt"}
    if source:
        audio["source"] = source
    else:
        audio.update({"voice": "en-US-GuyNeural", "rate": "-10%"})
    m = {
        "job_id": "test",
        "title": "Test",
        "format": {"width": 1920, "height": 1080, "fps": 30},
        "audio": audio,
        "scenes": [],
    }
    mpath = proj / "manifest.json"
    mpath.write_text(json.dumps(m), encoding="utf-8")
    return mpath


def _touch(p: Path, content: bytes = b"fake") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


# ── make_narration.native_audio_mode ─────────────────────────────────────────

class TestNativeAudioMode:
    def test_missing_source_returns_error(self, tmp_path):
        source = tmp_path / "missing.m4a"
        out = tmp_path / "voice.mp3"
        rc = make_narration.native_audio_mode(source, out)
        assert rc != 0
        assert not out.exists()

    def test_normalises_when_voice_missing(self, tmp_path):
        source = _touch(tmp_path / "narration.m4a")
        out = tmp_path / "voice.mp3"
        # out does not exist yet — ffmpeg should be invoked

        def fake_run(cmd, **kw):
            if "ffmpeg" in cmd[0]:
                _touch(out)  # simulate ffmpeg creating the output file
                return MagicMock(returncode=0)
            return MagicMock(returncode=0, stdout="1348.73\n")  # ffprobe

        with patch("make_narration.subprocess.run", side_effect=fake_run) as mock_run:
            rc = make_narration.native_audio_mode(source, out)

        assert rc == 0
        assert mock_run.called
        ffmpeg_call = mock_run.call_args_list[0]
        cmd = ffmpeg_call[0][0]
        assert "ffmpeg" in cmd[0]
        assert "loudnorm" in " ".join(cmd)
        assert str(source) in cmd
        assert str(out) in cmd

    def test_skips_when_voice_is_newer(self, tmp_path):
        source = _touch(tmp_path / "narration.m4a")
        out = _touch(tmp_path / "voice.mp3")
        # Make voice.mp3 definitively newer than source.
        out.touch()
        time.sleep(0.01)
        source.touch()
        # Now source is newer — flip: make out newer than source.
        time.sleep(0.01)
        out.touch()

        with patch("make_narration.subprocess.run") as mock_run:
            rc = make_narration.native_audio_mode(source, out)
        mock_run.assert_not_called()
        assert rc == 0

    def test_renormalises_when_source_is_newer(self, tmp_path):
        out = _touch(tmp_path / "voice.mp3")
        time.sleep(0.05)
        source = _touch(tmp_path / "narration.m4a")  # source is newer
        assert source.stat().st_mtime > out.stat().st_mtime

        def fake_run(cmd, **kw):
            if "ffmpeg" in cmd[0]:
                out.touch()  # update mtime (simulate ffmpeg ran)
                return MagicMock(returncode=0)
            return MagicMock(returncode=0, stdout="1348.73\n")

        with patch("make_narration.subprocess.run", side_effect=fake_run) as mock_run:
            rc = make_narration.native_audio_mode(source, out)
        assert mock_run.called
        assert rc == 0


# ── make_narration.main() — manifest dispatch ─────────────────────────────────

class TestManifestDispatch:
    def test_native_mode_chosen_when_source_present(self, tmp_path):
        source = _touch(tmp_path / "narration.m4a")
        _write_manifest(tmp_path, source=str(source))
        sys.argv = ["make_narration.py", "--manifest", str(tmp_path / "manifest.json")]
        with patch("make_narration.native_audio_mode", return_value=0) as mock_nat:
            rc = make_narration.main()
        # native_audio_mode must be called; TTS (asyncio.run) must not be called
        mock_nat.assert_called_once()
        assert rc == 0

    def test_tts_mode_when_no_source(self, tmp_path):
        _write_manifest(tmp_path, source=None)
        (tmp_path / "script.txt").write_text("Hello world.", encoding="utf-8")
        # Without source, main() should try TTS (will fail due to no edge_tts,
        # but the important check is that native_audio_mode is NOT called).
        with patch("make_narration.native_audio_mode") as mock_nat, \
             patch("make_narration.asyncio.run", side_effect=SystemExit(0)):
            sys.argv = ["make_narration.py", "--manifest", str(tmp_path / "manifest.json")]
            try:
                make_narration.main()
            except SystemExit:
                pass
        mock_nat.assert_not_called()


# ── make_video.stage_narration — orchestrator integration ────────────────────

class TestStageNarration:
    def _base_manifest(self, source: str | None) -> dict:
        audio: dict = {"narration_script": "script.txt"}
        if source:
            audio["source"] = source
        else:
            audio.update({"voice": "en-US-GuyNeural", "rate": "-10%"})
        return {"audio": audio, "scenes": [], "job_id": "test", "title": "T",
                "format": {}}

    def test_native_skips_edge_tts_ensure(self, tmp_path):
        source = _touch(tmp_path / "narration.m4a")
        voice = _touch(tmp_path / "voice.mp3")
        time.sleep(0.01)
        voice.touch()  # voice is newer
        m = self._base_manifest(str(source))
        with patch("make_video.ensure") as mock_ensure, \
             patch("make_video.sh", return_value=0):
            # voice is newer than source, so stage skips entirely
            result = make_video.stage_narration(tmp_path, m, force=False)
        mock_ensure.assert_not_called()
        assert result is True

    def test_native_error_on_missing_source(self, tmp_path):
        m = self._base_manifest(str(tmp_path / "missing.m4a"))
        with patch("make_video.sh") as mock_sh:
            result = make_video.stage_narration(tmp_path, m, force=False)
        mock_sh.assert_not_called()
        assert result is False

    def test_tts_mode_unchanged(self, tmp_path):
        m = self._base_manifest(source=None)
        script = _touch(tmp_path / "script.txt", b"Hello.")
        voice = _touch(tmp_path / "voice.mp3")
        bounds = _touch(tmp_path / "voice_boundaries.json", b"[]")
        time.sleep(0.01)
        voice.touch()  # voice newer than script
        with patch("make_video.ensure") as mock_ensure, \
             patch("make_video.sh") as mock_sh:
            result = make_video.stage_narration(tmp_path, m, force=False)
        # Should skip (all up to date) without calling sh or ensure
        mock_sh.assert_not_called()
        assert result is True


# ── make_video.stage_script — native transcription path ─────────────────────

class TestStageScript:
    def test_native_transcribes_when_script_missing(self, tmp_path):
        source = _touch(tmp_path / "narration.m4a")
        m = {
            "audio": {"narration_script": "script.txt", "source": str(source)},
            "scenes": [],
        }
        fake_words = [MagicMock(word=" hello", start=0.0, end=0.5),
                      MagicMock(word=" world", start=0.5, end=1.0)]
        fake_seg = MagicMock(text=" hello world", words=fake_words)
        fake_info = MagicMock(duration=1.0)

        with patch("make_video.ensure"), \
             patch("make_video._transcribe_to_script",
                   return_value=True) as mock_tr:
            result = make_video.stage_script(tmp_path, m, force=False)
        mock_tr.assert_called_once()
        assert result is True

    def test_native_skips_when_script_fresh(self, tmp_path):
        source = _touch(tmp_path / "narration.m4a")
        script = _touch(tmp_path / "script.txt", b"hello world")
        bounds = _touch(tmp_path / "voice_boundaries.json", b"[]")
        time.sleep(0.01)
        script.touch()  # script is newer than source
        m = {
            "audio": {"narration_script": "script.txt", "source": str(source)},
            "scenes": [],
        }
        with patch("make_video.ensure") as mock_ensure, \
             patch("make_video._transcribe_to_script") as mock_tr:
            result = make_video.stage_script(tmp_path, m, force=False)
        mock_tr.assert_not_called()
        assert result is True

    def test_tts_mode_errors_without_script(self, tmp_path):
        m = {
            "audio": {"narration_script": "script.txt",
                      "voice": "en-US-GuyNeural"},
            "scenes": [],
        }
        result = make_video.stage_script(tmp_path, m, force=False)
        assert result is False
