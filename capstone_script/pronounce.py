"""Respellings that help the voice say names its dictionary does not know.

Kokoro reads unknown words by English spelling rules, so "Qian" comes out as
"kai-en". schemas/pronunciations.json maps such words to respellings that the
rules read correctly ("Chee-en"). Only the text sent to the voice changes; the
plan, captions and subtitles keep the real spelling.
"""

import json
from pathlib import Path
import re

RESPELLINGS = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "pronunciations.json")
                         .read_text(encoding="utf-8"))
_WORDS = re.compile(r"(?<![\w'])(" + "|".join(re.escape(word) for word in sorted(RESPELLINGS, key=len, reverse=True))
                    + r")(?![\w'])") if RESPELLINGS else None


def spoken(text: str) -> str:
    """The line as the voice should read it."""
    return _WORDS.sub(lambda match: RESPELLINGS[match.group(1)], text) if _WORDS else text
