"""Deterministic citation validation and repair. No LLM in the exact-match path.

Matching rule mirrors the assessment checker: case and whitespace are ignored,
everything else (words, punctuation, fillers like "um") must match, and the
quote must lie inside ONE speaker turn and be >= MIN_QUOTE_WORDS words.

`snap_quote` repairs near-miss quotes produced by an LLM: it aligns the model's
quote to the most similar word span of the original turn and returns the
ORIGINAL transcript text for that span. The output therefore always consists of
transcript characters, never model characters. A minimum similarity threshold
stops it from "repairing" a paraphrase into an unrelated span.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher

import config
from src.parsing.transcript import MEETING_ID_RE

_WS = re.compile(r"\s+")
_WORD = re.compile(r"\S+")


def norm(s: str) -> str:
    return _WS.sub(" ", s).strip().lower()


def _word_key(w: str) -> str:
    return re.sub(r"[^\w']", "", w.lower())


@dataclass
class CitationCheck:
    meeting_id: str
    quote: str
    meeting_exists: bool = False
    team_ok: bool = False
    exact_match: bool = False
    single_turn: bool = False
    min_words_ok: bool = False
    turn_idx: int | None = None
    speaker: str | None = None
    repaired: bool = False
    error: str = ""

    @property
    def valid(self) -> bool:
        return all([self.meeting_exists, self.team_ok, self.exact_match, self.single_turn, self.min_words_ok])

    def to_dict(self):
        d = asdict(self)
        d["valid"] = self.valid
        return d


def find_quote_turn(conn, meeting_id: str, quote: str):
    """Return the turn row that contains quote (case/space-insensitive), else None."""
    nq = norm(quote)
    if not nq:
        return None
    for t in conn.execute("SELECT * FROM turns WHERE meeting_id=? ORDER BY turn_idx", (meeting_id,)):
        if nq in norm(t["text"]):
            return t
    return None


def quote_in_meeting_any(conn, meeting_id: str, quote: str) -> bool:
    """True if the quote occurs anywhere in the meeting even across turns (diagnostic only)."""
    full = " ".join(r["text"] for r in conn.execute(
        "SELECT text FROM turns WHERE meeting_id=? ORDER BY turn_idx", (meeting_id,)))
    return norm(quote) in norm(full)


def validate_citation(conn, meeting_id: str, quote: str, team_id: str | None = None) -> CitationCheck:
    c = CitationCheck(meeting_id=meeting_id, quote=quote)
    if not MEETING_ID_RE.match(meeting_id or ""):
        c.error = "malformed meeting id"
        return c
    row = conn.execute("SELECT team_id FROM meetings WHERE meeting_id=?", (meeting_id,)).fetchone()
    if not row:
        c.error = "meeting id not in corpus"
        return c
    c.meeting_exists = True
    c.team_ok = team_id is None or row["team_id"] == team_id
    if not c.team_ok:
        c.error = f"meeting belongs to {row['team_id']}, not {team_id}"
    c.min_words_ok = len(quote.split()) >= config.MIN_QUOTE_WORDS
    t = find_quote_turn(conn, meeting_id, quote)
    if t is not None:
        c.exact_match = c.single_turn = True
        c.turn_idx, c.speaker = t["turn_idx"], t["speaker"]
    elif quote_in_meeting_any(conn, meeting_id, quote):
        c.exact_match = True
        c.error = c.error or "quote spans more than one speaker turn"
    else:
        c.error = c.error or "quote not found verbatim in transcript"
    if not c.min_words_ok and not c.error:
        c.error = f"quote shorter than {config.MIN_QUOTE_WORDS} words"
    return c


def _best_span(turn_text: str, quote: str) -> tuple[float, str]:
    words = [(m.start(), m.end(), _word_key(m.group())) for m in _WORD.finditer(turn_text)]
    q = [_word_key(w) for w in quote.split()]
    q = [w for w in q if w]
    if not words or not q:
        return 0.0, ""
    keys = [w[2] for w in words]
    best = (0.0, 0, 0)
    n = len(q)
    for L in range(max(1, n - 3), n + 4):
        for s in range(0, max(1, len(words) - L + 1)):
            e = min(len(words), s + L)
            r = SequenceMatcher(None, keys[s:e], q, autojunk=False).ratio()
            if r > best[0]:
                best = (r, s, e)
    r, s, e = best
    if e <= s:
        return 0.0, ""
    return r, turn_text[words[s][0]:words[e - 1][1]]


def extend_quote(conn, meeting_id: str, quote: str, min_words: int = config.MIN_QUOTE_WORDS) -> str | None:
    """A verbatim quote that is too short (< min_words) is widened inside the SAME turn, preferring the
    words that follow it, until it is long enough. Output is transcript text; None if the turn is too short."""
    t = find_quote_turn(conn, meeting_id, quote)
    if t is None:
        return None
    words = [(m.start(), m.end()) for m in _WORD.finditer(t["text"])]
    if len(words) < min_words:
        return None
    keys = [_word_key(t["text"][a:b]) for a, b in words]
    q = [_word_key(w) for w in quote.split()]
    n = len(q)
    start = next((i for i in range(len(keys) - n + 1) if keys[i:i + n] == q), None)
    if start is None:
        return None
    s, e = start, start + n
    while e - s < min_words:
        if e < len(words):
            e += 1
        else:
            s -= 1
    return t["text"][words[s][0]:words[e - 1][1]]


def snap_quote(conn, meeting_id: str, quote: str, turn_idx: int | None = None,
               min_ratio: float = 0.8) -> tuple[str | None, int | None, float]:
    """Map an approximate quote to verbatim transcript text.

    Searches the hinted turn (and its neighbours) first, then the whole meeting.
    Returns (verbatim_text, turn_idx, similarity) or (None, None, best_ratio).
    """
    t = find_quote_turn(conn, meeting_id, quote)
    if t is not None:  # already exact: return the transcript's own casing/spacing
        r, span = _best_span(t["text"], quote)
        return (span if r == 1.0 else quote), t["turn_idx"], 1.0
    rows = conn.execute("SELECT * FROM turns WHERE meeting_id=? ORDER BY turn_idx", (meeting_id,)).fetchall()
    if turn_idx is not None:
        near = [r for r in rows if abs(r["turn_idx"] - turn_idx) <= 2]
        rows = near + [r for r in rows if abs(r["turn_idx"] - turn_idx) > 2]
    best = (0.0, None, None)
    qset = {_word_key(w) for w in quote.split()}
    for r in rows:
        # cheap prefilter: require some lexical overlap
        tset = {_word_key(w) for w in r["text"].split()}
        if len(qset & tset) < max(2, len(qset) // 3):
            continue
        ratio, span = _best_span(r["text"], quote)
        if ratio > best[0]:
            best = (ratio, span, r["turn_idx"])
        if ratio >= 0.97:
            break
    ratio, span, idx = best
    if ratio >= min_ratio and span and len(span.split()) >= config.MIN_QUOTE_WORDS:
        return span, idx, ratio
    return None, None, ratio
