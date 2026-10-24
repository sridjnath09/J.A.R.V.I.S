"""The floating orb: JARVIS's main interface. Shows state at a glance; click to talk."""

import time

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from . import hud, macos

STATES = ("standby", "ready", "listening", "thinking", "speaking", "paused")


class Orb(QWidget):
    clicked = Signal()
    double_clicked = Signal()
    hold_started = Signal()
    hold_ended = Signal()
    context_menu = Signal(QPoint)

    def __init__(self, size: int = 64, level_source=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.orb = size
        self.margin = int(size * 0.35)  # room for the listening ripples
        side = size + 2 * self.margin
        self.setFixedSize(side, side)
        self.state = "standby"
        self.level_source = level_source  # callable -> float 0..1 (speaker loudness)
        self._t0 = time.monotonic()
        self._press_pos: QPoint | None = None
        self._dragging = False
        self._holding = False
        self._hold_timer = QTimer(self, singleShot=True, interval=450, timeout=self._on_hold)
        self._click_timer = QTimer(self, singleShot=True, interval=220, timeout=self.clicked.emit)
        self._anim = QTimer(self, interval=16, timeout=self.update)
        self._anim.start()
        self._settings = QSettings("JARVIS", "orb")
        self._restore_position()

    # ---- state ----------------------------------------------------------------------------
    def set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self._anim.setInterval(16 if state in ("listening", "thinking", "speaking") else 33)
            self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        macos.configure(self)

    # ---- painting -------------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        level = self.level_source() if self.level_source and self.state == "speaking" else 0.0
        hud.draw_hud(p, QPointF(self.width() / 2, self.height() / 2), self.orb / 2, self.margin,
                     time.monotonic() - self._t0, self.state, level)

    # ---- mouse: click / double-click / hold-to-talk / drag / right-click --------------------
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.RightButton:
            self.context_menu.emit(e.globalPosition().toPoint())
            return
        self._press_pos = e.globalPosition().toPoint()
        self._win_pos = self.pos()
        self._dragging = False
        self._hold_timer.start()

    def mouseMoveEvent(self, e) -> None:
        if self._press_pos is None or self._holding:
            return
        delta = e.globalPosition().toPoint() - self._press_pos
        if self._dragging or delta.manhattanLength() > 5:
            self._dragging = True
            self._hold_timer.stop()
            self.move(self._win_pos + delta)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.LeftButton or self._press_pos is None:
            return
        self._hold_timer.stop()
        self._press_pos = None
        if self._holding:
            self._holding = False
            self.hold_ended.emit()
        elif self._dragging:
            self._snap_to_edge()
        elif not self._click_timer.isActive():
            self._click_timer.start()  # wait briefly: this might become a double-click

    def mouseDoubleClickEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._click_timer.stop()
            self._hold_timer.stop()
            self._press_pos = None
            self.double_clicked.emit()

    def _on_hold(self) -> None:
        if self._press_pos is not None and not self._dragging:
            self._holding = True
            self.hold_started.emit()

    # ---- position ---------------------------------------------------------------------------
    def _snap_to_edge(self) -> None:
        screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x, y = self.x(), self.y()
        snap = 24
        if abs(x - area.left()) < snap:
            x = area.left()
        elif abs(area.right() - (x + self.width())) < snap:
            x = area.right() - self.width()
        if abs(y - area.top()) < snap:
            y = area.top()
        elif abs(area.bottom() - (y + self.height())) < snap:
            y = area.bottom() - self.height()
        self.move(x, y)
        self._settings.setValue("pos", self.pos())

    def _restore_position(self) -> None:
        pos = self._settings.value("pos")
        if isinstance(pos, QPoint) and QGuiApplication.screenAt(pos + QPoint(self.width() // 2, self.height() // 2)):
            self.move(pos)
        else:
            area = QGuiApplication.primaryScreen().availableGeometry()
            self.move(area.right() - self.width() - 16, area.bottom() - self.height() - 80)
