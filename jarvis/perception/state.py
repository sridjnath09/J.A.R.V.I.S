import time
from collections import deque
from dataclasses import dataclass, field

from PIL import Image


@dataclass
class ScreenText:
    display_id: int
    name: str                 # "external display" / "built-in display"
    text: str = ""
    image: Image.Image | None = field(default=None, repr=False)
    ts: float = field(default_factory=time.time)


@dataclass
class Snapshot:
    """The focused window (app + title) and the OCR text of every display."""
    app: str = ""
    title: str = ""
    hidden: bool = False                       # focused app is on the privacy blocklist
    active_display: int | None = None
    screens: dict[int, ScreenText] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    @property
    def active(self) -> ScreenText | None:
        return self.screens.get(self.active_display)

    @property
    def image(self) -> Image.Image | None:
        return self.active.image if self.active else None

    def lines_by_display(self) -> dict[int, set[str]]:
        return {did: {l.strip() for l in s.text.splitlines() if len(l.strip()) > 3} for did, s in self.screens.items()}


class ScreenState:
    """What JARVIS currently sees, plus a short timeline. RAM only, never written to disk."""

    def __init__(self, timeline_len: int = 10):
        self.current = Snapshot()
        self.timeline: deque[tuple[float, str, str, str]] = deque(maxlen=timeline_len)

    def set_focus(self, app: str, title: str, hidden: bool, active_display: int | None) -> bool:
        cur = self.current
        if (cur.app, cur.title, cur.hidden, cur.active_display) == (app, title, hidden, active_display):
            return False
        if cur.app and (cur.app, cur.title) != (app, title):
            summary = "" if cur.hidden else _summary(cur.active.text if cur.active else "")
            self.timeline.append((cur.ts, cur.app, cur.title, summary))
        cur.app, cur.title, cur.hidden, cur.active_display, cur.ts = app, title, hidden, active_display, time.time()
        return True

    def set_screen(self, screen: ScreenText) -> None:
        self.current.screens[screen.display_id] = screen

    def drop_missing(self, display_ids: set[int]) -> None:
        for did in list(self.current.screens):
            if did not in display_ids:
                del self.current.screens[did]

    def context_block(self, max_chars: int) -> str:
        cur = self.current
        if not cur.screens:
            return "SCREENS: nothing captured yet."
        focus = f"FOCUSED WINDOW: {cur.app}" + (f" | {cur.title}" if cur.title else "")
        parts = [focus]
        ordered = sorted(cur.screens.values(), key=lambda s: s.display_id != cur.active_display)
        others = max(len(ordered) - 1, 1)
        for s in ordered:
            is_active = s.display_id == cur.active_display
            budget = int(max_chars * (0.65 if is_active and len(ordered) > 1 else 1.0 if is_active else 0.35 / others))
            head = f"SCREEN: {s.name}" + (" (has the focused window; the user is most likely looking here)" if is_active else "")
            if is_active and cur.hidden:
                body = "[hidden: the focused app is on the privacy blocklist; do not speculate about it]"
            else:
                text = s.text.strip()
                body = (text[:budget] + ("\n[...truncated]" if len(text) > budget else "")) if text else "[no readable text]"
            parts.append(f"{head}\n{body}")
        if self.timeline:
            recent = "\n".join(
                f"- {time.strftime('%H:%M', time.localtime(ts))} {app}" + (f" | {title}" if title else "")
                + (f" | {summary}" if summary else "")
                for ts, app, title, summary in list(self.timeline)[-5:]
            )
            parts.append("EARLIER WINDOWS (no longer necessarily on screen; mention them only if the user asks "
                         "about something they saw before):\n" + recent)
        return "\n\n".join(parts)


def _summary(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if len(line) > 20:
            return line[:100]
    return ""
