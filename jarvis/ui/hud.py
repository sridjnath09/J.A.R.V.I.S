"""Iron Man style HUD for the floating orb, drawn with QPainter (no image assets).

Layers, outside in: listening ripples, broken outer ring, rotating tick ring, amber accent arc,
segmented cyan band, amber dots, inner rings with a blueprint-style crosshair, and the glowing
"J.A.R.V.I.S." wordmark. Each state changes colour, brightness and how fast the rings turn.
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient

CYAN = (90, 220, 255)
BAND = (120, 200, 245)
AMBER = (255, 186, 48)
GREY = (150, 160, 168)

# per state: (colour scale 0..1, ring speed, band speed, saturated?)
STYLE = {
    "standby":   (0.45, 0.10, -0.05, True),
    "ready":     (0.85, 0.20, -0.10, True),
    "listening": (1.00, 0.35, -0.20, True),
    "thinking":  (1.00, 1.40, -2.20, True),
    "speaking":  (1.00, 0.30, -0.25, True),
    "paused":    (0.55, 0.00, 0.00, False),
}


def _c(rgb, alpha: float, sat: bool = True) -> QColor:
    if not sat:
        rgb = GREY
    return QColor(rgb[0], rgb[1], rgb[2], max(0, min(255, int(alpha * 255))))


def _arc(p: QPainter, c: QPointF, radius: float, start_deg: float, span_deg: float) -> None:
    rect = QRectF(c.x() - radius, c.y() - radius, 2 * radius, 2 * radius)
    p.drawArc(rect, int(start_deg * 16), int(span_deg * 16))


def draw_hud(p: QPainter, c: QPointF, r: float, margin: float, t: float, state: str, level: float = 0.0) -> None:
    p.setRenderHint(QPainter.Antialiasing)
    scale, ring_speed, band_speed, sat = STYLE.get(state, STYLE["ready"])
    if state == "standby":
        scale *= 0.8 + 0.2 * math.sin(t * 1.3)  # slow breathing
    a = lambda x: x * scale  # noqa: E731  alpha scaled by state brightness
    w = max(1.0, r / 40)    # base line width, scales with orb size

    # listening: ripples expanding beyond the disc
    if state == "listening":
        p.setBrush(Qt.NoBrush)
        for i in range(3):
            phase = (t * 0.9 + i / 3) % 1.0
            p.setPen(QPen(_c(CYAN, 0.6 * (1 - phase)), w * 1.2))
            rr = r + phase * margin * 0.95
            p.drawEllipse(c, rr, rr)

    # dark glass disc with a soft cyan glow at the rim
    g = QRadialGradient(c, r)
    g.setColorAt(0.0, QColor(6, 22, 32, 235))
    g.setColorAt(0.80, QColor(4, 16, 26, 235))
    g.setColorAt(0.94, _c(CYAN, a(0.18), sat))
    g.setColorAt(1.0, _c(CYAN, 0, sat))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawEllipse(c, r, r)
    p.setBrush(Qt.NoBrush)

    # blueprint crosshair, very faint
    p.setPen(QPen(_c(CYAN, a(0.10), sat), w * 0.6))
    p.drawLine(QPointF(c.x() - r * 0.9, c.y()), QPointF(c.x() + r * 0.9, c.y()))
    p.drawLine(QPointF(c.x(), c.y() - r * 0.9), QPointF(c.x(), c.y() + r * 0.9))

    # broken outer ring (three long arcs), slow rotation
    rot = t * 20 * ring_speed
    p.setPen(QPen(_c(CYAN, a(0.85), sat), w * 1.4, Qt.SolidLine, Qt.FlatCap))
    for start in (10, 130, 250):
        _arc(p, c, r * 0.96, start + rot, 95)
    p.setPen(QPen(_c(CYAN, a(0.35), sat), w * 0.8, Qt.SolidLine, Qt.FlatCap))
    for start in (112, 232, 352):
        _arc(p, c, r * 0.96, start + rot, 12)

    # tick ring, counter-rotating; every fifth tick longer
    tick_rot = -t * 12 * ring_speed
    for i in range(72):
        ang = math.radians(i * 5 + tick_rot)
        long = i % 6 == 0
        r1, r2 = r * (0.80 if long else 0.835), r * 0.885
        p.setPen(QPen(_c(CYAN, a(0.9 if long else 0.55), sat), w * (1.2 if long else 0.8)))
        p.drawLine(QPointF(c.x() + r1 * math.cos(ang), c.y() - r1 * math.sin(ang)),
                   QPointF(c.x() + r2 * math.cos(ang), c.y() - r2 * math.sin(ang)))

    # amber accent arc on the left, plus a short bracket
    amber_rot = rot * 0.5
    p.setPen(QPen(_c(AMBER, a(0.95), sat), w * 1.6, Qt.SolidLine, Qt.RoundCap))
    _arc(p, c, r * 0.775, 160 + amber_rot, 55)
    p.setPen(QPen(_c(AMBER, a(0.6), sat), w * 0.9, Qt.SolidLine, Qt.FlatCap))
    _arc(p, c, r * 0.745, 168 + amber_rot, 38)

    # segmented band: the bright blue sweep (speaking: grows with the voice)
    band_rot = t * 40 * band_speed
    span = 210 + (90 * min(1.0, level * 1.4) if state == "speaking" else 0)
    segments = 26
    seg = span / segments
    band_w = r * 0.15
    for i in range(segments):
        frac = i / segments
        alpha = a(0.35 + 0.65 * (1 - abs(frac - 0.55) * 1.4))
        p.setPen(QPen(_c(BAND, max(0.12, alpha), sat), band_w, Qt.SolidLine, Qt.FlatCap))
        _arc(p, c, r * 0.655, 30 + band_rot + i * seg, seg * 0.86)

    # amber dots riding just inside the band
    p.setPen(Qt.NoPen)
    p.setBrush(_c(AMBER, a(0.95), sat))
    for k in range(4):
        ang = math.radians(62 + k * 11 + band_rot * 0.6)
        p.drawEllipse(QPointF(c.x() + r * 0.56 * math.cos(ang), c.y() - r * 0.56 * math.sin(ang)), w * 1.1, w * 1.1)
    p.setBrush(Qt.NoBrush)

    # inner rings; while speaking the inner one pulses and radial bars follow the voice
    pulse = 1 + (0.06 * level if state == "speaking" else 0)
    p.setPen(QPen(_c(CYAN, a(0.9), sat), w * 1.3))
    p.drawEllipse(c, r * 0.52 * pulse, r * 0.52 * pulse)
    p.setPen(QPen(_c(CYAN, a(0.30), sat), w * 0.7))
    p.drawEllipse(c, r * 0.46, r * 0.46)
    if state == "speaking":
        bars = 40
        for i in range(bars):
            ang = math.radians(i * 360 / bars + t * 30)
            wob = 0.5 + 0.5 * math.sin(t * 11 + i * 1.9)
            h = r * (0.02 + 0.07 * level * wob)
            r1 = r * 0.47
            p.setPen(QPen(_c(CYAN, 0.85, sat), w))
            p.drawLine(QPointF(c.x() + r1 * math.cos(ang), c.y() - r1 * math.sin(ang)),
                       QPointF(c.x() + (r1 + h) * math.cos(ang), c.y() - (r1 + h) * math.sin(ang)))
    elif state == "thinking":
        p.setPen(QPen(_c(CYAN, 0.9, sat), w * 1.6, Qt.SolidLine, Qt.RoundCap))
        _arc(p, c, r * 0.49, -t * 400, 70)
        _arc(p, c, r * 0.49, -t * 400 + 180, 70)

    # wordmark with a glow
    _wordmark(p, c, r, a(1.0), sat, paused=state == "paused")


def _wordmark(p: QPainter, c: QPointF, r: float, alpha: float, sat: bool, paused: bool) -> None:
    text = "PAUSED" if paused else "J.A.R.V.I.S."
    font = QFont("Avenir Next", 10)
    font.setWeight(QFont.DemiBold)
    font.setLetterSpacing(QFont.PercentageSpacing, 108)
    font.setPixelSize(max(7, int(r * (0.19 if not paused else 0.16))))
    path = QPainterPath()
    path.addText(0, 0, font, text)
    box = path.boundingRect()
    path.translate(c.x() - box.center().x(), c.y() - box.center().y())
    p.setBrush(Qt.NoBrush)
    for width, glow in ((r * 0.07, 0.10), (r * 0.035, 0.22)):  # soft cyan halo
        p.setPen(QPen(_c(CYAN, alpha * glow, sat), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(235, 250, 255, int(255 * max(0.35, alpha))) if sat else QColor(200, 205, 210, 200))
    p.drawPath(path)
    p.setBrush(Qt.NoBrush)
