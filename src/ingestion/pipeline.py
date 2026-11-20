"""Ingestion: discover -> hash -> parse -> chunk -> store (SQLite + FTS5) -> embed.

* Idempotent: a file whose sha256 matches the stored hash is skipped.
* Incremental: new files are added; changed files have their derived rows
  deleted and rebuilt (including memory records, which must be re-extracted).
* Failures are logged to ingest_log and do not stop the run.
No LLM is used here.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import config
from src.ingestion.chunker import chunk_meeting
from src.memory import db
from src.parsing.transcript import MEETING_ID_RE, TranscriptParseError, parse_file

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    discovered: int = 0
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    chunks_written: int = 0
    seconds: float = 0.0
    missing_meetings: dict = field(default_factory=dict)
    backfilled: int = 0

    def summary(self) -> dict:
        return {"discovered": self.discovered, "added": len(self.added), "updated": len(self.updated),
                "vectors_backfilled": self.backfilled,
                "skipped_unchanged": len(self.skipped), "errors": self.errors,
                "chunks_written": self.chunks_written, "seconds": round(self.seconds, 2),
                "missing_meetings": self.missing_meetings}


def discover(transcripts_dir: Path) -> list[Path]:
    return sorted(p for p in Path(transcripts_dir).glob("*.txt"))


def ingest(transcripts_dir: Path = config.TRANSCRIPTS_DIR, conn=None, vstore=None) -> IngestReport:
    t0 = time.time()
    conn = conn or db.connect()
    if vstore is None:
        from src.retrieval.vector_store import VectorStore
        vstore = VectorStore()
    rep = IngestReport()
    files = discover(transcripts_dir)
    rep.discovered = len(files)

    pending_vec: tuple[list, list, list] = ([], [], [])
    for path in files:
        mid = path.stem
        try:
            if not MEETING_ID_RE.match(mid):
                raise TranscriptParseError(f"filename is not a meeting id: {path.name}")
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            old = db.get_meeting_hash(conn, mid)
            if old == sha:
                rep.skipped.append(mid)
                continue
            m = parse_file(path)
            if old is not None:
                db.delete_meeting(conn, mid)
                vstore.delete_meeting(mid)
                rep.updated.append(mid)
            else:
                rep.added.append(mid)
            conn.execute("INSERT INTO meetings VALUES (?,?,?,?,?,?,?,?,?)",
                         (m.meeting_id, m.team_id, m.stage, m.order, str(path), sha,
                          len(m.turns), m.word_count, time.time()))
            conn.executemany("INSERT INTO turns VALUES (?,?,?,?,?,?,?,?)",
                             [(t.meeting_id, t.turn_idx, t.time, t.seconds, t.speaker, t.text,
                               t.char_start, t.char_end) for t in m.turns])
            chunks = chunk_meeting(m)
            conn.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             [(c.chunk_id, c.meeting_id, c.team_id, c.stage, c.order, c.turn_start,
                               c.turn_end, c.speakers, c.time_start, c.time_end, c.text, c.n_words)
                              for c in chunks])
            conn.executemany("INSERT INTO chunks_fts(text, chunk_id, team_id, meeting_id) VALUES (?,?,?,?)",
                             [(c.text, c.chunk_id, c.team_id, c.meeting_id) for c in chunks])
            for c in chunks:
                pending_vec[0].append(c.chunk_id)
                pending_vec[1].append(c.text)
                pending_vec[2].append({"team_id": c.team_id, "meeting_id": c.meeting_id,
                                       "stage": c.stage, "order": c.order})
            rep.chunks_written += len(chunks)
            db.log_ingest(conn, path, mid, "ok", f"{len(m.turns)} turns, {len(chunks)} chunks")
            conn.commit()
        except Exception as e:  # log and continue
            conn.rollback()
            log.exception("ingest failed for %s", path)
            db.log_ingest(conn, path, mid, "error", repr(e))
            conn.commit()
            rep.errors.append((path.name, repr(e)))

    if pending_vec[0]:
        log.info("embedding %d chunks with %s", len(pending_vec[0]), config.EMBEDDING_MODEL)
        vstore.upsert(*pending_vec)

    # Resumability: if a previous run crashed after the SQLite commit but before embedding,
    # some chunks have no vector. Detect and backfill them (SQLite is the source of truth).
    if vstore.count() != conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]:
        have = set(vstore.ids()) if hasattr(vstore, "ids") else set()
        missing = [r for r in conn.execute("SELECT * FROM chunks") if r["chunk_id"] not in have]
        if missing:
            log.info("backfilling %d chunks missing from the vector index", len(missing))
            vstore.upsert([r["chunk_id"] for r in missing], [r["text"] for r in missing],
                          [{"team_id": r["team_id"], "meeting_id": r["meeting_id"], "stage": r["stage"],
                            "order": r["meeting_order"]} for r in missing])
            rep.chunks_written += 0
            rep.backfilled = len(missing)

    # Coverage report: which teams are missing which stages (deterministic)
    by_team: dict[str, set] = {}
    for r in conn.execute("SELECT team_id, stage FROM meetings"):
        by_team.setdefault(r["team_id"], set()).add(r["stage"])
    rep.missing_meetings = {t: sorted(set("abcd") - s) for t, s in sorted(by_team.items()) if set("abcd") - s}
    rep.seconds = time.time() - t0
    return rep
