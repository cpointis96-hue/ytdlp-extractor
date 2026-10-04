import os
from pathlib import Path
import subprocess
import shutil
import hashlib
import tempfile
import unittest
from unittest.mock import patch

_data = tempfile.TemporaryDirectory(prefix="extractor-tests-")
os.environ["YTDLP_EXTRACTOR_DATA_DIR"] = str(Path(_data.name) / "data")
os.environ["YTDLP_EXTRACTOR_DOWNLOAD_DIR"] = str(Path(_data.name) / "downloads")

import ytdlp_extractor as app


class CoreTests(unittest.TestCase):
    def test_storage_is_isolated(self):
        self.assertTrue(app.DB_PATH.is_relative_to(_data.name))
        self.assertTrue(app.DOWNLOAD_DIR.is_relative_to(_data.name))

    def test_presets_match_domains_not_substrings(self):
        store = app.Store()
        for url in ("https://www.youtube.com/watch?v=demo", "https://m.youtube.com/watch?v=demo"):
            self.assertEqual(store.preset_for_url(url)["domain"], "youtube.com")
        for url in ("", "http://localhost:4180/media.mp4", "https://youtube.com.attacker.invalid/", "https://notyoutube.com/"):
            self.assertIsNone(store.preset_for_url(url))

    def test_queue_claim_and_finish(self):
        store = app.Store()
        job_id = store.job_add("http://localhost/demo", "Audio")
        job = store.job_claim_next()
        self.assertEqual(job.id, job_id)
        self.assertIsNone(store.job_claim_next())
        store.job_update(job_id, status="done", progress=100)

    def test_failed_conversion_preserves_original(self):
        for returncode, output in ((1, b"partial"), (0, b"")):
            with self.subTest(returncode=returncode, output=output):
                path = Path(_data.name) / "source.mp3"
                path.write_bytes(b"original audio")
                def failed(cmd, **kwargs):
                    Path(cmd[-1]).write_bytes(output)
                    return subprocess.CompletedProcess(cmd, returncode)
                with patch.object(app.subprocess, "run", side_effect=failed):
                    app.Pipeline()._loudnorm(path)
                self.assertEqual(path.read_bytes(), b"original audio")
                self.assertFalse(path.with_suffix(".norm.mp3").exists())

    def test_successful_conversion_replaces_original(self):
        path = Path(_data.name) / "source.opus"
        path.write_bytes(b"original")
        def success(cmd, **kwargs):
            self.assertEqual(cmd[cmd.index("-c:a") + 1], "libopus")
            Path(cmd[-1]).write_bytes(b"normalized")
            return subprocess.CompletedProcess(cmd, 0)
        with patch.object(app.subprocess, "run", side_effect=success):
            app.Pipeline()._loudnorm(path)
        self.assertEqual(path.read_bytes(), b"normalized")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe required")
    def test_real_audio_formats(self):
        codecs = {"mp3": "libmp3lame", "m4a": "aac", "aac": "aac",
                  "opus": "libopus", "wav": "pcm_s16le", "flac": "flac"}
        for extension, codec in codecs.items():
            with self.subTest(extension=extension):
                path = Path(_data.name) / f"tone.{extension}"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                                "sine=frequency=440:sample_rate=48000", "-t", "0.5",
                                "-c:a", codec, str(path)], check=True, capture_output=True)
                original = hashlib.sha256(path.read_bytes()).hexdigest()
                app.Pipeline()._loudnorm(path)
                self.assertNotEqual(hashlib.sha256(path.read_bytes()).hexdigest(), original)
                probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                                        "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True)
                self.assertEqual(probe.stdout.strip(), "audio")
                self.assertFalse(path.with_suffix(".norm." + extension).exists())


if __name__ == "__main__":
    unittest.main()
