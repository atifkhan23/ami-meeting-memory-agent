"""Speaker-turn-aware chunking. Deterministic.

Rules:
* Chunks are built from whole speaker turns; a turn is never split, so every
  quote lies inside exactly one turn of exactly one chunk's source range.
* A chunk closes once it reaches CHUNK_TARGET_WORDS, BUT not right after a turn
  that ends with "?" (we keep consuming up to 2 more turns so a question stays
  with its answer), and never beyond CHUNK_MAX_WORDS unless a single turn is huge.
* Consecutive chunks overlap by CHUNK_OVERLAP_TURNS turns, so a decision and the
  explanation that precedes it usually co-occur in at least one chunk.
"""
from __future__ import annotations

from dataclasses import dataclass

import config
from src.parsing.transcript import Meeting, Turn


@dataclass
class Chunk:
    chunk_id: str
    meeting_id: str
    team_id: str
    stage: str
    order: int
    turn_start: int   # inclusive
    turn_end: int     # inclusive
    speakers: str     # e.g. "A,B,D"
    time_start: str
    time_end: str
    text: str         # rendered "[HH:MM:SS] Speaker X: ..." lines, verbatim turn text
    n_words: int


def render_turn(t: Turn) -> str:
    return f"[{t.time}] Speaker {t.speaker}: {t.text}"


def chunk_meeting(m: Meeting, target: int = config.CHUNK_TARGET_WORDS,
                  max_words: int = config.CHUNK_MAX_WORDS,
                  overlap: int = config.CHUNK_OVERLAP_TURNS) -> list[Chunk]:
    turns = m.turns
    chunks: list[Chunk] = []
    i = 0
    while i < len(turns):
        j = i
        words = 0
        extra_for_question = 0
        while j < len(turns):
            w = len(turns[j].text.split())
            if words and words + w > max_words:
                break
            words += w
            j += 1
            if words >= target:
                if turns[j - 1].text.rstrip().endswith("?") and extra_for_question < 2 and j < len(turns):
                    extra_for_question += 1
                    continue
                break
        sel = turns[i:j]
        chunks.append(Chunk(
            chunk_id=f"{m.meeting_id}-c{len(chunks):03d}",
            meeting_id=m.meeting_id, team_id=m.team_id, stage=m.stage, order=m.order,
            turn_start=sel[0].turn_idx, turn_end=sel[-1].turn_idx,
            speakers=",".join(sorted({t.speaker for t in sel})),
            time_start=sel[0].time, time_end=sel[-1].time,
            text="\n".join(render_turn(t) for t in sel),
            n_words=sum(len(t.text.split()) for t in sel),
        ))
        if j >= len(turns):
            break
        i = max(i + 1, j - overlap)  # guarantee progress
    return chunks
