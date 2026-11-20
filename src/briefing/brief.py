"""Pre-meeting brief generator.

"The brief Team TS3012 should read before their final meeting" => the brief is
built AS OF the start of the final meeting: only meetings before it are used
(for TS3012: a, b, c). The temporal state is replayed deterministically at that
cutoff (`state_as_of`), so nothing said in meeting d can leak into the brief.

Pipeline: structured memory (code) + targeted hybrid retrieval per section (code)
-> LLM writes section items, each with cited turn ids -> every citation is
snapped/validated (code) -> items with no valid citation are dropped and counted.
"""
from __future__ import annotations

import json
import logging

import config
from src.citations.validator import snap_quote, validate_citation
from src.llm.client import get_client
from src.memory import db
from src.memory.temporal import state_as_of
from src.retrieval.hybrid import HybridRetriever

log = logging.getLogger(__name__)

SECTIONS = [
    ("current_decisions", "Current decisions", "what is agreed / the current direction of the product"),
    ("decision_history", "What changed along the way", "decisions that changed between meetings, old vs new and why"),
    ("completed_work", "Completed work", "work already done / presented"),
    ("open_actions", "Open actions and owners", "tasks still to do for the final meeting and who owns them"),
    ("disagreements", "Open disagreements", "unresolved disagreements, with each side's position"),
    ("context", "Context to remember", "constraints, budget, requirements, commitments, concerns raised earlier"),
]

SECTION_QUERIES = {
    "current_decisions": ["we decided agreed final choice", "energy source battery", "case material rubber plastic",
                          "buttons scroll wheel LCD", "colour shape design", "price budget twelve fifty"],
    "decision_history": ["changed instead now decided not anymore", "too expensive cut drop", "compared to last meeting"],
    "completed_work": ["prototype model presentation finished", "I looked into researched found"],
    "open_actions": ["next meeting you will", "your task homework prepare", "evaluation costs final"],
    "disagreements": ["I don't agree but", "I don't think that's a good idea", "not sure about"],
    "context": ["requirements teletext only television corporate colour", "budget production cost limit",
                "user research survey young people", "trendwatching fashion"],
}

SYSTEM = """You write a concise pre-meeting brief for a product design team from verified meeting memory.
Only state what the evidence shows. Every item must cite 1-2 quotes copied EXACTLY from one evidence line
each (>= 6 words). Speaker letters are per meeting; give roles only when the role table supports them.
Separate fact from inference: inferred items must start with "Inference:"."""

PROMPT = """Team {team}. The brief is for the start of meeting {next_stage} (their final meeting).
Use ONLY meetings {used}. Meeting order: {used} (later overrides earlier).

SPEAKER ROLES:
{roles}

TEMPORAL MEMORY STATE as of meeting {next_stage} (deterministically reconciled; status in brackets):
{memory}

TRANSCRIPT EVIDENCE:
{evidence}

QUOTING RULE: citation quotes must be copied from TRANSCRIPT EVIDENCE lines or from the 'evidence' part of a
memory line - never from a memory 'summary' (those are paraphrases and will be rejected by the verifier).

Write the brief sections:
{sections}

Return JSON: {{"sections": {{"<section key>": [{{"text": "one or two sentences", "owner": "Speaker X (role) or null",
  "citations": [{{"meeting_id": "...", "turn": <n>, "quote": "exact words"}}]}}]}},
  "priorities": ["3-5 recommended priorities for the final meeting (recommendations, not facts)"]}}
3-6 items per section; skip a section item rather than guess. Do not invent owners or deadlines."""


