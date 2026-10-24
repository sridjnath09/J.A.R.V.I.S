"""Apple Vision OCR, returning text in layout-aware reading order.

Screens are multi-pane (sidebar | editor | chat). Grouping boxes into rows across the whole screen
interleaves the panes ("EXPLORER  env  New session  JARVIS plan"). Instead, a recursive XY-cut splits
the page along the widest empty gutter (vertical or horizontal), so each pane is read top to bottom
on its own, and panes are separated by a blank line.
"""

from ocrmac import ocrmac
from PIL import Image

MIN_COL_GAP = 14     # px: an empty vertical strip at least this wide separates panes / columns
MIN_ROW_GAP = 6      # px: an empty horizontal strip at least this tall separates blocks
PANE_GAP = 24        # px: column gaps at least this wide are marked with a blank line in the output


def recognize(img: Image.Image, level: str = "accurate") -> str:
    # Vision is accurate up to ~3000 px; larger Retina captures only cost time.
    if img.width > 3000:
        img = img.resize((3000, int(img.height * 3000 / img.width)), Image.BILINEAR)
    items = ocrmac.OCR(img, recognition_level=level, language_preference=["en-US"]).recognize()
    if not items:
        return ""
    w, h = img.size
    # bbox = (x, y, bw, bh), normalised, origin bottom-left -> pixel boxes, origin top-left
    boxes = [(b[0] * w, (1 - b[1] - b[3]) * h, (b[0] + b[2]) * w, (1 - b[1]) * h, text)
             for text, _conf, b in items if text.strip()]
    return _xy_cut(boxes).strip()


def _gaps(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Empty intervals between the union of spans: (start, end) of each gap."""
    spans = sorted(spans)
    gaps, reach = [], spans[0][1]
    for a, b in spans[1:]:
        if a > reach:
            gaps.append((reach, a))
        reach = max(reach, b)
    return gaps


def _xy_cut(boxes: list[tuple], depth: int = 0) -> str:
    if len(boxes) <= 1 or depth > 40:
        return _rows(boxes)
    col_gaps = [g for g in _gaps([(b[0], b[2]) for b in boxes]) if g[1] - g[0] >= MIN_COL_GAP]
    row_gaps = [g for g in _gaps([(b[1], b[3]) for b in boxes]) if g[1] - g[0] >= MIN_ROW_GAP]
    best_col = max(col_gaps, key=lambda g: g[1] - g[0], default=None)
    best_row = max(row_gaps, key=lambda g: g[1] - g[0], default=None)
    if best_col is None and best_row is None:
        return _rows(boxes)
    col_w = best_col[1] - best_col[0] if best_col else -1
    row_h = best_row[1] - best_row[0] if best_row else -1
    # A real pane gutter wins over a blank band: blank bands often run across two panes that happen
    # to have whitespace at the same height, and cutting there would split a sidebar in two.
    if col_w >= PANE_GAP or col_w >= row_h:  # split into left | right panes
        cut = (best_col[0] + best_col[1]) / 2
        left = [b for b in boxes if b[2] <= cut]
        right = [b for b in boxes if b[0] >= cut]
        sep = "\n\n" if col_w >= PANE_GAP else "  "
        if _single_row(boxes):
            sep = "  "  # gaps inside one line of text are word gaps, not panes
        return _join(_xy_cut(left, depth + 1), _xy_cut(right, depth + 1), sep)
    cut = (best_row[0] + best_row[1]) / 2  # split into top / bottom blocks
    top = [b for b in boxes if b[3] <= cut]
    bottom = [b for b in boxes if b[1] >= cut]
    return _join(_xy_cut(top, depth + 1), _xy_cut(bottom, depth + 1), "\n")


def _single_row(boxes: list[tuple]) -> bool:
    top = min(b[1] for b in boxes)
    bottom = max(b[3] for b in boxes)
    tallest = max(b[3] - b[1] for b in boxes)
    return bottom - top <= tallest * 1.5


def _join(a: str, b: str, sep: str) -> str:
    a, b = a.strip("\n"), b.strip("\n")
    return f"{a}{sep}{b}" if a and b else a or b


def _rows(boxes: list[tuple]) -> str:
    """Group boxes with overlapping vertical extent into lines, left to right."""
    lines: list[list[tuple]] = []
    for box in sorted(boxes, key=lambda b: (b[1], b[0])):
        mid = (box[1] + box[3]) / 2
        if lines and lines[-1][0][1] <= mid <= lines[-1][0][3]:
            lines[-1].append(box)
        else:
            lines.append([box])
    return "\n".join("  ".join(b[4] for b in sorted(line, key=lambda b: b[0])) for line in lines)
