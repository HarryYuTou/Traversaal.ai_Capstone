"""Kokoro adapter. Model files are pinned and inference always uses the CPU."""

from pathlib import Path
import re

MODEL_ID = "hexgrad/Kokoro-82M"
MODEL_REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"
VOICE_ID = "af_heart"
SOURCE_RATE = 24_000
OUTPUT_RATE = 48_000


def check_language_dependencies():
    import importlib.util
    if importlib.util.find_spec("en_core_web_sm") is None:
        raise RuntimeError("English language model missing. Install requirements.lock.txt first.")
    from misaki.espeak import EspeakFallback
    fallback = EspeakFallback(british=False)
    if not fallback.backend.phonemize(["hello"])[0].strip():
        raise RuntimeError("English phonemizer failed its smoke check.")


class KokoroEngine:
    def __init__(self, cache_dir: Path, offline: bool = False, threads: int = 2):
        check_language_dependencies()
        import torch
        from huggingface_hub import hf_hub_download
        from kokoro import KModel, KPipeline

        torch.set_num_threads(threads)
        files = {}
        for filename in ("config.json", "kokoro-v1_0.pth", f"voices/{VOICE_ID}.pt"):
            files[filename] = hf_hub_download(
                repo_id=MODEL_ID, revision=MODEL_REVISION, filename=filename,
                cache_dir=str(cache_dir), local_files_only=offline,
            )
        model = KModel(repo_id=MODEL_ID, config=files["config.json"],
                       model=files["kokoro-v1_0.pth"]).to("cpu").eval()
        self.pipeline = KPipeline(lang_code="a", repo_id=MODEL_ID, model=model, device="cpu")
        if self.pipeline.model.device.type != "cpu":
            raise RuntimeError("CPU-only inference was requested but not selected.")
        self.voice = torch.load(files[f"voices/{VOICE_ID}.pt"], map_location="cpu", weights_only=True)

    def chunks(self, text: str, speed: float):
        # Prepare ALL phonemes before inference. Kokoro's convenience call can
        # truncate oversized chunks; reject them explicitly instead.
        prepared = []
        for paragraph in re.split(r"\n+", text):
            if not paragraph.strip():
                continue
            _, tokens = self.pipeline.g2p(paragraph)
            missing = [t.text for t in tokens
                       if any(c.isalnum() for c in t.text) and not t.phonemes]
            if missing:
                raise ValueError(f"No pronunciation found for: {missing!r}. Rewrite these words.")
            for words, phonemes, _ in self.pipeline.en_tokenize(tokens):
                if not phonemes:
                    continue
                if len(phonemes) > 510:
                    raise ValueError("A speech chunk exceeds 510 phonemes; shorten the unusually long word or sentence.")
                prepared.append((words, phonemes))
        if not prepared:
            raise ValueError("The input contains no pronounceable text.")
        for words, phonemes in prepared:
            for result in self.pipeline.generate_from_tokens(phonemes, voice=self.voice, speed=speed):
                if result.audio is None:
                    raise RuntimeError("Kokoro returned a chunk without audio.")
                yield words, result.audio.detach().cpu().numpy()
