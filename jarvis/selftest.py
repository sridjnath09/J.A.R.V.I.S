"""End-to-end check without microphone or UI.

    .venv/bin/python -m jarvis.selftest            # writes data/selftest.wav
    .venv/bin/python -m jarvis.selftest --play     # also plays the answer
"""

import asyncio
import sys
import time
import wave

import numpy as np
import soxr

from .__main__ import setup_logging
from .brain import prompts
from .brain.llm import OllamaClient
from .brain.sentences import SentenceSplitter
from .config import ROOT, load_config
from .perception import capture, ocr
from .perception.state import ScreenState, ScreenText
from .voice.stt import STT
from .voice.tts import SAMPLE_RATE, TTS

QUESTION = "Jarvis, what am I looking at right now?"  # override: --ask "your question"


async def main(play: bool) -> None:
    setup_logging()
    cfg = load_config()
    t = time.perf_counter

    print("\n[1] Perception (every display)")
    t0 = t()
    win = capture.frontmost_window()
    screens = capture.displays()
    active = capture.window_display(win, screens)
    state = ScreenState()
    state.set_focus(win.app if win else "?", win.title if win else "", False, active.id if active else None)
    for d in screens:
        img = capture.grab(d.bounds)
        text = ocr.recognize(img, cfg.screen.ocr_level)
        state.set_screen(ScreenText(d.id, d.name, text, img))
        print(f"    {d.name}{' (focused)' if active and d.id == active.id else ''}: {img.size}, {len(text)} chars")
    print(f"    focused: {win.app if win else '?'} | {(win.title if win else '')[:60]} | all read in {t() - t0:.2f} s")

    print("[2] Cold start: load TTS, STT, LLM in parallel")
    llm, stt, tts = OllamaClient(cfg.llm), STT(cfg.stt.model), TTS(cfg.tts)
    t0 = t()
    await asyncio.gather(asyncio.to_thread(tts.load), stt.load(), llm.load())
    print(f"    loaded in {t() - t0:.2f} s")
    system = prompts.system_prompt("explain", state.context_block(cfg.llm.max_screen_chars), "")
    t0 = t()
    await llm.prewarm(system)
    print(f"    prewarm (cold KV cache) {t() - t0:.2f} s")
    await stt.rewarm()

    print("[3] Simulated question (Kokoro voice -> 16 kHz -> parakeet)")
    spoken = soxr.resample(tts._synth(QUESTION), SAMPLE_RATE, 16000)
    audio = (np.clip(spoken, -1, 1) * 32767).astype(np.int16)

    t_end = t()  # the moment "you stopped talking"
    heard = await stt.transcribe(audio)
    t_stt = t() - t_end
    print(f"    heard: {heard!r}  STT {t_stt * 1000:.0f} ms")

    print("[4] Answer (prewarmed LLM -> sentence split -> TTS)")
    splitter, answer, out = SentenceSplitter(), "", []
    t_tok = t_audio = None
    async for tok in llm.chat(system, [], heard):
        t_tok = t_tok or t() - t_end
        answer += tok
        for s in splitter.feed(tok):
            out.append(await asyncio.to_thread(tts.synth, s))
            t_audio = t_audio or t() - t_end
    for s in splitter.flush():
        out.append(await asyncio.to_thread(tts.synth, s))
        t_audio = t_audio or t() - t_end
    print(f"    JARVIS: {answer}")
    print(f"\n    LATENCY after you stop talking (VAD end-of-speech adds ~{cfg.listen.end_silence_ms} ms):")
    print(f"      STT {t_stt * 1000:.0f} ms | first token {t_tok * 1000:.0f} ms | first audio {t_audio * 1000:.0f} ms")
    print(f"      => first word heard ~{(t_audio * 1000 + cfg.listen.end_silence_ms):.0f} ms after you finish")

    wav = np.concatenate(out)
    path = ROOT / "data" / "selftest.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(wav, -1, 1) * 32767).astype(np.int16).tobytes())
    print(f"    audio written to {path}")
    if play:
        import sounddevice as sd
        sd.play(wav, SAMPLE_RATE)
        sd.wait()


if __name__ == "__main__":
    if "--ask" in sys.argv:
        QUESTION = sys.argv[sys.argv.index("--ask") + 1]
    asyncio.run(main("--play" in sys.argv))
