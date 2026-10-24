"""J.A.R.V.I.S orchestrator: lifecycle, audio routing, the question pipeline and the UI."""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from .brain import prompts, router
from .brain.llm import OllamaClient
from .brain.sentences import SentenceSplitter
from .config import resolve
from .memory.store import Memory
from .perception import pointer
from .perception.state import ScreenState
from .perception.watcher import ScreenWatcher
from .voice.detectors import VoiceActivity, WakeWord
from .voice.mic import FRAME, SAMPLE_RATE, Mic
from .voice.player import Player
from .voice.stt import STT
from .voice.tts import TTS, chime

log = logging.getLogger("jarvis")

FRAME_MS = FRAME * 1000 // SAMPLE_RATE  # 80


@dataclass
class Recording:
    source: str
    cold: bool = False
    ptt: bool = False
    frames: list = field(default_factory=list)
    skip: int = 2                # frames to ignore while the chime plays
    speech_frames: int = 0
    speech_started: bool = False
    silence_ms: int = 0
    started: float = field(default_factory=time.monotonic)
    greeted: bool = False


class Jarvis:
    def __init__(self, cfg, ui: bool = True):
        self.cfg = cfg
        self.memory = Memory(resolve(cfg.memory.db))
        self.screen = ScreenState()
        self.watcher = ScreenWatcher(cfg.screen, self.screen, self.on_screen_update,
                                     anchor=self._orb_center if ui else None)
        self.llm = OllamaClient(cfg.llm)
        self.stt = STT(cfg.stt.model)
        self.tts = TTS(cfg.tts)
        self.player = Player()
        self.wake = WakeWord(cfg.wake.threshold)
        self.vad = VoiceActivity(cfg.listen.vad_threshold)
        self.mic = Mic()

        self.life = "standby"          # standby | waking | active | warm_idle
        self.activity = "idle"         # idle | listening | thinking | speaking
        self.listen_mode = "wake"      # wake | follow | record | muted
        self.paused = False
        self.stay_awake = False
        self.mode = "explain"
        self.fx_preset = cfg.tts.fx_preset
        self.history: list[dict] = []
        self.memory_block = ""
        self.models_ready = asyncio.Event()
        self.rec: Recording | None = None
        self.last_activity = time.monotonic()
        self.window_until = 0.0
        self.prewarmed_system = ""
        self._prewarmed_key: tuple = ()
        self._prewarmed_lines: dict = {}
        self._prewarm_lines: dict = {}
        self._prewarm_task: asyncio.Task | None = None
        self._prewarm_target = ""
        self._prewarm_key: tuple = ()
        self._turn_task: asyncio.Task | None = None
        self._warm_task: asyncio.Task | None = None
        self._follow_hits = 0
        self._barge_hits = 0
        self._last_pointer: tuple[float, float] | None = None
        self._last_app_pid: int | None = None
        self._moment_task: asyncio.Task | None = None

        self.ui = ui
        self.orb = self.panel = self.menu = self.tray = None
        if ui:
            self._build_ui()

    # ================================================================== startup / UI
    def _orb_center(self) -> tuple[float, float] | None:
        """Where the orb is, in global points (same coordinates as Quartz display bounds)."""
        if self.orb is None:
            return None
        c = self.orb.geometry().center()
        return (c.x(), c.y())

    def _build_ui(self) -> None:
        from .ui import hotkey, menu, orb, panel
        self.orb = orb.Orb(self.cfg.ui.orb_size, level_source=lambda: self.player.level)
        self.panel = panel.TranscriptPanel()
        self.menu = menu.build_menu(self)
        self.tray = menu.tray_icon(self.menu)
        self.orb.clicked.connect(self.on_orb_click)
        self.orb.double_clicked.connect(self.toggle_panel)
        self.orb.hold_started.connect(self.on_hold_start)
        self.orb.hold_ended.connect(self.on_hold_end)
        self.orb.context_menu.connect(lambda pos: self.menu.popup(pos))
        self.orb.show()
        hotkey.register(self.cfg.ui.toggle_hotkey, self.toggle_orb)
        hotkey.register(self.cfg.ui.get("stop_hotkey", "esc"), self.on_stop_key)

    async def start(self) -> None:
        self.mic.start()
        self.watcher.start()
        asyncio.create_task(self._audio_loop())
        asyncio.create_task(self._lifecycle_loop())
        asyncio.create_task(self._pointer_loop())
        self._refresh_ui()
        log.info("J.A.R.V.I.S standing by. Say 'Hey Jarvis' or click the orb.")

    # ================================================================== audio routing
    async def _audio_loop(self) -> None:
        preroll: deque = deque(maxlen=4)
        while True:
            frame = await self.mic.queue.get()
            try:
                if self.paused:
                    continue
                mode = self.listen_mode
                if mode == "record":
                    self._record_frame(frame)
                elif mode == "muted":
                    if self.activity not in ("speaking", "thinking"):
                        continue
                    preroll.append(frame)
                    # "Hey Jarvis" always interrupts: the wake-word model does not fire on JARVIS's own voice,
                    # so this is safe even on speakers.
                    if self.wake.detect(frame):
                        log.info("interrupted by wake word")
                        self.interrupt()
                        self.player.enqueue(chime("listen"))
                        self._start_recording("wake word")
                    # Talking over JARVIS: only with headphones, or it would hear itself.
                    elif self.cfg.listen.barge_in:
                        # Stricter than normal listening (~0.4 s of confident speech) so headset sidetone,
                        # breathing or room noise does not cut JARVIS off.
                        lc = self.cfg.listen
                        speech = self.vad.is_speech(frame, lc.get("barge_in_threshold", 0.8))
                        self._barge_hits = self._barge_hits + 1 if speech else 0
                        if self._barge_hits >= lc.get("barge_in_frames", 5):
                            self._barge_hits = 0
                            log.info("interrupted by voice (barge-in)")
                            self.interrupt()
                            self._start_recording("barge-in", frames=list(preroll))
                else:
                    preroll.append(frame)
                    if self.wake.detect(frame):
                        self.on_wake("wake word")
                    elif mode == "follow":
                        self._follow_hits = self._follow_hits + 1 if self.vad.is_speech(frame) else 0
                        if self._follow_hits >= 2:
                            self._follow_hits = 0
                            self._start_recording("follow-up", frames=list(preroll))
            except Exception:
                log.exception("audio loop error")

    def _start_recording(self, source: str, frames=None, cold=False, ptt=False) -> None:
        self.vad.reset()
        self.rec = Recording(source, cold=cold, ptt=ptt, frames=list(frames or []), skip=0 if frames else 2)
        if frames:
            self.rec.speech_started, self.rec.speech_frames = True, 2
        self.listen_mode = "record"
        self._set_activity("listening")
        self._moment_task = asyncio.create_task(self._capture_moment())
        if self.models_ready.is_set():
            asyncio.create_task(self._prepare_for_question())

    # ================================================================== pointer and selection
    def _over_orb(self, pt: tuple[float, float]) -> bool:
        if self.orb is None or not self.orb.isVisible():
            return False
        g = self.orb.frameGeometry()
        return g.left() <= pt[0] <= g.right() and g.top() <= pt[1] <= g.bottom()

    async def _pointer_loop(self) -> None:
        """Remember where the pointer was before it went to the orb, and which app you were in."""
        while True:
            await asyncio.sleep(0.25)
            try:
                pt = pointer.location()
                if not self._over_orb(pt):
                    self._last_pointer = pt
                pid = pointer.frontmost_pid()
                if pid:
                    self._last_app_pid = pid
            except Exception:
                log.debug("pointer sample failed", exc_info=True)

    async def _capture_moment(self) -> dict:
        """At the moment you start asking: where the pointer is and what is highlighted."""
        pt = pointer.location()
        if self._over_orb(pt):  # you clicked the orb: use where the pointer was just before
            pt = self._last_pointer or pt
        pid = pointer.frontmost_pid() or self._last_app_pid
        selection = await asyncio.to_thread(pointer.selected_text, pid)
        return {"point": pt, "selection": selection}

    async def _moment_note(self, question: str) -> tuple[str, dict]:
        moment = {}
        if self._moment_task is not None:
            try:
                moment = await asyncio.wait_for(self._moment_task, 1.0)
            except Exception:
                moment = {}
        if not moment.get("selection") and router.mentions_selection(question):
            moment["selection"] = await asyncio.to_thread(pointer.copy_selection)
            if moment["selection"]:
                log.info("selection read via copy fallback")
        lines = []
        sel = (moment.get("selection") or "")[:1500]
        if sel:
            lines.append(f'SELECTED TEXT (highlighted by the user):\n"""\n{sel}\n"""')
        pt = moment.get("point")
        screen = next((s for s in self.screen.current.screens.values() if pt and s.contains(*pt)), None)
        # Only when the question points at something ("what is this?"); otherwise the model fixates on
        # whatever the mouse happens to rest on.
        if screen is not None and not sel and router.points_at_something(question):
            under, around = pointer.text_near(screen.boxes, pt)
            if under:
                lines.append(f'UNDER THE MOUSE POINTER: "{under}"')
            if around:
                lines.append(f"TEXT AROUND THE POINTER:\n{around}")
        moment["screen"] = screen
        note = ("\n\n[AT THE MOMENT OF ASKING]\n" + "\n".join(lines)) if lines else ""
        return note, moment

    def _crop_near_pointer(self, moment: dict):
        """For visual questions: the part of the screen around the pointer, sharper and faster than all of it."""
        screen, pt = moment.get("screen"), moment.get("point")
        if screen is None or screen.image is None or not pt:
            return self.watcher.latest_image
        img = screen.image
        bx, by, bw, bh = screen.bounds
        scale = img.width / bw
        cx, cy = (pt[0] - bx) * scale, (pt[1] - by) * scale
        half_w, half_h = 600 * scale, 380 * scale
        left = max(0, min(cx - half_w, img.width - 2 * half_w))
        top = max(0, min(cy - half_h, img.height - 2 * half_h))
        return img.crop((int(left), int(top), int(min(img.width, left + 2 * half_w)),
                         int(min(img.height, top + 2 * half_h))))

    def _record_frame(self, frame: np.ndarray) -> None:
        rec, lc = self.rec, self.cfg.listen
        if rec.skip:
            rec.skip -= 1
            return
        rec.frames.append(frame)
        now = time.monotonic()
        if rec.ptt:
            if now - rec.started > lc.max_utterance_s:
                self._finish_recording()
            return
        if self.vad.is_speech(frame):
            rec.speech_frames += 1
            rec.silence_ms = 0
            if rec.speech_frames >= 2:
                rec.speech_started = True
        elif rec.speech_started:
            rec.silence_ms += FRAME_MS
        if rec.speech_started and rec.silence_ms >= lc.end_silence_ms:
            self._finish_recording()
        elif not rec.speech_started and now - rec.started > lc.no_speech_timeout_s:
            self._finish_recording()
        elif now - rec.started > lc.max_utterance_s:
            self._finish_recording()
        elif (rec.cold and not rec.greeted and not rec.speech_started and self.tts.loaded
              and now - rec.started > lc.greeting_after_s):
            rec.greeted = True
            asyncio.create_task(self._greet())

    def _finish_recording(self) -> None:
        rec, self.rec = self.rec, None
        if rec is None:
            return
        self.listen_mode = "muted"
        has_speech = rec.speech_started or (rec.ptt and len(rec.frames) > 3)
        if not has_speech:
            log.info("no speech heard")
            self.after_turn()
            return
        audio = np.concatenate(rec.frames)
        self._turn_task = asyncio.create_task(self.handle_turn(audio, rec.source, time.monotonic()))

    async def _greet(self) -> None:
        """Cold wake and you have not started talking: acknowledge, then keep listening."""
        if self.listen_mode != "record":
            return
        self.listen_mode = "muted"
        hour = time.localtime().tm_hour
        if self.memory.first_wake_today():
            part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
            text = f"Good {part}, sir. All systems online."
        else:
            text = "Yes, sir?"
        self._set_activity("speaking")
        self.player.enqueue(await asyncio.to_thread(self.tts.synth, text))
        await self.player.drain()
        if self.rec is not None:
            self.rec.started, self.rec.frames, self.rec.skip = time.monotonic(), [], 1
            self.vad.reset()
            self.listen_mode = "record"
            self._set_activity("listening")

    # ================================================================== wake / lifecycle
    def on_wake(self, source: str) -> None:
        if self.paused:
            return
        self.touch()
        cold = self.life == "standby"
        if cold:
            self.life = "waking"
            self._warm_task = asyncio.create_task(self.warm_up())
        self.player.enqueue(chime("listen"))
        self._start_recording(source, cold=cold)
        log.info("wake (%s)%s", source, " - cold start" if cold else "")

    async def warm_up(self) -> None:
        t0 = time.perf_counter()
        self.memory_block = self.memory.profile_block()
        self._refresh_ui()
        try:
            await asyncio.gather(asyncio.to_thread(self.tts.load), self.stt.load(), self.llm.load())
        except Exception:
            log.exception("warm-up failed (is Ollama running?)")
            self.life = "standby"
            self._refresh_ui()
            return
        log.info("models loaded in %.1f s", time.perf_counter() - t0)
        self.models_ready.set()
        if self.life == "waking":
            self.life = "active"
            self.window_until = time.monotonic() + self.cfg.lifecycle.conversation_window_s
        self.schedule_prewarm()
        self._refresh_ui()

    async def go_standby(self, announce: bool = True) -> None:
        log.info("going to standby")
        self.interrupt(resume=False)
        if announce and self.tts.loaded:
            self._set_activity("speaking")
            self.player.enqueue(await asyncio.to_thread(self.tts.synth, "Standing by, sir."))
            await self.player.drain()
        if self._warm_task and not self._warm_task.done():
            self._warm_task.cancel()
        if self._prewarm_task and not self._prewarm_task.done():
            self._prewarm_task.cancel()
        self.life = "standby"
        self.activity = "idle"
        self.listen_mode = "wake"
        self.models_ready.clear()
        self.prewarmed_system, self._prewarmed_key = "", ()
        self.history.clear()
        self.stay_awake = False
        await self.llm.unload()
        await self.stt.unload()
        self.tts.unload()
        self._refresh_ui()

    def request_standby(self) -> None:
        asyncio.create_task(self.go_standby())

    async def _lifecycle_loop(self) -> None:
        lc = self.cfg.lifecycle
        while True:
            await asyncio.sleep(1)
            if self.paused or self.activity != "idle" or self.life in ("standby", "waking"):
                continue
            now = time.monotonic()
            if self.life == "active" and now > self.window_until:
                self.life = "warm_idle"
                self.listen_mode = "wake"
                self._refresh_ui()
            if not self.stay_awake and now - self.last_activity > lc.idle_timeout_s:
                await self.go_standby()

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    # ================================================================== screen / prewarm
    def current_system(self) -> str:
        return prompts.system_prompt(self.mode, self.screen.context_block(self.cfg.llm.max_screen_chars),
                                     self.memory_block)

    def on_screen_update(self) -> None:
        if self.orb:
            cur = self.screen.current
            reading = ", ".join(s.name for s in cur.screens.values()) or "nothing yet"
            self.orb.setToolTip(f"J.A.R.V.I.S: {self.status_text()}\nReading: {reading}\nFocused: {cur.app}"
                                + (f" | {cur.title[:60]}" if cur.title else "") + (" (hidden)" if cur.hidden else ""))
        if self.models_ready.is_set() and self.activity == "idle":
            self.schedule_prewarm()

    def _screen_key(self) -> tuple:
        cur = self.screen.current
        return (self.mode, self.memory_block, cur.app, cur.title, cur.hidden)

    def _matches_screen(self, key: tuple, lines: dict) -> bool:
        """True when a context built from (key, lines) still describes the screens well enough to reuse.
        Small changes (a clock, a scrolling log line) must not throw away the KV cache, but a real change
        on ANY display must, even when that display holds only a small share of the total text."""
        if key != self._screen_key():
            return False
        now = self.screen.current.lines_by_display()
        if set(now) != set(lines):
            return False
        limit = 1 - self.cfg.screen.reprewarm_change
        for did, new in now.items():
            old = lines[did]
            if (old or new) and len(old & new) / max(len(old | new), 1) < limit:
                return False
        return True

    def _close_enough(self) -> bool:
        return bool(self.prewarmed_system) and self._matches_screen(self._prewarmed_key, self._prewarmed_lines)

    def schedule_prewarm(self) -> None:
        if self._close_enough():
            return
        system = self.current_system()
        if system == self._prewarm_target:
            return
        if self._prewarm_task and not self._prewarm_task.done():
            self._prewarm_task.cancel()
        self._prewarm_target = system
        self._prewarm_task = asyncio.create_task(
            self._prewarm(system, self._screen_key(), self.screen.current.lines_by_display()))

    def system_for_question(self) -> str:
        """Reuse the prewarmed prompt when the screen has barely changed: only the question needs processing."""
        if self._close_enough():
            return self.prewarmed_system
        if (self._prewarm_task and not self._prewarm_task.done()
                and self._matches_screen(self._prewarm_key, self._prewarm_lines)):
            return self._prewarm_target  # still current: Ollama finishes it, then reuses it for the question
        return self.current_system()

    async def _prepare_for_question(self) -> None:
        """While you are still talking: let a running prewarm finish, then warm the GPU for speech-to-text."""
        if self._prewarm_task and not self._prewarm_task.done():
            await asyncio.wait({self._prewarm_task})
        await self.stt.rewarm()

    async def _prewarm(self, system: str, key: tuple, lines: dict) -> None:
        self._prewarm_key, self._prewarm_lines = key, lines
        try:
            await self.llm.prewarm(system)
            self.prewarmed_system, self._prewarmed_key, self._prewarmed_lines = system, key, lines
            await self.stt.rewarm()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("prewarm failed")
        finally:
            if self._prewarm_target == system:
                self._prewarm_target = ""

    # ================================================================== a question, end to end
    async def handle_turn(self, audio: np.ndarray, source: str, t_end: float) -> None:
        self._set_activity("thinking")
        times = {}
        speaker: asyncio.Task | None = None
        try:
            if not self.models_ready.is_set():
                await self.models_ready.wait()
            text = await self.stt.transcribe(audio)
            times["stt"] = time.monotonic() - t_end
            log.info("heard: %r (%.0f ms after you stopped)", text, times["stt"] * 1000)
            if router.is_stop(text):
                log.info("stop: %r", text)
                self.after_turn()
                return
            if source in ("barge-in", "follow-up") and self.mode != "quiz" and router.is_fragment(text):
                log.info("ignored fragment: %r", text)
                self.after_turn()
                return
            if len(text.strip(" .?!")) < 2 or (source == "follow-up" and self.mode != "quiz" and router.is_filler(text)):
                log.info("ignored: %r", text)
                self.after_turn()
                return
            if await self._command(text):
                return
            self.touch()
            note, moment = await self._moment_note(text)
            if self.panel:
                extra = []
                if moment.get("selection"):
                    extra.append(f"selection: {len(moment['selection'])} chars")
                if "UNDER THE MOUSE POINTER" in note:
                    extra.append("pointer context")
                self.panel.add_question(text, source + (f" · {', '.join(extra)}" if extra else ""))
            cur = self.screen.current
            visual = router.is_visual(text) and self.watcher.latest_image is not None and not cur.hidden
            system = self.system_for_question()
            if self._prewarm_task and not self._prewarm_task.done() and self._prewarm_target != system:
                self._prewarm_task.cancel()
            log.info("context: %s", "prewarmed (cache hit)" if system == self.prewarmed_system
                     else "prewarm in flight" if system == self._prewarm_target else "fresh (cache miss)")

            speak_q: asyncio.Queue = asyncio.Queue()
            speaker = asyncio.create_task(self._speaker(speak_q, t_end, times))
            if visual:
                await speak_q.put("One moment, sir.")
                stream = self.llm.vision(self._crop_near_pointer(moment), prompts.VISION_SYSTEM, text + note)
            else:
                n = self.cfg.llm.history_turns * 2
                stream = self.llm.chat(system, self.history[-n:], text + note)

            splitter, answer = SentenceSplitter(), ""
            limit, spoken, cut = self.cfg.tts.get("max_spoken_chars", 450), 0, False

            async def say(chunk: str) -> None:
                # Long answers: speak the first part, the rest stays in the transcript.
                nonlocal spoken, cut
                if cut:
                    return
                await speak_q.put(chunk)
                spoken += len(chunk)
                if spoken >= limit and chunk.rstrip().endswith((".", "!", "?")):
                    cut = True

            async for tok in stream:
                if "llm" not in times:
                    times["llm"] = time.monotonic() - t_end
                answer += tok
                if self.panel:
                    self.panel.append_answer(tok)
                for s in splitter.feed(tok):
                    await say(s)
            for s in splitter.flush():
                await say(s)
            if cut:
                await speak_q.put("The rest is in the transcript, sir.")
                if self.panel and not self.panel.isVisible():
                    self.panel.toggle(self.orb.geometry().center() if self.orb else None)
            if splitter.had_code:
                await speak_q.put("I've put the code in the transcript, sir.")
                if self.panel and not self.panel.isVisible():
                    self.panel.toggle(self.orb.geometry().center() if self.orb else None)
            await speak_q.put(None)
            await speaker

            self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": answer}]
            self.memory.add_turn("user", text, cur.app, cur.title, self.mode)
            self.memory.add_turn("assistant", answer, mode=self.mode)
            times["total"] = time.monotonic() - t_end
            meta = (f"{'vision' if visual else 'text'} · STT {times['stt'] * 1000:.0f} ms · "
                    f"first token {times.get('llm', 0) * 1000:.0f} ms · first audio {times.get('audio', 0) * 1000:.0f} ms"
                    f" · done {times['total']:.1f} s")
            log.info("latency: %s", meta)
            if self.panel:
                self.panel.set_meta(meta)
            self.after_turn()
        except asyncio.CancelledError:
            # Stop the speech task too, or a sentence already being synthesised is queued after the
            # interrupt and JARVIS carries on talking.
            if speaker is not None:
                speaker.cancel()
            self.player.stop()
            raise
        except Exception as e:
            log.exception("turn failed")
            if speaker is not None:
                speaker.cancel()
            self.player.stop()
            if self.panel:
                self.panel.note(f"Error: {e}")
            self.player.enqueue(chime("error"))
            self.after_turn()

    async def _speaker(self, q: asyncio.Queue, t_end: float, times: dict) -> None:
        while (sentence := await q.get()) is not None:
            audio = await asyncio.to_thread(self.tts.synth, sentence)
            if "audio" not in times:
                times["audio"] = time.monotonic() - t_end
                self._set_activity("speaking")
            self.player.enqueue(audio)
        await self.player.drain()

    async def _command(self, text: str) -> bool:
        cmd = router.command(text)
        if cmd is None:
            return False
        log.info("command: %s", cmd)
        if cmd == "stop":
            self.after_turn()
            return True
        if cmd == "standby":
            await self.go_standby()
            return True
        if cmd == "stay_awake":
            self.stay_awake = True
            reply = "Very well, sir. I shall stay awake."
        elif cmd == "pause":
            await self._say("Pausing, sir. Click me when you need me.")
            self.after_turn()
            self.toggle_pause()
            return True
        else:
            self.set_mode(cmd.split(":")[1])
            reply = f"{prompts.MODE_NAMES[self.mode]} mode, sir."
        await self._say(reply)
        self.after_turn()
        return True

    async def _say(self, text: str) -> None:
        self._set_activity("speaking")
        self.player.enqueue(await asyncio.to_thread(self.tts.synth, text))
        await self.player.drain()

    def after_turn(self) -> None:
        if self.life == "standby":
            return
        self.life = "active"
        self.window_until = time.monotonic() + self.cfg.lifecycle.conversation_window_s
        self.listen_mode = "follow"
        self._follow_hits = 0
        self.vad.reset()
        self._set_activity("idle")
        self.touch()
        if self.models_ready.is_set():
            asyncio.create_task(self.stt.rewarm())
            self.schedule_prewarm()

    def interrupt(self, resume: bool = True) -> None:
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()
        self.rec = None
        self.player.stop()
        if resume:
            self.after_turn()

    # ================================================================== UI actions
    def on_orb_click(self) -> None:
        if self.paused:
            self.toggle_pause()
        elif self.activity in ("speaking", "thinking"):
            self.interrupt()
        elif self.activity == "listening" and self.rec is not None:
            self._finish_recording()
        else:
            self.on_wake("click")

    def on_hold_start(self) -> None:
        if self.paused:
            return
        if self.activity in ("speaking", "thinking"):
            self.interrupt()
        cold = self.life == "standby"
        if cold:
            self.life = "waking"
            self._warm_task = asyncio.create_task(self.warm_up())
        self.touch()
        self._start_recording("push-to-talk", ptt=True)
        self.rec.skip = 0

    def on_hold_end(self) -> None:
        if self.rec is not None and self.rec.ptt:
            self._finish_recording()

    def on_stop_key(self) -> None:
        """Esc anywhere stops JARVIS while it is thinking or speaking (and does nothing otherwise)."""
        if self.activity in ("speaking", "thinking"):
            log.info("interrupted by Esc")
            self.interrupt()

    def toggle_panel(self) -> None:
        if self.panel:
            self.panel.toggle(self.orb.geometry().center() if self.orb else None)

    def toggle_orb(self) -> None:
        if self.orb:
            self.orb.setVisible(not self.orb.isVisible())

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.watcher.paused = self.paused
        if self.paused:
            self.interrupt(resume=False)
            self.activity = "idle"
            self.listen_mode = "wake"
        self._refresh_ui()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._refresh_ui()

    def set_fx(self, preset: str) -> None:
        self.fx_preset = preset
        self.tts.set_preset(preset)

    def quit(self) -> None:
        from PySide6.QtWidgets import QApplication
        self.mic.stop()
        self.player.close()
        asyncio.ensure_future(self.llm.unload()).add_done_callback(lambda _: QApplication.quit())

    # ================================================================== status
    def _set_activity(self, activity: str) -> None:
        self.activity = activity
        # OCR competes with speech-to-text and the LLM for the GPU and Neural Engine; the screen you
        # asked about was already read before you spoke, so pause reading until the answer is done.
        self.watcher.busy = activity != "idle"
        self._refresh_ui()

    def status_text(self) -> str:
        if self.paused:
            return "Paused"
        if self.activity != "idle":
            return self.activity.capitalize()
        return {"standby": "Standby", "waking": "Waking up", "active": "Listening for follow-ups",
                "warm_idle": "Ready (say 'Hey Jarvis')"}[self.life] + f" · {prompts.MODE_NAMES[self.mode]}"

    def orb_state(self) -> str:
        if self.paused:
            return "paused"
        if self.activity != "idle":
            return self.activity
        return {"standby": "standby", "waking": "thinking"}.get(self.life, "ready")

    def _refresh_ui(self) -> None:
        if self.orb:
            self.orb.set_state(self.orb_state())
        if self.panel:
            self.panel.set_status(self.status_text())
