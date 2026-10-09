"""A quiet music bed for a video, synthesized on the spot: no downloads, no licenses to check.

Slow pad chords over a soft bass, with a few bell notes on top, through a synthetic reverb. The bed
ducks under the narration (quietest while a line is spoken) and rises during the title and chapter
cards. It is generated with numpy from a seed, so one timeline always gets the same music.
"""

from pathlib import Path

RATE = 24000
CHORD_SECONDS = 8.0
# A minor: i - VI - III - VII (Am, F, C, G) as MIDI notes, each with its bass note.
PROGRESSION = [([57, 60, 64, 69], 45), ([53, 57, 60, 65], 41), ([55, 60, 64, 67], 48), ([55, 59, 62, 67], 43)]
# Level of the full bed relative to the narration's loudness, and how far it ducks while a line is spoken.
BED_DB = -6.0
DUCK_DB = -12.0
DUCK_SECONDS, RISE_SECONDS, PRE_DUCK_SECONDS = 0.25, 0.9, 0.3
FADE_IN_SECONDS, FADE_OUT_SECONDS = 1.5, 2.5


def _hz(note: int) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def _envelope(np, length: int, attack: int, release: int):
    """Raised-cosine attack and release around a flat middle."""
    envelope = np.ones(length, dtype=np.float32)
    attack, release = min(attack, length // 2), min(release, length // 2)
    envelope[:attack] = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, attack))
    envelope[length - release:] = 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, release))
    return envelope


def _pad_chord(np, rng, notes, bass, seconds: float):
    """One chord as a stereo pad: three detuned voices per note, soft harmonics, slow swells."""
    length = int(seconds * RATE)
    t = np.arange(length, dtype=np.float64) / RATE
    out = np.zeros((length, 2), dtype=np.float64)
    for note in notes:
        for cents, pan in ((-7, 0.2), (0, 0.5), (7, 0.8)):
            frequency = _hz(note) * 2 ** (cents / 1200)
            voice = np.zeros(length)
            for k in range(1, 7):
                voice += np.sin(2 * np.pi * frequency * k * t + rng.uniform(0, 2 * np.pi)) / k ** 1.6
            voice *= 1 + 0.18 * np.sin(2 * np.pi * rng.uniform(0.07, 0.16) * t + rng.uniform(0, 2 * np.pi))
            out[:, 0] += voice * (1 - pan)
            out[:, 1] += voice * pan
    low = np.sin(2 * np.pi * _hz(bass) * t) + 0.25 * np.sin(4 * np.pi * _hz(bass) * t)
    out += 1.6 * low[:, None]
    return out * _envelope(np, length, int(2.5 * RATE), int(3.5 * RATE))[:, None]


def _bell(np, note: int, seconds: float = 2.6):
    t = np.arange(int(seconds * RATE)) / RATE
    tone = np.sin(2 * np.pi * _hz(note) * t) + 0.3 * np.sin(2 * np.pi * 2 * _hz(note) * t) * np.exp(-t / 0.3)
    return tone * np.exp(-t / 0.8) * _envelope(np, t.size, int(0.01 * RATE), int(0.2 * RATE))


def _reverb(np, rng, signal, seconds: float = 2.8, block: int = 1 << 17):
    """Convolve each channel with decaying noise, block by block (overlap-add), and mix it in."""
    length = int(seconds * RATE)
    decay = np.exp(-np.arange(length) / RATE * 6.9 / seconds)
    size = 1 << int(np.ceil(np.log2(block + length)))
    wet = np.zeros((signal.shape[0] + length, 2))
    for channel in range(2):
        response = np.fft.rfft(rng.standard_normal(length) * decay, size)
        for start in range(0, signal.shape[0], block):
            piece = signal[start:start + block, channel]
            tail = np.fft.irfft(np.fft.rfft(piece, size) * response, size)[:piece.size + length]
            wet[start:start + tail.size, channel] += tail
    wet = wet[:signal.shape[0]]
    wet *= np.sqrt(np.mean(signal ** 2) / max(np.mean(wet ** 2), 1e-12))
    return 0.75 * signal + 0.55 * wet


