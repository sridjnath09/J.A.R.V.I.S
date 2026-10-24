"""Transcript panel: questions, answers (with code blocks), and per-question latency."""

import html
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication, QTextCursor
from PySide6.QtWidgets import QLabel, QTextBrowser, QVBoxLayout, QWidget

from . import macos

CSS = """
body { font-family: -apple-system, 'SF Pro Text', sans-serif; font-size: 13px; }
.q { color: #4aa3ff; font-weight: 600; margin-top: 10px; }
.a { margin: 4px 0 2px 0; }
.meta { color: #888; font-size: 11px; }
pre { background: rgba(127,127,127,0.15); padding: 8px; border-radius: 6px; font-family: Menlo, monospace; font-size: 12px; }
"""


class TranscriptPanel(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("J.A.R.V.I.S")
        self.resize(460, 560)
        self.status = QLabel("Standby")
        self.status.setStyleSheet("color: #888; padding: 2px 4px;")
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.document().setDefaultStyleSheet(CSS)
        self.view.setFont(QFont("SF Pro Text", 13))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.status)
        layout.addWidget(self.view)
        self._entries: list[dict] = []

    def showEvent(self, event) -> None:
        super().showEvent(event)
        macos.configure(self, floating=False)

    def toggle(self, near=None) -> None:
        if self.isVisible():
            self.hide()
            return
        if near is not None:
            area = QGuiApplication.primaryScreen().availableGeometry()
            x = max(area.left(), min(near.x() - self.width() - 12, area.right() - self.width()))
            y = max(area.top(), min(near.y() - self.height() // 2, area.bottom() - self.height()))
            self.move(x, y)
        self.show()
        self.raise_()

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def add_question(self, text: str, source: str) -> None:
        self._entries.append({"q": text, "src": source, "a": "", "meta": ""})
        self._render()

    def append_answer(self, text: str) -> None:
        if self._entries:
            self._entries[-1]["a"] += text
            self._render()

    def set_meta(self, text: str) -> None:
        if self._entries:
            self._entries[-1]["meta"] = text
            self._render()

    def note(self, text: str) -> None:
        self._entries.append({"q": "", "src": "", "a": text, "meta": ""})
        self._render()

    def _render(self) -> None:
        parts = []
        for e in self._entries[-30:]:
            if e["q"]:
                parts.append(f'<div class="q">You: {html.escape(e["q"])}</div>'
                             f'<div class="meta">{html.escape(e["src"])}</div>')
            parts.append(f'<div class="a">{_format_answer(e["a"])}</div>')
            if e["meta"]:
                parts.append(f'<div class="meta">{html.escape(e["meta"])}</div>')
        self.view.setHtml("".join(parts))
        self.view.moveCursor(QTextCursor.End)


def _format_answer(text: str) -> str:
    out = []
    for i, part in enumerate(re.split(r"```", text)):
        if i % 2:
            code = part.split("\n", 1)[1] if "\n" in part else part
            out.append(f"<pre>{html.escape(code.rstrip())}</pre>")
        else:
            out.append(html.escape(part).replace("\n", "<br>"))
    return "".join(out)
