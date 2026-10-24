"""Speech-to-text with parakeet-mlx on the Apple GPU. Loaded on wake, unloaded in standby.

MLX streams are per-thread, so every call runs on one dedicated worker thread.
"""

import asyncio
import gc
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from ..config import ROOT

log =logging.getLogger("jarvis.stt")


class STT:
    def __init__(self, model_id: str):
        self.model_id = model_id
        self.model = None
        self._warm_clip: np.ndarray | None = None
        self._executor =ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")

    async def _run(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self._executor, fn, *args)

    async def load(self) -> None:
        await self._run(self._load)

    async def unload(self) -> None:
        await self._run(self._unload)

    async def transcribe(self, audio: np.ndarray) -> str:
        return await self._run(self._transcribe, audio)

    async def rewarm(self) -> None:
        """After Ollama has used the GPU, the next MLX decode is ~4x slower (730 vs 180 ms).
        A tiny background decode right after each LLM job keeps the real one fast."""
        if self.model is not None and self._warm_clip is not None:
            await self._run(self._decode, self._warm_clip)

    def _load(self) -> None:
        if self.model is not None:
            return
        from huggingface_hub import snapshot_download
        from parakeet_mlx import from_pretrained
        try:  # use the local copy without any network round-trip
            path = snapshot_download(self.model_id, local_files_only=True)
        except Exception:
            path = snapshot_download(self.model_id)
        self.model = from_pretrained(path)
        # Warm-up on real speech: the first decodes are 3-5x slower, and noise does not exercise the decoder.
        clip = ROOT / "models" / "stt_warmup.npy"
        speech = np.load(clip) if clip.exists() else np.zeros(32000, dtype=np.int16)
        self._warm_clip = speech[: len(speech) // 3]
        for audio in (speech, speech[: len(speech) // 2], speech):
            self._decode(audio)

    def _unload(self) -> None:
        self.model = None
        gc.collect()
        import mlx.core as mx
        mx.clear_cache()

    def _transcribe(self, audio: np.ndarray) -> str:
        self._load()
        return self._decode(audio)

    def _decode(self, audio: np.ndarray) -> str:
        import mlx.core as mx
        from parakeet_mlx.audio import get_logmel
        x = mx.array(audio.astype(np.float32) / 32768.0)
        mel = get_logmel(x, self.model.preprocessor_config)
        return self.model.generate(mel)[0].text.strip()
