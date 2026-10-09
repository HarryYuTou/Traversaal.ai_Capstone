"""Music bed tests: length, ducking under narration, determinism, and the render props that use it."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from capstone_script.music import RATE, music_bed, speech_gain, write_music
from capstone_script.render import render_props


def short_timeline(seconds: int = 12):
    """A silent title, then one line spoken from 4 s to 8 s, then silence."""
    return {"fps": 30, "durationInFrames": seconds * 30,
            "scenes": [{"lines": [{"from": 120, "durationInFrames": 120}]}]}


def rms(samples):
    return float(np.sqrt(np.mean(samples ** 2)))


class MusicTests(unittest.TestCase):
    def test_bed_covers_the_whole_timeline_in_stereo(self):
        bed = music_bed(short_timeline(), narration_rms=0.1)
        self.assertEqual(bed.shape, (12 * RATE, 2))
        self.assertEqual(bed.dtype, np.float32)
        self.assertLessEqual(float(np.abs(bed).max()), 0.5)

    def test_bed_ducks_while_a_line_is_spoken(self):
        bed = music_bed(short_timeline(), narration_rms=0.1).mean(axis=1)
        gap = rms(bed[int(2.5 * RATE):int(3.5 * RATE)])
        speech = rms(bed[int(5 * RATE):int(7 * RATE)])
        self.assertLess(speech, gap / 2)
        gain = speech_gain(np, short_timeline(), 12 * RATE)
        self.assertAlmostEqual(float(gain[int(3 * RATE)]), 1.0, places=3)
        self.assertLess(float(gain[int(6 * RATE)]), 0.3)

    def test_same_timeline_gives_the_same_music(self):
        first = music_bed(short_timeline(6), narration_rms=0.1)
        second = music_bed(short_timeline(6), narration_rms=0.1)
        self.assertTrue(np.array_equal(first, second))

    def test_props_carry_the_theme_and_the_music_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary)
            timeline = {**short_timeline(6), "title": "Test"}
            (video / "timeline.json").write_text(json.dumps(timeline), encoding="utf-8")
            sf.write(video / "narration.wav", np.full(6 * 24000, 0.05, dtype=np.float32), 24000)
            props = json.loads(render_props(video / "timeline.json", "night", True).read_text(encoding="utf-8"))
            self.assertEqual((props["theme"], props["music"], props["title"]), ("night", {"path": "music.wav"}, "Test"))
            self.assertEqual(sf.info(video / "music.wav").channels, 2)
            props = json.loads(render_props(video / "timeline.json", "light", False).read_text(encoding="utf-8"))
            self.assertIsNone(props["music"])
            with self.assertRaisesRegex(ValueError, "Unknown theme"):
                render_props(video / "timeline.json", "neon", False)

    def test_write_music_measures_the_narration(self):
        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary)
            sf.write(video / "narration.wav", np.zeros(4 * 24000, dtype=np.float32), 24000)
            path = write_music(video, short_timeline(4))
            self.assertEqual(sf.info(path).frames, 4 * RATE)


if __name__ == "__main__":
    unittest.main()
