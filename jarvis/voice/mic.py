"""Always-on microphone: 16 kHz mono int16 frames of 80 ms, delivered to an asyncio queue."""

import asyncio

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
FRAME = 1280  # 80 ms, the frame size openWakeWord expects


class Mic:
    def __init__(self):
        self.queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=200)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stream: sd.InputStream | None = None

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                      blocksize=FRAME, callback=self._callback)
        self._stream.start()

    def _callback(self, indata, frames, time_info, status) -> None:
        frame = indata[:, 0].copy()
        self._loop.call_soon_threadsafe(self._put, frame)

    def _put(self, frame: np.ndarray) -> None:
        if self.queue.full():
            self.queue.get_nowait()  # drop the oldest frame rather than block the audio thread
        self.queue.put_nowait(frame)

    def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
