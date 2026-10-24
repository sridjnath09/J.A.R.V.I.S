"""Background loop: watch every display, detect changes, OCR a display once it settles.

Change detection uses a cheap nominal-resolution grab; OCR uses a full-resolution grab of that display
with blocklisted apps' windows blacked out first.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import capture, ocr
from .state import ScreenState, ScreenText

log = logging.getLogger("jarvis.screen")

GRAB_TIMEOUT_S = 5.0  # macOS can block screen capture (e.g. after a permission change) instead of failing


@dataclass
class _Track:
    hash: np.ndarray | None = None
    last_change: float = 0.0
    pending: bool = True


class ScreenWatcher:
    def __init__(self, cfg, state: ScreenState, on_update: Callable[[], None]):
        self.cfg = cfg
        self.state = state
        self.on_update = on_update
        self.paused = False
        self.busy = False  # set while JARVIS is listening, thinking or speaking
        self.blocklist = {a.lower() for a in cfg.blocklist}
        self._tracks: dict[int, _Track] = {}
        self._stuck_warned = False

    @property
    def latest_image(self):
        return None if self.state.current.hidden else self.state.current.image

    def start(self) -> None:
        asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.cfg.interval_s)
            if self.paused or self.busy:
                continue
            try:
                await self._tick()
            except Exception:
                log.exception("screen watcher tick failed")

    async def _tick(self) -> None:
        win = await asyncio.to_thread(capture.frontmost_window)
        screens = await asyncio.to_thread(capture.displays)
        active = capture.window_display(win, screens)
        changed = False
        if win is not None:  # None = JARVIS itself has focus: keep the previous focus
            hidden = win.app.lower() in self.blocklist
            changed = self.state.set_focus(win.app, win.title, hidden, active.id if active else None)
        self.state.drop_missing({d.id for d in screens})

        now = time.monotonic()
        for d in screens:
            track = self._tracks.setdefault(d.id, _Track())
            small = await self._grab(d, full_res=False)
            if small is None:
                continue
            h = await asyncio.to_thread(capture.dhash, small)
            if capture.hash_distance(h, track.hash) > 3:
                track.hash, track.last_change, track.pending = h, now, True
                continue
            if track.pending and (now - track.last_change) * 1000 >= self.cfg.stable_ms:
                track.pending = False
                await self._read(d)
                changed = True
        if changed:
            self.on_update()

    async def _grab(self, d: capture.Display, full_res: bool):
        try:
            img = await asyncio.wait_for(asyncio.to_thread(capture.grab, d.bounds, full_res), GRAB_TIMEOUT_S)
            self._stuck_warned = False
            return img
        except asyncio.TimeoutError:
            if not self._stuck_warned:
                self._stuck_warned = True
                log.warning("Screen capture of the %s is not responding. Check System Settings > Privacy & "
                            "Security > Screen & System Audio Recording for the app that launched JARVIS "
                            "(e.g. Terminal), then quit and reopen that app.", d.name)
            return None

    async def _read(self, d: capture.Display) -> None:
        t0 = time.perf_counter()
        img = await self._grab(d, full_res=True)
        if img is None:
            return
        rects = await asyncio.to_thread(capture.blocked_rects, self.blocklist)
        img = capture.redact(img, d.bounds, rects)
        text = await asyncio.to_thread(ocr.recognize, img, self.cfg.ocr_level)
        self.state.set_screen(ScreenText(d.id, d.name, text, img))
        log.info("read %s: %d chars in %.0f ms%s", d.name, len(text), (time.perf_counter() - t0) * 1000,
                 f" ({len(rects)} blocked window(s) redacted)" if rects else "")
