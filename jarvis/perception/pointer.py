"""What you are pointing at: the mouse position, the text under it, and any highlighted text.

Selected text comes from the macOS Accessibility API (AXSelectedText of the focused element), which
works in most native apps and many web views. When an app does not expose it, `copy_selection` sends
Cmd+C to that app and restores your clipboard afterwards. Both need Accessibility permission for the
app that launched JARVIS.
"""

import logging
import math
import time

import Quartz
from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString, NSWorkspace

from .capture import OWN_PID

log = logging.getLogger("jarvis.pointer")

C_KEY = 8  # macOS virtual key code for "c"


def location() -> tuple[float, float]:
    """Mouse position in global points, origin top-left of the main display (same as Quartz/Qt)."""
    p = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return (p.x, p.y)


def frontmost_pid() -> int | None:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    pid = app.processIdentifier() if app else None
    return None if pid == OWN_PID else pid


def selected_text(pid: int | None) -> str:
    """Highlighted text in that app's focused element, via Accessibility. "" if none or not exposed."""
    if pid is None:
        return ""
    try:
        from ApplicationServices import (AXUIElementCopyAttributeValue, AXUIElementCreateApplication,
                                         kAXFocusedUIElementAttribute, kAXSelectedTextAttribute)
        app = AXUIElementCreateApplication(pid)
        err, focused = AXUIElementCopyAttributeValue(app, kAXFocusedUIElementAttribute, None)
        if err or focused is None:
            return ""
        err, text = AXUIElementCopyAttributeValue(focused, kAXSelectedTextAttribute, None)
        return str(text).strip() if not err and text else ""
    except Exception:
        log.debug("AX selected text failed", exc_info=True)
        return ""


def copy_selection(timeout: float = 0.35) -> str:
    """Fallback for apps that hide their selection from Accessibility: press Cmd+C in the frontmost app,
    read the clipboard, then put your previous clipboard contents back exactly as they were."""
    if frontmost_pid() is None:
        return ""
    pb = NSPasteboard.generalPasteboard()
    saved = [{t: item.dataForType_(t) for t in item.types()} for item in (pb.pasteboardItems() or [])]
    before = pb.changeCount()
    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateCombinedSessionState)
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(src, C_KEY, down)
        Quartz.CGEventSetFlags(ev, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
    end = time.monotonic() + timeout
    while pb.changeCount() == before and time.monotonic() < end:
        time.sleep(0.02)
    text = ""
    if pb.changeCount() != before:
        text = str(pb.stringForType_(NSPasteboardTypeString) or "").strip()
        pb.clearContents()
        items = []
        for types in saved:
            item = NSPasteboardItem.alloc().init()
            for t, data in types.items():
                if data is not None:
                    item.setData_forType_(data, t)
            items.append(item)
        if items:
            pb.writeObjects_(items)
    return text


def text_near(boxes: list[tuple], point: tuple[float, float], radius_y: float = 90,
              radius_x: float = 420) -> tuple[str, str]:
    """(line under the pointer, text around it) from OCR boxes in global points (x0, y0, x1, y1, text)."""
    if not boxes:
        return "", ""
    px, py = point
    pad = 6

    def dist(b):
        dx = max(b[0] - px, 0, px - b[2])
        dy = max(b[1] - py, 0, py - b[3])
        return math.hypot(dx, dy)

    under = [b for b in boxes if b[0] - pad <= px <= b[2] + pad and b[1] - pad <= py <= b[3] + pad]
    if not under:
        nearest = min(boxes, key=dist)
        under = [nearest] if dist(nearest) <= 40 else []
    around = [b for b in boxes if abs((b[1] + b[3]) / 2 - py) <= radius_y
              and b[2] >= px - radius_x and b[0] <= px + radius_x]
    around.sort(key=lambda b: (round(b[1] / 8), b[0]))
    lines, row, last_y = [], [], None
    for b in around:
        y = round(b[1] / 8)
        if last_y is not None and y != last_y:
            lines.append("  ".join(row))
            row = []
        row.append(b[4])
        last_y = y
    if row:
        lines.append("  ".join(row))
    return " ".join(b[4] for b in under)[:300], "\n".join(lines)[:700]