def build_brief(team: str = "TS3012", conn=None, llm=None, retriever=None) -> dict:
    conn = conn or db.connect()
    llm = llm or get_client()
    retriever = retriever or HybridRetriever(conn)
    meetings = db.team_meetings(conn, team)
    final_order = max(m["meeting_order"] for m in meetings)
    used = [m["meeting_id"] for m in meetings if m["meeting_order"] < final_order]
    next_stage = "abcd"[final_order - 1]

    state = state_as_of(conn, team, final_order)
    mem_lines = []
    for r in state:
        tag = r["status"] + (f", replaced by {r['superseded_by']}" if r.get("superseded_by") else "")
        owner = f" owner={r['owner']}" if r.get("owner") else ""
        ev = (f' | evidence [{r["meeting_id"]} t{r["evidence_turn"]}]: "{r["evidence_quote"]}"'
              if r.get("evidence_quote") else "")
        mem_lines.append(f"{r['record_id']} [{r['meeting_id']}] {r['type']} [{tag}] topic={r['topic']} "
                         f"speaker={r['speaker']}{owner} | summary (NOT quotable): {r['description']}{ev}")

    # Retrieval per section, restricted to the meetings before the final one
    chosen: dict[str, set[int]] = {}
    for key, qs in SECTION_QUERIES.items():
        for q in qs:
            for h in retriever.search(q, team_id=team, k=4):
                if h.meeting_id in used:
                    chosen.setdefault(h.meeting_id, set()).update(range(h.turn_start, h.turn_end + 1))
    for r in state:
        if r.get("evidence_turn") is not None:
            chosen.setdefault(r["meeting_id"], set()).update(range(max(0, r["evidence_turn"] - 1), r["evidence_turn"] + 2))
    lines, budget, used_words = [], int(14000 / 1.35), 0
    for mid in used:
        idxs = sorted(chosen.get(mid, []))
        if not idxs:
            continue
        lines.append(f"=== {mid} ===")
        for t in db.get_turns(conn, mid, idxs[0], idxs[-1]):
            if t["turn_idx"] in chosen[mid] and used_words < budget:
                lines.append(f"[{mid} t{t['turn_idx']} {t['time']}] Speaker {t['speaker']}: {t['text']}")
                used_words += len(t["text"].split())

    roles = conn.execute("SELECT * FROM speaker_roles WHERE meeting_id IN (%s) ORDER BY meeting_id, speaker"
                         % ",".join("?" * len(used)), used).fetchall()
    prompt = PROMPT.format(team=team, next_stage=next_stage, used=", ".join(used),
                           roles="\n".join(f"{r['meeting_id']}: Speaker {r['speaker']} = {r['role']}" for r in roles),
                           memory="\n".join(mem_lines), evidence="\n".join(lines),
                           sections="\n".join(f"- {k}: {desc}" for k, _, desc in SECTIONS))
    res = llm.complete(prompt, SYSTEM, max_tokens=8000, task="brief")
    data = res.data if isinstance(res.data, dict) else {}

    out_sections, dropped, total_cites = {}, [], 0
    for key, title, _ in SECTIONS:
        items = []
        for it in (data.get("sections") or {}).get(key, []) or []:
            if not isinstance(it, dict):
                continue
            cites = []
            for c in it.get("citations") or []:
                mid = str(c.get("meeting_id", ""))
                if mid not in used:   # no leakage from the final meeting / other teams
                    continue
                try:
                    turn = int(str(c.get("turn")).lstrip("t"))
                except (TypeError, ValueError):
                    turn = None
                q, _, _ = snap_quote(conn, mid, str(c.get("quote", "")), turn)
                chk = validate_citation(conn, mid, q or str(c.get("quote", "")), team)
                if chk.valid:
                    cites.append({"meeting_id": mid, "quote": chk.quote, "speaker": chk.speaker})
            if cites:
                items.append({"text": it.get("text", ""), "owner": it.get("owner"), "citations": cites})
                total_cites += len(cites)
            else:
                dropped.append({"section": key, "text": it.get("text", "")})
        out_sections[key] = items
    return {"team": team, "as_of": f"before meeting {next_stage}", "meetings_used": used,
            "sections": out_sections, "priorities": data.get("priorities", []), "dropped_uncited": dropped,
            "n_citations": total_cites, "model": f"{res.provider}/{res.model}"}


def render_markdown(b: dict) -> str:
    md = [f"# Pre-meeting brief: Team {b['team']} ({b['as_of']})", "",
          f"_Built only from meetings {', '.join(b['meetings_used'])}. Every bullet is a fact backed by verbatim, "
          f"programmatically verified quotes [meeting id: \"quote\"] unless marked Inference or Recommendation. "
          f"Speaker letters are per-meeting transcript labels._", ""]
    for key, title, _ in SECTIONS:
        md.append(f"## {title}")
        items = b["sections"].get(key) or []
        if not items:
            md.append("- (nothing supported by verified evidence)")
        for it in items:
            cites = "; ".join(f'[{c["meeting_id"]}, Speaker {c["speaker"]}: "{c["quote"]}"]' for c in it["citations"])
            owner = f" **Owner:** {it['owner']}." if it.get("owner") and it["owner"] != "null" else ""
            md.append(f"- {it['text']}{owner} {cites}")
        md.append("")
    md.append("## Suggested priorities for the final meeting (Recommendation, not fact)")
    md += [f"{i}. {p}" for i, p in enumerate(b.get("priorities") or [], 1)]
    if b.get("dropped_uncited"):
        md += ["", f"_{len(b['dropped_uncited'])} draft item(s) were removed because none of their quotes could be verified._"]
    return "\n".join(md) + "\n"


def render_plain(b: dict) -> str:
    """Plain-text version for answers.json 'brief'."""
    # NB: never strip "_" globally -- transcripts spell acronyms as "L_C_D_" inside quotes.
    lines = []
    for ln in render_markdown(b).splitlines():
        if ln.startswith("_") and ln.endswith("_"):
            ln = ln[1:-1]
        lines.append(ln.replace("**", "").removeprefix("## ").removeprefix("# "))
    return "\n".join(lines)
