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


STOP_WORD = re.compile(r"\b(stop|enough|quiet|shut up|hold on|never ?mind|cancel)\b", re.I)
ACK_WORDS = {"okay", "ok", "jarvis", "got", "it", "i", "thanks", "thank", "you", "understood", "that's", "thats",
             "fine", "all", "good", "great", "perfect", "cool", "alright", "right", "yes", "yeah", "sir", "nice",
             "there", "is", "now", "so", "oh", "ah", "um", "uh", "and", "get", "see"}


def is_stop(text: str) -> bool:
    """A short utterance that means "stop talking" or "I've got it", however it is phrased:
    "Stop, stop, stop. I got it.", "Judge stop." (a misheard "Jarvis, stop"), "Okay Jarvis, got it, got it"."""
    words = [w.lower() for w in re.findall(r"[\w']+", text)]
    if not words or "?" in text:
        return False
    if len(words) <= 10 and STOP_WORD.search(text):
        return True
    # Pure acknowledgement ("got it", "okay thanks"): every word is an acknowledgement word.
    return any(w in ("got", "thanks", "thank", "understood") for w in words) and all(w in ACK_WORDS for w in words)


DEICTIC = re.compile(r"\b(this|that|these|those|here|there|it|pointer|mouse|cursor|pointing|hover(ing)?)\b", re.I)


def points_at_something(question: str) -> bool:
    """"What is this?", "explain that line", "what's here" -> use the text under the mouse pointer."""
    return bool(DEICTIC.search(question))


def is_fragment(text: str) -> bool:
    """One or two words that are not a question ("This", "Okay, and now"): speech cut off, not a request."""
    words = re.findall(r"[\w']+", text)
    return len(words) <= 2 and "?" not in text


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
