"""Frontmost-window capture at native (Retina) resolution via Quartz.

Windows with NSWindowSharingNone (JARVIS's own orb and panel) are excluded by macOS.
"""

import os
from dataclasses import dataclass

import numpy as np
import Quartz
from AppKit import NSWorkspace
from PIL import Image

OWN_PID = os.getpid()


@dataclass
class WindowInfo:
    app: str
    title: str
    pid: int
    bounds: tuple[float, float, float, float]  # x, y, w, h in global points

    @property
    def key(self) -> tuple:
        return (self.app, self.title)


def frontmost_window() -> WindowInfo | None:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return None
    pid = app.processIdentifier()
    name = app.localizedName() or "?"
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    for w in windows or []:
        if w.get("kCGWindowLayer", 1) != 0 or w.get("kCGWindowOwnerPID") != pid:
            continue
        b = w.get("kCGWindowBounds", {})
        if b.get("Width", 0) < 100 or b.get("Height", 0) < 100:
            continue
        return WindowInfo(name, w.get("kCGWindowName") or "", pid,
                          (b["X"], b["Y"], b["Width"], b["Height"]))
    # Frontmost app has no normal window (e.g. JARVIS itself, or the desktop): use the main display.
    if pid == OWN_PID:
        return None
    main = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    return WindowInfo(name, "", pid, (main.origin.x, main.origin.y, main.size.width, main.size.height))


@dataclass
class Display:
    id: int
    bounds: tuple[float, float, float, float]  # global points
    builtin: bool

    @property
    def name(self) -> str:
        return "built-in display" if self.builtin else "external display"

    def contains(self, x: float, y: float) -> bool:
        bx, by, bw, bh = self.bounds
        return bx <= x < bx + bw and by <= y < by + bh


def displays() -> list[Display]:
    err, ids, count = Quartz.CGGetActiveDisplayList(16, None, None)
    out = []
    for did in (ids or [])[:count]:
        r = Quartz.CGDisplayBounds(did)
        out.append(Display(int(did), (r.origin.x, r.origin.y, r.size.width, r.size.height),
                           bool(Quartz.CGDisplayIsBuiltin(did))))
    return out


def window_display(win: WindowInfo | None, screens: list[Display]) -> Display | None:
    if win is None or not screens:
        return screens[0] if screens else None
    x, y, w, h = win.bounds
    for d in screens:
        if d.contains(x + w / 2, y + h / 2):
            return d
    return screens[0]


def blocked_rects(blocklist: set[str]) -> list[tuple[float, float, float, float]]:
    """On-screen windows of blocklisted apps, wherever they are, so they can be blacked out before OCR."""
    rects = []
    for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []:
        if (w.get("kCGWindowOwnerName") or "").lower() in blocklist and w.get("kCGWindowLayer", 1) == 0:
            b = w.get("kCGWindowBounds", {})
            rects.append((b["X"], b["Y"], b["Width"], b["Height"]))
    return rects


def redact(img: Image.Image, origin: tuple[float, float, float, float], rects) -> Image.Image:
    if not rects:
        return img
    from PIL import ImageDraw
    ox, oy, ow, _ = origin
    scale = img.width / ow
    img = img.copy()
    draw = ImageDraw.Draw(img)
    for x, y, w, h in rects:
        draw.rectangle([(x - ox) * scale, (y - oy) * scale, (x - ox + w) * scale, (y - oy + h) * scale], fill="black")
    return img


def grab(bounds: tuple[float, float, float, float], full_res: bool = True) -> Image.Image | None:
    x, y, w, h = bounds
    res = Quartz.kCGWindowImageBestResolution if full_res else Quartz.kCGWindowImageNominalResolution
    cg = Quartz.CGWindowListCreateImage(
        Quartz.CGRectMake(x, y, w, h),
        Quartz.kCGWindowListOptionOnScreenOnly,
        Quartz.kCGNullWindowID,
        res | Quartz.kCGWindowImageBoundsIgnoreFraming,
    )
    if cg is None:
        return None
    width, height = Quartz.CGImageGetWidth(cg), Quartz.CGImageGetHeight(cg)
    bpr = Quartz.CGImageGetBytesPerRow(cg)
    data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(cg))
    return Image.frombuffer("RGBA", (width, height), bytes(data), "raw", "BGRA", bpr, 1).convert("RGB")


def dhash(img: Image.Image, size: int = 16) -> np.ndarray:
    """Difference hash: 256 bits that change when the visible content changes."""
    small = np.asarray(img.convert("L").resize((size + 1, size), Image.BILINEAR), dtype=np.int16)
    return (small[:, 1:] > small[:, :-1]).flatten()


def hash_distance(a: np.ndarray | None, b: np.ndarray | None) -> int:
    if a is None or b is None:
        return 1 << 16
    return int(np.count_nonzero(a != b))
