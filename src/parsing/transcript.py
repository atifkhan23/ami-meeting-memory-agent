"""Deterministic transcript parser. No LLM involved.

File format (Catalist reformat of AMI manual transcripts):

    Meeting: TS3012a
    Team: TS3012
    Meeting number: 1 (a) of the team's four meetings
    ...header...

    00:00:02 Speaker A
    Okay, good morning. ...

Every turn = one header line "HH:MM:SS Speaker X" followed by one text line.
We keep the raw text untouched plus the character offsets of each turn's text in
the original file so that every chunk / citation is traceable to an exact location.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

MEETING_ID_RE = re.compile(r"^(?P<team>(?:ES|IS|TS)\d{4})(?P<stage>[a-d])$")
TURN_HEADER_RE = re.compile(r"^(?P<time>\d{2}:\d{2}:\d{2}) Speaker (?P<spk>[A-Z])\s*$")
STAGE_ORDER = {"a": 1, "b": 2, "c": 3, "d": 4}


class TranscriptParseError(ValueError):
    pass


@dataclass
class Turn:
    meeting_id: str
    turn_idx: int
    time: str          # HH:MM:SS from start of recording
    seconds: int
    speaker: str       # "A".."D"
    text: str          # verbatim text of the turn
    char_start: int    # offset of text in original file
    char_end: int

    @property
    def turn_id(self) -> str:
        return f"{self.meeting_id}#t{self.turn_idx}"


@dataclass
class Meeting:
    meeting_id: str
    team_id: str
    stage: str         # a/b/c/d
    order: int         # 1..4 within team
    path: str
    sha256: str
    raw_text: str
    turns: list[Turn] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return sum(len(t.text.split()) for t in self.turns)


def parse_meeting_id(meeting_id: str) -> tuple[str, str, int]:
    """'ES2008b' -> ('ES2008', 'b', 2). Raises on malformed ids."""
    m = MEETING_ID_RE.match(meeting_id)
    if not m:
        raise TranscriptParseError(f"Malformed meeting id: {meeting_id!r}")
    stage = m.group("stage")
    return m.group("team"), stage, STAGE_ORDER[stage]


def _to_seconds(t: str) -> int:
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


def parse_text(raw: str, meeting_id: str, path: str = "") -> Meeting:
    team_id, stage, order = parse_meeting_id(meeting_id)

    # Header cross-check (fail loudly if the file contradicts its filename)
    header_meeting = re.search(r"^Meeting: (\S+)", raw, re.M)
    header_team = re.search(r"^Team: (\S+)", raw, re.M)
    if header_meeting and header_meeting.group(1) != meeting_id:
        raise TranscriptParseError(f"{path}: header meeting {header_meeting.group(1)} != filename {meeting_id}")
    if header_team and header_team.group(1) != team_id:
        raise TranscriptParseError(f"{path}: header team {header_team.group(1)} != {team_id}")

    meeting = Meeting(
        meeting_id=meeting_id, team_id=team_id, stage=stage, order=order, path=path,
        sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(), raw_text=raw,
    )

    pos = 0
    pending = None  # (time, speaker)
    for line in raw.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        hm = TURN_HEADER_RE.match(stripped)
        if hm:
            pending = (hm.group("time"), hm.group("spk"))
        elif pending and stripped.strip():
            text = stripped
            meeting.turns.append(Turn(
                meeting_id=meeting_id, turn_idx=len(meeting.turns), time=pending[0],
                seconds=_to_seconds(pending[0]), speaker=pending[1], text=text,
                char_start=pos, char_end=pos + len(text),
            ))
            pending = None
        pos += len(line)

    if not meeting.turns:
        raise TranscriptParseError(f"{path}: no speaker turns found")
    return meeting


def parse_file(path: Path) -> Meeting:
    # newline="" keeps the exact bytes-as-text so char offsets match the file on disk
    with open(path, encoding="utf-8", newline="") as f:
        raw = f.read()
    return parse_text(raw, path.stem, str(path))