def speech_gain(np, timeline: dict, samples: int):
    """Per-sample gain: 1 with no speech, ducked while (and just before) narration lines play."""
    fps = timeline["fps"]
    frames = timeline["durationInFrames"]
    speaking = np.zeros(frames, dtype=bool)
    lead = round(PRE_DUCK_SECONDS * fps)
    for scene in timeline["scenes"]:
        for line in scene["lines"]:
            speaking[max(0, line["from"] - lead):line["from"] + line["durationInFrames"]] = True
    low = 10 ** (DUCK_DB / 20)
    down, up = 1 / (DUCK_SECONDS * fps), 1 / (RISE_SECONDS * fps)
    gain, level = np.empty(frames), 1.0
    for frame in range(frames):
        target = low if speaking[frame] else 1.0
        level = max(target, level - down) if target < level else min(target, level + up)
        gain[frame] = level
    return np.interp(np.arange(samples) / RATE * fps, np.arange(frames), gain)


def music_bed(timeline: dict, narration_rms: float, seed: int = 7):
    """A stereo float32 array at RATE for the whole timeline."""
    import numpy as np

    rng = np.random.default_rng(seed)
    samples = round(timeline["durationInFrames"] / timeline["fps"] * RATE)
    tail = 4.0
    pads_made = {}

    def pad(variant: int, index: int):
        # Two voicings of each chord, made only when first needed, each from its own seed.
        if (variant, index) not in pads_made:
            notes, bass = PROGRESSION[index]
            pads_made[variant, index] = _pad_chord(np, np.random.default_rng([seed, variant, index]), notes, bass,
                                                   CHORD_SECONDS + tail)
        return pads_made[variant, index]

    # Bell notes sound an octave above the chord.
    bells = {note: _bell(np, note + 12) for notes, _ in PROGRESSION for note in notes}
    pads = np.zeros((samples + int((CHORD_SECONDS + tail) * RATE), 2))
    sparkle = np.zeros_like(pads)
    step = int(CHORD_SECONDS * RATE)
    for index, start in enumerate(range(0, samples, step)):
        chord = pad((index // len(PROGRESSION)) % 2, index % len(PROGRESSION))
        pads[start:start + chord.shape[0]] += chord
        notes = PROGRESSION[index % len(PROGRESSION)][0]
        when = start + int(rng.uniform(0.5, 2.0) * RATE)
        while when < start + step:
            bell = bells[int(rng.choice(notes))]
            pan = rng.uniform(0.25, 0.75)
            for echo, delay in enumerate((0, int(0.375 * RATE), int(0.75 * RATE))):
                at = when + delay
                side = pan if echo % 2 == 0 else 1 - pan
                sparkle[at:at + bell.size, 0] += 0.5 ** echo * bell[:pads.shape[0] - at] * (1 - side)
                sparkle[at:at + bell.size, 1] += 0.5 ** echo * bell[:pads.shape[0] - at] * side
            when += int(rng.uniform(1.6, 3.4) * RATE)
    bed = pads / np.sqrt(np.mean(pads ** 2) + 1e-12) + 0.35 * sparkle / np.sqrt(np.mean(sparkle ** 2) + 1e-12)
    bed = _reverb(np, rng, bed[:samples])
    bed *= 10 ** (BED_DB / 20) * narration_rms / np.sqrt(np.mean(bed ** 2) + 1e-12)
    bed *= speech_gain(np, timeline, samples)[:, None]
    bed *= _envelope(np, samples, int(FADE_IN_SECONDS * RATE), int(FADE_OUT_SECONDS * RATE))[:, None]
    peak = np.max(np.abs(bed))
    return (bed * (0.5 / peak if peak > 0.5 else 1)).astype(np.float32)


def write_music(video_dir: Path, timeline: dict) -> Path:
    """Write video/music.wav for a timeline whose video/narration.wav exists."""
    import numpy as np
    import soundfile as sf

    narration, _ = sf.read(Path(video_dir) / "narration.wav", dtype="float32")
    voiced = narration[np.abs(narration) > 1e-4]
    rms = float(np.sqrt(np.mean(voiced ** 2))) if voiced.size else 0.05
    path = Path(video_dir) / "music.wav"
    sf.write(path, music_bed(timeline, rms), RATE, subtype="PCM_16")
    return path
