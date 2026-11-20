"""Temporal decision model.

Split of responsibilities
-------------------------
LLM (reasoning model, compact input = extracted records only, never transcripts):
    * canonicalise topics ("power", "batteries", "energy source" -> "energy source")
    * propose typed links between records: supersedes | rejects | confirms | completes | refers_to
Deterministic code (this module, `apply_links`):
    * ordering by (meeting_order, turn) -- the ground truth of time
    * validating links (a record may only affect an EARLIER record of the same team)
    * the state machine below, and the `is_current` flag

State machine (per record)
--------------------------
    proposed --confirms(by accepted)--> accepted
    proposed --rejects-->               rejected
    accepted --supersedes(by accepted)->superseded   (superseded_by = newer id)
    accepted --rejects-->               rejected     (decision reversed, nothing replaced it)
    unresolved(action/commitment) --completes--> completed
A later *proposal* never supersedes an accepted decision: "latest statement wins"
is explicitly NOT the rule; only a later accepted decision or explicit rejection
changes the current state. History is never deleted -- superseded records stay
in the table with their evidence and the link to what replaced them.

Current decision for a topic = the latest accepted, non-superseded, non-rejected
decision record; ties broken by meeting order then turn.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time

import config
from src.llm.client import LLMClient, get_client
from src.memory import db

log = logging.getLogger(__name__)

SYSTEM = "You reconcile meeting-memory records over time for one design team. Be conservative and evidence-based."

PROMPT = """Team {team_id}. Below are memory records extracted from the team's meetings, in time order
(meeting a < b < c < d; within a meeting by turn). Format: id | meeting | type | status | topic | speaker | description

{records}

Tasks:
1. Give every record a canonical topic so the same subject shares one label across meetings
   (e.g. "battery", "power source", "energy" -> "energy source"). Keep labels short.
2. Propose links from a LATER record to an EARLIER record only, when the transcript evidence implies it:
   - "supersedes": later accepted decision replaces an earlier decision on the same topic with a different choice
   - "rejects": later record drops/declines an earlier proposal or decision
   - "confirms": later record agrees to / finalises an earlier proposal (same choice)
   - "completes": later record reports an earlier action/commitment as done (e.g. presents the result)
   - "refers_to": later record refers back to an earlier discussion without changing it
   Do not link records that are merely on the same topic. A suggestion or question does not supersede anything.

