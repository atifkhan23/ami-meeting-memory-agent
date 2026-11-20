"""Ingest-time structured memory extraction (LLM: cheap extraction model).

Why an LLM here: deciding whether "yeah let's just go with the rubber then" is a
decision, a suggestion or a joke, who owns "I'll look into the prices", and
whether a remark disagrees with an earlier one is language understanding that
regexes cannot do reliably.

What stays deterministic: segmenting the meeting, turn ids, meeting order,
verifying/snapping every evidence quote against the transcript, persistence,
and resumability (a meeting is skipped if already extracted for its sha256).

Each meeting is sent in ~2.5k-word segments (never the whole corpus), rendered
with turn ids so the model can point at evidence precisely.
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from src.citations.validator import snap_quote
from src.llm.client import LLMClient, LLMUnavailable, get_client
from src.memory import db

log = logging.getLogger(__name__)

SEGMENT_WORDS = 2200  # keeps prompt+max_tokens under Groq free-tier 8k TPM

SYSTEM = """You extract structured meeting memory from a real, messy meeting transcript (AMI corpus:
a team of four designing a TV remote control over meetings a-d). Speech has fillers and broken sentences.
Be precise and conservative: only extract what the transcript actually supports."""

PROMPT = """Meeting {meeting_id} (team {team_id}, meeting {stage} = #{order} of the team's meetings).
Transcript segment {seg_no}/{seg_total}. Each line is: t<turn number> <speaker letter>: text

{segment}

Extract memory items. Types:
- "decision": a choice the group makes or proposes about the product/process (materials, energy source,
  features, price, shape, colours, target group, components, budget cuts...).
- "action": a task someone is asked/agrees to do (owner = speaker letter doing it).
- "commitment": a promise a speaker makes ("I'll check...", "I will send...").
- "disagreement": a speaker objects to / argues against a proposal or another speaker.
- "open_question": an issue explicitly left unresolved or to be checked later.
- "reference": an explicit reference back to an earlier meeting/discussion or a figure (cost, price, total).
For decisions set status: "proposed" (suggested, not agreed), "accepted" (group agrees / PM confirms),
"rejected" (explicitly dropped/declined), "unknown". Do NOT mark a mere suggestion or question as accepted.
For actions/commitments: "unresolved" if open, "completed" if reported done in this segment.
For disagreements/open questions: "unresolved" unless resolved in this segment.

Also list speaker roles that THIS segment makes clear (self-introductions, "as the marketing expert I...",
someone presenting the role's standard presentation). Roles: Project Manager, Industrial Designer,
User Interface Designer, Marketing Expert.

Return JSON:
{{"items": [{{"type": "...", "topic": "short noun phrase, e.g. 'energy source', 'case material', 'LCD screen'",
  "description": "one sentence, include concrete values (numbers, materials, names)",
  "speaker": "A|B|C|D", "owner": "A|B|C|D|null", "deadline": "text or null", "status": "...",
  "turn": <turn number>, "quote": "6-30 words copied EXACTLY from that turn"}}],
 "roles": [{{"speaker": "A|B|C|D", "role": "...", "turn": <turn number>, "quote": "exact words showing it"}}]}}
Extract at most 25 items, prioritising decisions, changes of mind, figures and ownership."""


def _segments(turns: list, words: int = SEGMENT_WORDS) -> list[list]:
    segs, cur, n = [], [], 0
    for t in turns:
        cur.append(t)
        n += len(t["text"].split())
        if n >= words:
            segs.append(cur)
            cur, n = cur[-3:], 0  # small overlap for context
    if cur and (not segs or len(cur) > 3):
        segs.append(cur)
    return segs


def _render(turns) -> str:
    # compact rendering (no timestamps) keeps segments small enough for small-context fallbacks
    return "\n".join(f"t{t['turn_idx']} {t['speaker']}: {t['text']}" for t in turns)


def _ensure_roles_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS speaker_roles (meeting_id TEXT, speaker TEXT, role TEXT,
                    evidence_quote TEXT, evidence_turn INTEGER, PRIMARY KEY (meeting_id, speaker, role))""")


def extract_meeting(conn, meeting_id: str, llm: LLMClient | None = None, force=False) -> int:
    llm = llm or get_client()
    _ensure_roles_table(conn)
    m = conn.execute("SELECT * FROM meetings WHERE meeting_id=?", (meeting_id,)).fetchone()
    done = conn.execute("SELECT sha256 FROM extraction_runs WHERE meeting_id=?", (meeting_id,)).fetchone()
    if done and done["sha256"] == m["sha256"] and not force:
        return -1
    turns = [dict(r) for r in conn.execute("SELECT * FROM turns WHERE meeting_id=? ORDER BY turn_idx", (meeting_id,))]
    segs = _segments(turns)
    records, roles, models = [], [], set()
    for i, seg in enumerate(segs, 1):
        prompt = PROMPT.format(meeting_id=meeting_id, team_id=m["team_id"], stage=m["stage"],
                               order=m["meeting_order"], seg_no=i, seg_total=len(segs), segment=_render(seg))
        res = llm.complete(prompt, SYSTEM, chain=config.EXTRACTION_CHAIN, max_tokens=8000, task="extract")
        models.add(f"{res.provider}/{res.model}")
        data = res.data if isinstance(res.data, dict) else {"items": res.data or []}
        for it in data.get("items", []) or []:
            if not isinstance(it, dict) or not it.get("description"):
                continue
            records.append(it)
        roles += [r for r in data.get("roles", []) or [] if isinstance(r, dict)]

    conn.execute("DELETE FROM memory_records WHERE meeting_id=?", (meeting_id,))
    n = 0
    seen = set()
    for it in records:
        turn = it.get("turn")
        try:
            turn = int(str(turn).lstrip("t"))
        except (TypeError, ValueError):
            turn = None
        quote, qturn, _ = snap_quote(conn, meeting_id, str(it.get("quote") or ""), turn)
        key = (it.get("type"), (it.get("description") or "")[:60], qturn)
        if key in seen:
            continue
        seen.add(key)
        rid = f"{meeting_id}-r{n:03d}"
        chunk = None
        if qturn is not None:
            c = conn.execute("SELECT chunk_id FROM chunks WHERE meeting_id=? AND ? BETWEEN turn_start AND turn_end "
                             "ORDER BY chunk_id LIMIT 1", (meeting_id, qturn)).fetchone()
            chunk = c["chunk_id"] if c else None
        status = str(it.get("status") or "unknown").lower()
        if status not in {"proposed", "accepted", "rejected", "superseded", "unresolved", "completed", "unknown"}:
            status = "unknown"
        conn.execute("""INSERT INTO memory_records (record_id, team_id, meeting_id, meeting_order, type, topic,
                        description, speaker, owner, deadline, status, raw_status, evidence_quote, evidence_turn,
                        chunk_id, quote_verified, related, extracted_by, created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (rid, m["team_id"], meeting_id, m["meeting_order"], str(it.get("type", "unknown")).lower(),
                      (it.get("topic") or "").lower().strip(), it["description"], it.get("speaker"),
                      it.get("owner") if it.get("owner") not in ("null", "") else None,
                      it.get("deadline") if it.get("deadline") not in ("null", "") else None,
                      status, status, quote, qturn, chunk, int(quote is not None), "[]",
                      ",".join(sorted(models)), time.time()))
        n += 1
    for r in roles:
        q, qt, _ = snap_quote(conn, meeting_id, str(r.get("quote") or ""), None)
        if q and r.get("speaker") and r.get("role"):
            conn.execute("INSERT OR REPLACE INTO speaker_roles VALUES (?,?,?,?,?)",
                         (meeting_id, r["speaker"], r["role"], q, qt))
    conn.execute("INSERT OR REPLACE INTO extraction_runs VALUES (?,?,?,?,?)",
                 (meeting_id, m["sha256"], ",".join(sorted(models)), n, time.time()))
    conn.commit()
    return n


def extract_all(conn=None, llm=None, team_ids: list[str] | None = None, workers: int = 4) -> dict:
    """Resumable: meetings already extracted (same sha256) are skipped."""
    conn = conn or db.connect()
    llm = llm or get_client()
    q = "SELECT meeting_id FROM meetings"
    rows = [r[0] for r in conn.execute(q + " ORDER BY team_id, meeting_order")]
    if team_ids:
        rows = [r for r in rows if r[:6] in team_ids]
    out = {"extracted": 0, "skipped": 0, "failed": []}

    # LLM calls run in threads; DB writes are serialized through one connection per thread.
    def work(mid):
        c = db.connect()
        try:
            for attempt in range(3):  # all providers briefly down (503 burst / TPM window): wait, then retry
                try:
                    return mid, extract_meeting(c, mid, llm)
                except LLMUnavailable:
                    if attempt == 2:
                        raise
                    time.sleep(90)
        finally:
            c.close()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, mid): mid for mid in rows}
        for f in as_completed(futs):
            mid = futs[f]
            try:
                _, n = f.result()
                if n == -1:
                    out["skipped"] += 1
                else:
                    out["extracted"] += 1
                    log.info("extracted %s: %d records", mid, n)
            except LLMUnavailable as e:
                log.error("extraction failed for %s: %s", mid, e)
                out["failed"].append((mid, str(e)[:200]))
            except Exception as e:
                log.exception("extraction error %s", mid)
                out["failed"].append((mid, repr(e)[:200]))
    return out
