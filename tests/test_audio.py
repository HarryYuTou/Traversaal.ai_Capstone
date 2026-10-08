"""Unit tests with synthetic tones; these do not validate real Kokoro speech."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

from capstone_tts.audio import write_run


def tone(frequency=440, samples=12000):
    return (0.25 * np.sin(2 * np.pi * frequency * np.arange(samples) / 24000)).astype(np.float32)


class SyntheticEngine:
    """An injectable unit-test double, never a substitute for model acceptance."""

    def __init__(self, blocks):
        self.blocks = blocks

    def chunks(self, text, speed):
        yield from self.blocks


class AudioRunTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="capstone-tts-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.text_path = self.root / "input.txt"
        self.text_path.write_text("First sentence.\nSecond sentence.\n", encoding="utf-8")
        self.output = self.root / "run"
        # Keep these unit tests independent of installed model/package metadata.
        self.versions = patch("capstone_tts.audio.version", return_value="unit-test-placeholder")
        self.versions.start()
        self.addCleanup(self.versions.stop)

    def run_audio(self, blocks=None, engine_factory=None, **kwargs):
        if engine_factory is None:
            if blocks is None:
                blocks = [("First sentence.", tone())]
            engine_factory = lambda: SyntheticEngine(blocks)
        return write_run(text_path=self.text_path, output_dir=self.output,
                         engine_factory=engine_factory, **kwargs)

    def assert_unpublished(self):
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".tts-*")), [])

    @staticmethod
    def dominant_frequency(samples, rate):
        windowed = samples * np.hanning(len(samples))
        spectrum = np.abs(np.fft.rfft(windowed))
        frequencies = np.fft.rfftfreq(len(samples), 1 / rate)
        return frequencies[np.argmax(spectrum)]

    def test_two_chunks_keep_order_duration_and_pitch_after_real_resampling(self):
        metadata = self.run_audio([
            ("First sentence.", tone(440)),
            ("Second sentence.", tone(880)),
        ])
        samples, rate = sf.read(self.output / "narration.wav")
        info = sf.info(self.output / "narration.wav")
        self.assertEqual(rate, 48000)
        self.assertEqual(len(samples), 48000)
        self.assertEqual(info.channels, 1)
        self.assertEqual(info.subtype, "PCM_16")
        # Header-only rate changes would double the pitches and halve duration.
        self.assertAlmostEqual(self.dominant_frequency(samples[4800:19200], rate), 440, delta=4)
        self.assertAlmostEqual(self.dominant_frequency(samples[28800:43200], rate), 880, delta=4)
        self.assertAlmostEqual(metadata["durationSeconds"], 1.0)
        self.assertEqual(metadata["sampleCount"], 48000)
        self.assertEqual(metadata["sourceSampleCount"], 24000)
        self.assertEqual(metadata["chunkCount"], 2)
        self.assertEqual([c["text"] for c in metadata["chunks"]], ["First sentence.", "Second sentence."])
        self.assertEqual([c["sourceStartSample"] for c in metadata["chunks"]], [0, 12000])
        self.assertEqual([c["sourceSampleCount"] for c in metadata["chunks"]], [12000, 12000])
        saved_metadata = json.loads((self.output / "audio-info.json").read_text())
        self.assertEqual(saved_metadata, metadata)
        self.assertEqual(metadata["listeningReview"], "pending")
        self.assertEqual((self.output / "input.txt").read_text(), self.text_path.read_text())

    def test_odd_source_count_preserves_exact_duration(self):
        metadata = self.run_audio([("Short test.", tone(samples=1601))])
        self.assertEqual(metadata["sourceSampleCount"], 1601)
        self.assertEqual(metadata["sampleCount"], 3202)
        self.assertEqual(sf.info(self.output / "narration.wav").frames, 3202)
        self.assertAlmostEqual(metadata["durationSeconds"], 1601 / 24000)

    def test_no_chunks_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no audio"):
            self.run_audio([])
        self.assert_unpublished()

    def test_invalid_chunks_are_rejected(self):
        invalid = {
            "empty": np.array([], dtype=np.float32),
            "none": None,
            "nan": np.array([0.1, np.nan], dtype=np.float32),
            "infinity": np.array([0.1, np.inf], dtype=np.float32),
            "stereo": np.ones((10, 2), dtype=np.float32),
            "silent": np.zeros(20, dtype=np.float32),
        }
        for name, block in invalid.items():
            with self.subTest(kind=name):
                with self.assertRaises(ValueError):
                    self.run_audio([("Invalid chunk.", block)])
                self.assert_unpublished()

    def test_late_generator_failure_never_publishes_partial_run(self):
        def failing_chunks():
            yield "First sentence.", tone()
            raise RuntimeError("second chunk failed")
        with self.assertRaisesRegex(RuntimeError, "second chunk failed"):
            self.run_audio(failing_chunks())
        self.assert_unpublished()

    def test_engine_initialization_failure_never_publishes_run(self):
        with self.assertRaisesRegex(RuntimeError, "loading failed"):
            self.run_audio(engine_factory=Mock(side_effect=RuntimeError("loading failed")))
        self.assert_unpublished()

    def test_existing_output_is_untouched_and_engine_is_not_called(self):
        self.output.mkdir()
        marker = self.output / "existing-result.txt"
        marker.write_text("keep this")
        factory = Mock()
        with self.assertRaises(FileExistsError):
            self.run_audio(engine_factory=factory)
        factory.assert_not_called()
        self.assertEqual(marker.read_text(), "keep this")
        self.assertEqual(list(self.output.iterdir()), [marker])

    def test_output_created_during_generation_is_not_replaced(self):
        def colliding_chunks():
            yield "First sentence.", tone()
            self.output.mkdir()
            (self.output / "owner.txt").write_text("another run")
        with self.assertRaises(FileExistsError):
            self.run_audio(colliding_chunks())
        self.assertEqual((self.output / "owner.txt").read_text(), "another run")
        self.assertFalse((self.output / "narration.wav").exists())
        self.assertEqual(list(self.root.glob(".tts-*")), [])

    def test_write_failure_cleans_staging_and_publishes_nothing(self):
        with patch("capstone_tts.audio.sf.write", side_effect=OSError("disk unavailable")):
            with self.assertRaisesRegex(OSError, "disk unavailable"):
                self.run_audio()
        self.assert_unpublished()

    def test_bad_input_is_rejected_before_loading_model(self):
        # Escaped Greek samples exercise rejection of non-Latin input.
        for text in ("", " \n\t ", "... !!!", "\u03b3\u03b5\u03b9\u03b1", "Hello \u03ba\u03bf\u03c3\u03bc\u03bf\u03c2", "A" * 20001):
            with self.subTest(text=text[:20]):
                self.text_path.write_text(text, encoding="utf-8")
                factory = Mock()
                with self.assertRaises(ValueError):
                    self.run_audio(engine_factory=factory)
                factory.assert_not_called()
                self.assert_unpublished()

    def test_invalid_speed_is_rejected_before_loading_model(self):
        for speed in (0, 0.49, 2.01, float("nan"), float("inf")):
            with self.subTest(speed=speed):
                factory = Mock()
                with self.assertRaises(ValueError):
                    self.run_audio(engine_factory=factory, speed=speed)
                factory.assert_not_called()
                self.assert_unpublished()

    def test_invalid_cpu_threads_are_rejected_before_loading_model(self):
        for threads in (0, 17):
            with self.subTest(threads=threads):
                factory = Mock()
                with self.assertRaises(ValueError):
                    self.run_audio(engine_factory=factory, threads=threads)
                factory.assert_not_called()

    def test_utf8_bom_is_removed_from_input_snapshot(self):
        self.text_path.write_text("\ufeffHello from a text editor.\n", encoding="utf-8")
        self.run_audio()
        self.assertEqual((self.output / "input.txt").read_text(), "Hello from a text editor.\n")


if __name__ == "__main__":
    unittest.main()
