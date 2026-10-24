"""The JARVIS sound: a light pedalboard chain on top of Kokoro's British male voice."""

import numpy as np
from pedalboard import (Chorus, Compressor, HighShelfFilter, Limiter, LowShelfFilter, Pedalboard,
                        PitchShift, Reverb)

PRESETS = {
    "subtle":   dict(pitch=-0.4, low=1.5, high=2.0, chorus=0.04, reverb=0.06),
    "classic":  dict(pitch=-0.7, low=2.0, high=3.0, chorus=0.08, reverb=0.12),
    "full-lab": dict(pitch=-1.0, low=3.0, high=4.0, chorus=0.15, reverb=0.22),
}


def build(preset: str) -> Pedalboard | None:
    p = PRESETS.get(preset)
    if p is None:
        return None
    return Pedalboard([
        PitchShift(semitones=p["pitch"]),
        LowShelfFilter(cutoff_frequency_hz=200, gain_db=p["low"]),
        HighShelfFilter(cutoff_frequency_hz=6000, gain_db=p["high"]),
        Chorus(rate_hz=0.6, depth=0.15, centre_delay_ms=7.0, feedback=0.0, mix=p["chorus"]),
        Reverb(room_size=0.15, damping=0.6, wet_level=p["reverb"], dry_level=0.9, width=0.8),
        Compressor(threshold_db=-18, ratio=3, attack_ms=5, release_ms=80),
        Limiter(threshold_db=-1.0),
    ])


def apply(board: Pedalboard | None, audio: np.ndarray, sr: int) -> np.ndarray:
    if board is None:
        return audio
    # Pad so the reverb tail is not cut off at the end of the sentence.
    padded = np.concatenate([audio, np.zeros(int(sr * 0.15), dtype=np.float32)])
    return board(padded, sr, reset=True).astype(np.float32)
