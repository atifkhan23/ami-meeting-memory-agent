"""Deterministic validation of the submission file: schema + every citation re-checked
against the original transcripts (independent of the agent that produced it)."""
from __future__ import annotations

import re

from src.citations.validator import validate_citation
from src.memory import db

TEAM_RE = re.compile(r"(?:ES|IS|TS)\d{4}")


def validate_submission(sub: dict, expected_ids: list[str] | None = None, conn=None,
                        question_teams: dict[str, str] | None = None) -> list[str]:
    conn = conn or db.connect()
    problems = []
    if not isinstance(sub, dict) or not isinstance(sub.get("answers"), list):
        return ["top level must be an object with an 'answers' list"]
    if not isinstance(sub.get("brief", ""), str):
        problems.append("'brief' must be a string")
    ids = [a.get("question_id") for a in sub["answers"]]
    if expected_ids:
        missing = sorted(set(expected_ids) - set(ids))
        if missing:
            problems.append(f"missing question ids: {missing}")
    if len(ids) != len(set(ids)):
        problems.append("duplicate question ids")
    for a in sub["answers"]:
        qid = a.get("question_id")
        if not isinstance(a.get("answer"), str) or not a["answer"].strip():
            problems.append(f"{qid}: empty answer")
        cites = a.get("citations")
        if not isinstance(cites, list) or not (1 <= len(cites) <= 3):
            problems.append(f"{qid}: needs 1-3 citations, has {len(cites) if isinstance(cites, list) else 'none'}")
            continue
        team = (question_teams or {}).get(qid)
        for c in cites:
            if set(c) != {"meeting_id", "quote"}:
                problems.append(f"{qid}: citation keys must be meeting_id, quote")
            chk = validate_citation(conn, c.get("meeting_id", ""), c.get("quote", ""), team)
            if not chk.valid:
                problems.append(f"{qid}: invalid citation {c.get('meeting_id')}: {chk.error}")
    return problems


def brief_quotes(brief: str) -> list[tuple[str, str]]:
    """Extract [MEETING, Speaker X: "quote"] citations from a rendered brief."""
    return re.findall(r'\[((?:ES|IS|TS)\d{4}[a-d]), Speaker [A-Z]: "(.+?)"\]', brief)
