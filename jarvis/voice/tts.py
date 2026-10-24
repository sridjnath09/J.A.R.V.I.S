"""Kokoro-82M (ONNX) text-to-speech plus the JARVIS effects chain."""

import gc
import re
import threading

import numpy as np

from ..config import resolve
from . import fx

SAMPLE_RATE = 24000


class TTS:
    def __init__(self, cfg):
        self.cfg = cfg
        self.kokoro = None
        self.board = fx.build(cfg.fx_preset)
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self.kokoro is not None

    def load(self) -> None:
        with self._lock:
            if self.kokoro is None:
                from kokoro_onnx import Kokoro
                self.kokoro = Kokoro(str(resolve(self.cfg.model)), str(resolve(self.cfg.voices)))
                self._synth("Ready.")  # warm-up: the first inference is ~3x slower

    def unload(self) -> None:
        with self._lock:
            self.kokoro = None
        gc.collect()

    def set_preset(self, name: str) -> None:
        self.board = fx.build(name)

    def synth(self, text: str) -> np.ndarray:
        self.load()
        with self._lock:
            return fx.apply(self.board, self._synth(text), SAMPLE_RATE)

    def _synth(self, text: str) -> np.ndarray:
        text = clean_for_speech(text)
        if not text:
            return np.zeros(0, dtype=np.float32)
        audio, _ = self.kokoro.create(text, voice=self.cfg.voice, speed=self.cfg.speed, lang=self.cfg.lang)
        return audio.astype(np.float32)


def clean_for_speech(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"[*_#>|]+", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def chime(kind: str = "listen") -> np.ndarray:
    """A short soft two-tone chime, generated so no audio files are needed."""
    sr = SAMPLE_RATE
    notes = {"listen": (880, 1320), "done": (1320, 880), "error": (440, 330)}[kind]
    out = []
    for f in notes:
        t = np.arange(int(sr * 0.07)) / sr
        env = np.sin(np.pi * t / t[-1]) ** 2
        out.append(0.18 * env * np.sin(2 * np.pi * f * t))
    return np.concatenate(out).astype(np.float32)
