"""Respellings for the voice: listed names change, everything else stays as written."""

import unittest

from capstone_script.pronounce import RESPELLINGS, spoken


class PronunciationTests(unittest.TestCase):
    def test_listed_names_are_respelled(self):
        self.assertEqual(spoken("Zhang Qian left Chang'an."), "Zhang Chee-en left Chang-ahn.")
        self.assertEqual(spoken("The Saturn V rocket"), "The Saturn Five rocket")

    def test_only_whole_words_change(self):
        self.assertEqual(spoken("Qianlong ruled later."), "Qianlong ruled later.")
        self.assertEqual(spoken("A plain sentence."), "A plain sentence.")

    def test_respellings_are_plain_latin_text(self):
        for word, respelling in RESPELLINGS.items():
            with self.subTest(word=word):
                self.assertRegex(respelling, r"^[A-Za-z][A-Za-z' -]*$")


if __name__ == "__main__":
    unittest.main()
