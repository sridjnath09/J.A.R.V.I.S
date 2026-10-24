"""Global hotkey via an AppKit event monitor (runs on the main thread, alongside Qt).

Needs Accessibility permission (System Settings > Privacy & Security > Accessibility).
"""

import logging

log = logging.getLogger("jarvis.ui")

KEYCODES = {"a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12,
            "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38,
            "k": 40, "n": 45, "m": 46, "space": 49}

_monitor = None  # keep a reference or the monitor is released


def register(spec: str, callback) -> bool:
    """spec like "<alt>+j" or "<cmd>+<shift>+k"."""
    global _monitor
    if not spec:
        return False
    try:
        from AppKit import (NSEvent, NSEventMaskKeyDown, NSEventModifierFlagCommand, NSEventModifierFlagControl,
                            NSEventModifierFlagOption, NSEventModifierFlagShift)
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

        mods = {"<alt>": NSEventModifierFlagOption, "<option>": NSEventModifierFlagOption,
                "<cmd>": NSEventModifierFlagCommand, "<ctrl>": NSEventModifierFlagControl,
                "<shift>": NSEventModifierFlagShift}
        parts = [p.strip().lower() for p in spec.split("+")]
        want = 0
        for p in parts[:-1]:
            want |= mods[p]
        code = KEYCODES[parts[-1]]
        mask = NSEventModifierFlagOption | NSEventModifierFlagCommand | NSEventModifierFlagControl | NSEventModifierFlagShift

        def handler(event):
            if event.keyCode() == code and (event.modifierFlags() & mask) == want:
                callback()

        if not AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}):
            log.warning("hotkey %s needs Accessibility permission; it will work after you grant it and restart", spec)
        _monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyDown, handler)
        return True
    except Exception:
        log.exception("could not register hotkey %s", spec)
        return False
