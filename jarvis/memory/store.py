"""Conversation history and learning profile in SQLite. Screen contents are never stored."""

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY, ts REAL, role TEXT, text TEXT, app TEXT, title TEXT, mode TEXT
);
CREATE TABLE IF NOT EXISTS topics (
    name TEXT PRIMARY KEY, questions INTEGER DEFAULT 0, last_ts REAL
);
"""


class Memory:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def add_turn(self, role: str, text: str, app: str = "", title: str = "", mode: str = "") -> None:
        self.db.execute("INSERT INTO turns (ts, role, text, app, title, mode) VALUES (?,?,?,?,?,?)",
                        (time.time(), role, text, app, title, mode))
        if role == "user" and (title or app):
            topic = (title or app)[:120]
            self.db.execute("INSERT INTO topics (name, questions, last_ts) VALUES (?, 1, ?) "
                            "ON CONFLICT(name) DO UPDATE SET questions = questions + 1, last_ts = excluded.last_ts",
                            (topic, time.time()))
        self.db.commit()

    def profile_block(self) -> str:
        rows = self.db.execute("SELECT name, questions FROM topics ORDER BY last_ts DESC LIMIT 5").fetchall()
        if not rows:
            return ""
        lines = "\n".join(f"- {name} ({n} question{'s' if n != 1 else ''})" for name, n in rows)
        return "LEARNING PROFILE (what the user has recently studied with you):\n" + lines

    def first_wake_today(self) -> bool:
        start = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        return self.db.execute("SELECT COUNT(*) FROM turns WHERE ts >= ?", (start,)).fetchone()[0] == 0
