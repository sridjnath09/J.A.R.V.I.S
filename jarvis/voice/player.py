"""Cancellable streaming audio output. Exposes the current loudness for the orb animation."""

import asyncio
import threading
from collections import deque

import numpy as np
import sounddevice as sd

from .tts import SAMPLE_RATE


class Player:
    def __init__(self):
        self._chunks: deque[np.ndarray] = deque()
        self._pos = 0
        self._lock = threading.Lock()
        self.level = 0.0
        self._stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                       blocksize=512, callback=self._callback)
        self._stream.start()

    def _callback(self, outdata, frames, time_info, status) -> None:
        out = np.zeros(frames, dtype=np.float32)
        filled = 0
        with self._lock:
            while filled < frames and self._chunks:
                chunk = self._chunks[0]
                n = min(frames - filled, len(chunk) - self._pos)
                out[filled:filled + n] = chunk[self._pos:self._pos + n]
                filled += n
                self._pos += n
                if self._pos >= len(chunk):
                    self._chunks.popleft()
                    self._pos = 0
        outdata[:, 0] = out
        rms = float(np.sqrt(np.mean(out ** 2))) if filled else 0.0
        self.level = 0.6 * self.level + 0.4 * min(1.0, rms * 6)

    def enqueue(self, audio: np.ndarray) -> None:
        if len(audio):
            with self._lock:
                self._chunks.append(audio)

    @property
    def busy(self) -> bool:
        with self._lock:
            return bool(self._chunks)

    def stop(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._pos = 0

    async def drain(self) -> None:
        while self.busy:
            await asyncio.sleep(0.03)
        await asyncio.sleep(0.05)  # let the device buffer empty

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()
