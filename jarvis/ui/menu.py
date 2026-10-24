"""The shared right-click / menu-bar menu and the tray icon."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QActionGroup, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..brain.prompts import MODE_NAMES
from ..voice.fx import PRESETS


def build_menu(app) -> QMenu:
    """`app` is the Jarvis orchestrator; actions call straight into it."""
    menu = QMenu()
    menu.aboutToShow.connect(lambda: _refresh(menu, app))

    menu.status = menu.addAction("Standby")
    menu.status.setEnabled(False)
    menu.addSeparator()
    menu.talk = menu.addAction("Talk", app.on_orb_click)
    menu.standby = menu.addAction("Stand by", app.request_standby)
    menu.pause = menu.addAction("Pause watching and listening", app.toggle_pause)
    menu.addSeparator()

    modes = menu.addMenu("Mode")
    menu.mode_group = QActionGroup(menu)
    for key, name in MODE_NAMES.items():
        a = modes.addAction(name, lambda k=key: app.set_mode(k))
        a.setCheckable(True)
        a.setData(key)
        menu.mode_group.addAction(a)

    voices = menu.addMenu("Voice effects")
    menu.fx_group = QActionGroup(menu)
    for key in ("off", *PRESETS):
        a = voices.addAction(key, lambda k=key: app.set_fx(k))
        a.setCheckable(True)
        a.setData(key)
        menu.fx_group.addAction(a)

    menu.addAction("Show transcript", app.toggle_panel)
    menu.addSeparator()
    menu.addAction("Quit J.A.R.V.I.S", app.quit)
    return menu


def _refresh(menu: QMenu, app) -> None:
    menu.status.setText(app.status_text())
    menu.pause.setText("Resume" if app.paused else "Pause watching and listening")
    for a in menu.mode_group.actions():
        a.setChecked(a.data() == app.mode)
    for a in menu.fx_group.actions():
        a.setChecked(a.data() == app.fx_preset)


def tray_icon(menu: QMenu) -> QSystemTrayIcon:
    pix = QPixmap(44, 44)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0))
    p.drawEllipse(6, 6, 32, 32)
    p.setBrush(QColor(0, 0, 0, 0))
    p.setCompositionMode(QPainter.CompositionMode_Clear)
    p.drawEllipse(17, 17, 10, 10)
    p.end()
    icon = QIcon(pix)
    icon.setIsMask(True)  # adapts to light / dark menu bar
    tray = QSystemTrayIcon(icon)
    tray.setContextMenu(menu)
    tray.setToolTip("J.A.R.V.I.S")
    tray.show()
    return tray
