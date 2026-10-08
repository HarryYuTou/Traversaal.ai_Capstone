"""Adapter contract tests with mock phonemes/audio, without model loading."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

from capstone_tts.engine import KokoroEngine


class FakeTensor:
    def __init__(self, data):
        self.data = np.asarray(data, dtype=np.float32)

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.data


class EngineChunkTests(unittest.TestCase):
    def make_engine(self, phonemes="hello", tokens=None):
        engine = object.__new__(KokoroEngine)
        engine.voice = object()
        engine.pipeline = Mock()
        if tokens is None:
            tokens = [SimpleNamespace(text="Hello", phonemes=phonemes)]
        engine.pipeline.g2p.return_value = (phonemes, tokens)
        engine.pipeline.en_tokenize.side_effect = lambda _: iter([("Hello", phonemes, tokens)])
        engine.pipeline.generate_from_tokens.side_effect = lambda *a, **kw: iter([
            SimpleNamespace(audio=FakeTensor([0.1, 0.2])),
            SimpleNamespace(audio=FakeTensor([0.3, 0.4, 0.5])),
        ])
        return engine

    def test_all_results_from_model_are_collected_in_order(self):
        engine = self.make_engine()
        chunks = list(engine.chunks("Hello", 1.0))
        self.assertEqual(len(chunks), 2)
        np.testing.assert_allclose(np.concatenate([a for _, a in chunks]), [0.1, 0.2, 0.3, 0.4, 0.5])
        engine.pipeline.generate_from_tokens.assert_called_once_with("hello", voice=engine.voice, speed=1.0)

    def test_oversized_phonemes_are_rejected_before_inference(self):
        engine = self.make_engine("a" * 511)
        with self.assertRaisesRegex(ValueError, "510"):
            list(engine.chunks("An unusual token", 1.0))
        engine.pipeline.generate_from_tokens.assert_not_called()

    def test_exactly_510_phonemes_are_allowed(self):
        engine = self.make_engine("a" * 510)
        self.assertEqual(len(list(engine.chunks("A permitted token", 1.0))), 2)

    def test_bad_later_paragraph_prevents_inference_for_entire_input(self):
        engine = self.make_engine()
        engine.pipeline.g2p.side_effect = [
            ("hello", [SimpleNamespace(text="Hello", phonemes="hello")]),
            ("", [SimpleNamespace(text="Unreadable", phonemes="")]),
        ]
        with self.assertRaisesRegex(ValueError, "Unreadable"):
            list(engine.chunks("Hello\nUnreadable", 1.0))
        engine.pipeline.generate_from_tokens.assert_not_called()

    def test_empty_punctuation_token_does_not_falsely_fail(self):
        tokens = [SimpleNamespace(text="Hello", phonemes="hello"),
                  SimpleNamespace(text="!", phonemes="")]
        engine = self.make_engine(tokens=tokens)
        self.assertEqual(len(list(engine.chunks("Hello!", 1.0))), 2)

    def test_no_pronounceable_chunks_is_rejected(self):
        engine = self.make_engine("", [SimpleNamespace(text="!", phonemes="")])
        with self.assertRaisesRegex(ValueError, "no pronounceable"):
            list(engine.chunks("!", 1.0))
        engine.pipeline.generate_from_tokens.assert_not_called()

    def test_model_result_without_audio_is_rejected(self):
        engine = self.make_engine()
        engine.pipeline.generate_from_tokens.side_effect = lambda *a, **kw: iter([SimpleNamespace(audio=None)])
        with self.assertRaisesRegex(RuntimeError, "without audio"):
            list(engine.chunks("Hello", 1.0))


if __name__ == "__main__":
    unittest.main()
