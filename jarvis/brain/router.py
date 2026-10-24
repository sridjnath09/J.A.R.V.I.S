"""Decides between the fast text path and the slower vision path, and spots voice commands."""

import re

VISUAL = re.compile(
    r"\b(chart|graph|diagram|picture|image|photo|plot|figure|icon|logo|colou?rs?|looks? like|layout|"
    r"design|drawing|map|screenshot|visual|visually|see in the)\b", re.I)


def is_visual(question: str) -> bool:
    return bool(VISUAL.search(question))


SELECTION = re.compile(r"\b(highlight(ed)?|select(ed|ion)?|this (text|word|line|sentence|paragraph|code|bit|part)|"
                       r"what i('ve| have)? (marked|selected|highlighted))\b", re.I)


def mentions_selection(question: str) -> bool:
    return bool(SELECTION.search(question))


FILLER = re.compile(r"^\s*(mm+[- ]?hmm+|hmm+|uh+[- ]?huh|uh+|um+|ah+|oh+|okay|ok|right|yeah|yes|no|"
                    r"thanks?|thank you|cool|nice|got it|alright)[\s.!?,]*$", re.I)


def is_filler(question: str) -> bool:
    """Back-channel sounds picked up in the follow-up window, not questions."""
    return bool(FILLER.match(question))


COMMANDS = [
    ("stop", re.compile(r"^\s*(hey\s+)?(jarvis,?\s*)?(stop( talking| it)?|wait|enough|that'?s enough|hold on|"
                        r"quiet|be quiet|shut up|never ?mind|cancel|ok(ay)? stop)[\s.!?,]*$", re.I)),
    ("standby", re.compile(r"^\s*(jarvis,?\s*)?(stand ?by|go to sleep|that'?s all|goodbye|good night)\b", re.I)),
    ("stay_awake", re.compile(r"^\s*(jarvis,?\s*)?stay awake\b", re.I)),
    ("pause", re.compile(r"^\s*(jarvis,?\s*)?(pause|stop watching)\b", re.I)),
    ("mode:teach", re.compile(r"^\s*(jarvis,?\s*)?(teach me mode|switch to teach)", re.I)),
    ("mode:quiz", re.compile(r"^\s*(jarvis,?\s*)?(quiz me|switch to quiz)", re.I)),
    ("mode:debug", re.compile(r"^\s*(jarvis,?\s*)?(debug mode|switch to debug)", re.I)),
    ("mode:explain", re.compile(r"^\s*(jarvis,?\s*)?(explain mode|normal mode|switch to explain)", re.I)),
]


def command(question: str) -> str | None:
    for name, pattern in COMMANDS:
        if pattern.search(question):
            return name
    return None
