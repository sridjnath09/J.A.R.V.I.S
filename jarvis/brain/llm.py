"""Ollama client: load/unload, KV-cache prewarm, and streaming chat for text and vision."""

import base64
import io
import json
import logging
from typing import AsyncIterator

import httpx
from PIL import Image

log = logging.getLogger("jarvis.llm")


class OllamaClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.http = httpx.AsyncClient(base_url=cfg.host, timeout=httpx.Timeout(120, connect=5))

    def _options(self, **extra) -> dict:
        # num_ctx must stay identical across calls or Ollama reloads the model and drops the cache.
        return {"num_ctx": self.cfg.num_ctx, **extra}

    async def load(self) -> None:
        await self.http.post("/api/generate", json={"model": self.cfg.model, "keep_alive": self.cfg.keep_alive,
                                                    "options": self._options()})

    async def unload(self) -> None:
        for model in (self.cfg.model, self.cfg.vision_model):
            try:
                await self.http.post("/api/generate", json={"model": model, "keep_alive": 0})
            except httpx.HTTPError:
                pass

    async def prewarm(self, system: str) -> None:
        """Process the system prompt (persona + screen) now, so a question only adds its own tokens."""
        body = {"model": self.cfg.model, "keep_alive": self.cfg.keep_alive, "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": "."}],
                "options": self._options(num_predict=1)}
        r = await self.http.post("/api/chat", json=body)
        d = r.json()
        log.info("prewarm: %s tokens in %.2f s", d.get("prompt_eval_count"), d.get("prompt_eval_duration", 0) / 1e9)

    async def chat(self, system: str, history: list[dict], question: str) -> AsyncIterator[str]:
        messages = [{"role": "system", "content": system}, *history, {"role": "user", "content": question}]
        body = {"model": self.cfg.model, "keep_alive": self.cfg.keep_alive, "stream": True,
                "messages": messages, "options": self._options()}
        async for chunk in self._stream(body):
            yield chunk

    async def vision(self, image: Image.Image, system: str, question: str) -> AsyncIterator[str]:
        img = image.copy()
        img.thumbnail((1280, 1280))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        body = {"model": self.cfg.vision_model, "keep_alive": self.cfg.vision_keep_alive, "stream": True,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": question,
                              "images": [base64.b64encode(buf.getvalue()).decode()]}]}
        async for chunk in self._stream(body):
            yield chunk

    async def _stream(self, body: dict) -> AsyncIterator[str]:
        async with self.http.stream("POST", "/api/chat", json=body) as r:
            async for line in r.aiter_lines():
                if not line:
                    continue
                d = json.loads(line)
                if "error" in d:
                    raise RuntimeError(d["error"])
                text = d.get("message", {}).get("content", "")
                if text:
                    yield text
                if d.get("done"):
                    log.info("llm: prompt %s tok (%.2f s), %s tok out (%.1f tok/s)",
                             d.get("prompt_eval_count"), d.get("prompt_eval_duration", 0) / 1e9,
                             d.get("eval_count"), d.get("eval_count", 0) / max(d.get("eval_duration", 1) / 1e9, 1e-6))