Return JSON: {{"topics": {{"<id>": "<canonical topic>", ...}},
 "links": [{{"from": "<later id>", "to": "<earlier id>", "relation": "...", "reason": "short"}}]}}"""

VALID_REL = {"supersedes", "rejects", "confirms", "completes", "refers_to"}


def _sort_key(r):
    return (r["meeting_order"], r["evidence_turn"] if r["evidence_turn"] is not None else 10**6, r["record_id"])


def apply_links(records: list[dict], topics: dict[str, str], links: list[dict]) -> list[dict]:
    """Pure function: returns updated copies of records. Deterministic, unit-tested."""
    recs = {r["record_id"]: dict(r, related=list(r.get("related") or []), supersedes=None,
                                 superseded_by=None, status=r.get("raw_status") or r["status"])
            for r in records}
    for rid, t in topics.items():
        if rid in recs and t:
            recs[rid]["topic"] = str(t).lower().strip()
    ordered = sorted(recs.values(), key=_sort_key)
    pos = {r["record_id"]: i for i, r in enumerate(ordered)}

    valid_links = []
    for ln in links:
        f, t, rel = ln.get("from"), ln.get("to"), ln.get("relation")
        if f not in recs or t not in recs or rel not in VALID_REL or f == t:
            continue
        if pos[f] <= pos[t]:          # time only flows forward
            continue
        # A replacement/confirmation must be about the same subject: if the LLM linked records whose
        # canonical topics differ, keep the association but do not let it change any status.
        if rel in ("supersedes", "confirms") and (recs[f].get("topic") or "") != (recs[t].get("topic") or ""):
            rel = "refers_to"
        valid_links.append((pos[f], f, t, rel))

    for _, f, t, rel in sorted(valid_links):   # apply in chronological order of the later record
        src, dst = recs[f], recs[t]
        if t not in src["related"]:
            src["related"].append(t)
        if f not in dst["related"]:
            dst["related"].append(f)
        if rel == "supersedes":
            if src["status"] == "accepted" and dst["status"] in ("accepted", "proposed"):
                dst["status"] = "superseded"
                dst["superseded_by"] = f
                src["supersedes"] = t
        elif rel == "rejects":
            if dst["status"] in ("proposed", "accepted", "unknown"):
                dst["status"] = "rejected"
                dst["superseded_by"] = f
        elif rel == "confirms":
            if dst["status"] == "proposed" and src["status"] == "accepted":
                dst["status"] = "accepted"
        elif rel == "completes":
            if dst["type"] in ("action", "commitment") and dst["status"] in ("unresolved", "unknown", "accepted", "proposed"):
                dst["status"] = "completed"

    # Within one topic, an older accepted decision that is still "accepted" when a newer accepted decision
    # with an explicit supersedes link exists is already handled. We do NOT auto-supersede without a link.
    # Current = the LATEST accepted decision per topic. Older accepted decisions on the same topic keep
    # status "accepted" (no evidence they were overturned) but are historical, not current.
    latest: dict[str, str] = {}
    for r in sorted(recs.values(), key=_sort_key):
        r["is_current"] = 0
        if r["type"] == "decision" and r["status"] == "accepted":
            latest[r.get("topic") or r["record_id"]] = r["record_id"]
    for rid in latest.values():
        recs[rid]["is_current"] = 1
    return sorted(recs.values(), key=_sort_key)


def reconcile_team(conn, team_id: str, llm: LLMClient | None = None, force=False) -> dict:
    llm = llm or get_client()
    recs = db.records_for_team(conn, team_id)
    if not recs:
        return {"team": team_id, "records": 0}
    sig = hashlib.sha256(json.dumps([(r["record_id"], r["description"], r["raw_status"]) for r in recs]).encode()).hexdigest()
    done = conn.execute("SELECT signature FROM reconcile_runs WHERE team_id=?", (team_id,)).fetchone()
    if done and done["signature"] == sig and not force:
        return {"team": team_id, "skipped": True}
    lines = [f"{r['record_id']} | {r['meeting_id']} | {r['type']} | {r['raw_status']} | {r['topic']} | "
             f"{r['speaker'] or '-'} | {r['description'][:150]}" for r in sorted(recs, key=_sort_key)]
    res = llm.complete(PROMPT.format(team_id=team_id, records="\n".join(lines)), SYSTEM,
                       chain=config.REASONING_CHAIN, max_tokens=8000, task="reconcile")
    data = res.data if isinstance(res.data, dict) else {}
    updated = apply_links(recs, data.get("topics") or {}, data.get("links") or [])
    for r in updated:
        conn.execute("""UPDATE memory_records SET topic=?, status=?, supersedes=?, superseded_by=?, related=?,
                        is_current=? WHERE record_id=?""",
                     (r["topic"], r["status"], r["supersedes"], r["superseded_by"], json.dumps(r["related"]),
                      r["is_current"], r["record_id"]))
    conn.execute("DELETE FROM memory_links WHERE team_id=?", (team_id,))
    conn.executemany("INSERT INTO memory_links VALUES (?,?,?,?,?)",
                     [(team_id, ln.get("from"), ln.get("to"), ln.get("relation"), (ln.get("reason") or "")[:300])
                      for ln in (data.get("links") or []) if isinstance(ln, dict)])
    conn.execute("INSERT OR REPLACE INTO reconcile_runs VALUES (?,?,?,?)",
                 (team_id, sig, f"{res.provider}/{res.model}", time.time()))
    conn.commit()
    n_links = len(data.get("links") or [])
    return {"team": team_id, "records": len(recs), "links_proposed": n_links, "model": res.model}


def decision_history(conn, team_id: str, topic_query: str | None = None, before_order: int | None = None) -> list[dict]:
    """Chronological decision timeline for a team (optionally a topic substring / cutoff meeting)."""
    recs = db.records_for_team(conn, team_id, ["decision"])
    if before_order:
        recs = [r for r in recs if r["meeting_order"] < before_order]
    if topic_query:
        words = [w for w in topic_query.lower().split() if len(w) > 2]
        recs = [r for r in recs if any(w in (r["topic"] or "") or w in r["description"].lower() for w in words)]
    return sorted(recs, key=_sort_key)


def current_decisions(conn, team_id: str) -> list[dict]:
    return [r for r in db.records_for_team(conn, team_id, ["decision"]) if r["is_current"]]


def reapply_team(conn, team_id: str) -> int:
    """Re-run the deterministic state machine from stored topics + links (no LLM). Used after rule changes."""
    recs = db.records_for_team(conn, team_id)
    links = [dict(r) for r in conn.execute(
        "SELECT from_id AS 'from', to_id AS 'to', relation FROM memory_links WHERE team_id=?", (team_id,))]
    updated = apply_links(recs, {r["record_id"]: r["topic"] for r in recs}, links)
    for r in updated:
        conn.execute("UPDATE memory_records SET status=?, supersedes=?, superseded_by=?, related=?, is_current=? "
                     "WHERE record_id=?", (r["status"], r["supersedes"], r["superseded_by"],
                                           json.dumps(r["related"]), r["is_current"], r["record_id"]))
    conn.commit()
    return len(updated)


def state_as_of(conn, team_id: str, before_order: int) -> list[dict]:
    """Replay the deterministic state machine using only meetings < before_order.

    Lets us answer "what was current going INTO meeting d" without leaking later
    meetings: same records, same stored links, filtered to the cutoff.
    """
    recs = [r for r in db.records_for_team(conn, team_id) if r["meeting_order"] < before_order]
    ids = {r["record_id"] for r in recs}
    topics = {r["record_id"]: r["topic"] for r in recs}
    links = [dict(r) for r in conn.execute(
        "SELECT from_id AS 'from', to_id AS 'to', relation FROM memory_links WHERE team_id=?", (team_id,))]
    links = [ln for ln in links if ln["from"] in ids and ln["to"] in ids]
    return apply_links(recs, topics, links)
