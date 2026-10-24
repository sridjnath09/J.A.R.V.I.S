"""Turns an LLM token stream into speakable chunks as early as possible.

Early chunks are cut at clause boundaries so speech starts sooner; later chunks at sentence ends.
Fenced code blocks are not spoken (they are shown in the transcript panel).
"""

import re

SENTENCE_END = re.compile(r"[.!?](?=\s)|\n")
CLAUSE_END = re.compile(r"[,;:—](?=\s)")


class SentenceSplitter:
    def __init__(self):
        self.buf = ""
        self.count = 0
        self.in_code = False
        self.had_code = False

    def feed(self, text: str) -> list[str]:
        self.buf += text
        out = []
        while True:
            if "```" in self.buf:
                before, _, after = self.buf.partition("```")
                if not self.in_code:
                    out += self._split(before, final=True)
                    self.had_code = True
                self.in_code = not self.in_code
                self.buf = after
                continue
            if self.in_code:
                return out
            chunk = self._take()
            if chunk is None:
                return out
            out.append(chunk)

    def flush(self) -> list[str]:
        if self.in_code:
            self.buf = ""
            return []
        rest, self.buf = self.buf, ""
        return [rest.strip()] if rest.strip() else []

    # Per chunk: (min chars before a clause cut, force a word-boundary cut beyond this length).
    # Kokoro needs ~0.3 s per second of audio, so short early chunks get the voice going quickly
    # and later chunks are synthesised while earlier ones play.
    LIMITS = [(3, 40), (20, 70), (60, 140)]

    def _take(self) -> str | None:
        clause_min, force_at = self.LIMITS[min(self.count, len(self.LIMITS) - 1)]
        m = SENTENCE_END.search(self.buf, 2)
        c = CLAUSE_END.search(self.buf, clause_min)
        if c and (m is None or c.start() < m.start()):
            m = c
        end = m.end() if m else None
        if end is None and len(self.buf) > force_at:
            space = self.buf.rfind(" ", 0, force_at)
            end = space if space > 0 else None
        if end is None:
            return None
        chunk, self.buf = self.buf[:end].strip(), self.buf[end:]
        if not chunk:
            return self._take()
        self.count += 1
        return chunk

    def _split(self, text: str, final: bool) -> list[str]:
        self.buf = text
        out = []
        while (c := self._take()) is not None:
            out.append(c)
        if final and self.buf.strip():
            out.append(self.buf.strip())
        self.buf = ""
        return out
