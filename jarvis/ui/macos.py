"""macOS window tweaks through pyobjc: float over everything, follow every Space, stay out of screen capture."""

import logging

import objc
from AppKit import NSApplication

log = logging.getLogger("jarvis.ui")

NS_WINDOW_SHARING_NONE = 0
CAN_JOIN_ALL_SPACES = 1 << 0
STATIONARY = 1 << 4
IGNORES_CYCLE = 1 << 6
FULLSCREEN_AUXILIARY = 1 << 8
NS_STATUS_WINDOW_LEVEL = 25
NS_NONACTIVATING_PANEL = 1 << 7


def hide_dock_icon() -> None:
    NSApplication.sharedApplication().setActivationPolicy_(1)  # accessory: no Dock icon


def configure(widget, floating: bool = True) -> None:
    """Call after widget.show(). Excludes the window from screenshots so JARVIS never reads itself."""
    try:
        view = objc.objc_object(c_void_p=int(widget.winId()))
        win = view.window()
        win.setSharingType_(NS_WINDOW_SHARING_NONE)
        win.setHidesOnDeactivate_(False)
        if floating:
            # Clicking the orb must not activate JARVIS: the app you were in keeps focus and its selection.
            win.setStyleMask_(win.styleMask() | NS_NONACTIVATING_PANEL)
            win.setCollectionBehavior_(CAN_JOIN_ALL_SPACES | STATIONARY | IGNORES_CYCLE | FULLSCREEN_AUXILIARY)
            win.setLevel_(NS_STATUS_WINDOW_LEVEL)
    except Exception:
        log.exception("could not configure native window")
