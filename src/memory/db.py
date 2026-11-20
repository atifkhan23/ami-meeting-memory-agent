"""SQLite persistence: meetings, verbatim turns, chunks (+FTS5 BM25 index),
structured temporal memory records, ingest log. Deterministic, no LLM.

Why SQLite: single file, zero ops, transactional, FTS5 gives a persistent BM25
index with metadata filtering. At 10k+ meetings the same schema ports to Postgres
(tsvector / pgvector) without changing the agent code.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    meeting_id TEXT PRIMARY KEY, team_id TEXT NOT NULL, stage TEXT NOT NULL,
    meeting_order INTEGER NOT NULL, path TEXT, sha256 TEXT NOT NULL,
    n_turns INTEGER, n_words INTEGER, ingested_at REAL
);
CREATE INDEX IF NOT EXISTS idx_meetings_team ON meetings(team_id);

CREATE TABLE IF NOT EXISTS turns (
    meeting_id TEXT NOT NULL, turn_idx INTEGER NOT NULL, time TEXT, seconds INTEGER,
    speaker TEXT, text TEXT NOT NULL, char_start INTEGER, char_end INTEGER,
    PRIMARY KEY (meeting_id, turn_idx)
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL, team_id TEXT NOT NULL,
    stage TEXT, meeting_order INTEGER, turn_start INTEGER, turn_end INTEGER,
    speakers TEXT, time_start TEXT, time_end TEXT, text TEXT NOT NULL, n_words INTEGER
);
CREATE INDEX IF NOT EXISTS idx_chunks_team ON chunks(team_id);
CREATE INDEX IF NOT EXISTS idx_chunks_meeting ON chunks(meeting_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, chunk_id UNINDEXED, team_id UNINDEXED, meeting_id UNINDEXED,
    tokenize = 'porter unicode61'
);

CREATE TABLE IF NOT EXISTS memory_records (
    record_id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL, meeting_id TEXT NOT NULL, meeting_order INTEGER NOT NULL,
    type TEXT NOT NULL,          -- decision | action | commitment | disagreement | open_question | reference
    topic TEXT,                  -- normalised topic key used for temporal linking
    description TEXT NOT NULL,
    speaker TEXT, owner TEXT, deadline TEXT,
    status TEXT NOT NULL,        -- proposed|accepted|rejected|superseded|unresolved|completed|unknown
    raw_status TEXT,             -- status as first extracted, before reconciliation
    evidence_quote TEXT, evidence_turn INTEGER, chunk_id TEXT, quote_verified INTEGER,
    supersedes TEXT, superseded_by TEXT, related TEXT,  -- record ids (JSON list for related)
    is_current INTEGER DEFAULT 0,
    extracted_by TEXT, created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_mem_team ON memory_records(team_id, meeting_order);

CREATE TABLE IF NOT EXISTS extraction_runs (
    meeting_id TEXT PRIMARY KEY, sha256 TEXT, model TEXT, n_records INTEGER, finished_at REAL
);
CREATE TABLE IF NOT EXISTS reconcile_runs (
    team_id TEXT PRIMARY KEY, signature TEXT, model TEXT, finished_at REAL
);
CREATE TABLE IF NOT EXISTS memory_links (
    team_id TEXT, from_id TEXT, to_id TEXT, relation TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS speaker_roles (
    meeting_id TEXT, speaker TEXT, role TEXT, evidence_quote TEXT, evidence_turn INTEGER,
    PRIMARY KEY (meeting_id, speaker, role)
);
CREATE TABLE IF NOT EXISTS ingest_log (
    ts REAL, path TEXT, meeting_id TEXT, status TEXT, detail TEXT
);
"""


def connect(path: Path | str = config.SQLITE_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def log_ingest(conn, path, meeting_id, status, detail=""):
    conn.execute("INSERT INTO ingest_log VALUES (?,?,?,?,?)", (time.time(), str(path), meeting_id, status, detail))


def get_meeting_hash(conn, meeting_id) -> str | None:
    r = conn.execute("SELECT sha256 FROM meetings WHERE meeting_id=?", (meeting_id,)).fetchone()
    return r["sha256"] if r else None


def delete_meeting(conn, meeting_id):
    """Remove derived data for a meeting (used when a file changed and is re-ingested)."""
    conn.execute("DELETE FROM turns WHERE meeting_id=?", (meeting_id,))
    conn.execute("DELETE FROM chunks WHERE meeting_id=?", (meeting_id,))
    conn.execute("DELETE FROM chunks_fts WHERE meeting_id=?", (meeting_id,))
    conn.execute("DELETE FROM memory_records WHERE meeting_id=?", (meeting_id,))
    conn.execute("DELETE FROM extraction_runs WHERE meeting_id=?", (meeting_id,))
    conn.execute("DELETE FROM speaker_roles WHERE meeting_id=?", (meeting_id,))
    conn.execute("DELETE FROM reconcile_runs WHERE team_id=?", (meeting_id[:6],))  # team must re-reconcile
    conn.execute("DELETE FROM meetings WHERE meeting_id=?", (meeting_id,))


def team_meetings(conn, team_id) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM meetings WHERE team_id=? ORDER BY meeting_order", (team_id,)).fetchall()


def all_meeting_ids(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT meeting_id FROM meetings")}


def get_turn(conn, meeting_id, turn_idx):
    return conn.execute("SELECT * FROM turns WHERE meeting_id=? AND turn_idx=?", (meeting_id, turn_idx)).fetchone()


def get_turns(conn, meeting_id, start, end):
    return conn.execute("SELECT * FROM turns WHERE meeting_id=? AND turn_idx BETWEEN ? AND ? ORDER BY turn_idx",
                        (meeting_id, start, end)).fetchall()


def get_chunk(conn, chunk_id):
    return conn.execute("SELECT * FROM chunks WHERE chunk_id=?", (chunk_id,)).fetchone()


def records_for_team(conn, team_id, types: list[str] | None = None) -> list[dict]:
    q = "SELECT * FROM memory_records WHERE team_id=?"
    args: list = [team_id]
    if types:
        q += f" AND type IN ({','.join('?' * len(types))})"
        args += types
    q += " ORDER BY meeting_order, evidence_turn"
    rows = [dict(r) for r in conn.execute(q, args)]
    for r in rows:
        r["related"] = json.loads(r["related"]) if r.get("related") else []
    return rows


def stats(conn) -> dict:
    one = lambda q: conn.execute(q).fetchone()[0]
    return {
        "meetings": one("SELECT COUNT(*) FROM meetings"),
        "teams": one("SELECT COUNT(DISTINCT team_id) FROM meetings"),
        "turns": one("SELECT COUNT(*) FROM turns"),
        "words": one("SELECT COALESCE(SUM(n_words),0) FROM meetings"),
        "chunks": one("SELECT COUNT(*) FROM chunks"),
        "memory_records": one("SELECT COUNT(*) FROM memory_records"),
        "meetings_extracted": one("SELECT COUNT(*) FROM extraction_runs"),
        "teams_reconciled": one("SELECT COUNT(*) FROM reconcile_runs"),
        "ingest_errors": one("SELECT COUNT(*) FROM ingest_log WHERE status='error'"),
    }
