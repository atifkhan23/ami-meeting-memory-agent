"""The meeting-memory agent: one agent, explicit tools, observable loop.

Question
  -> [1] scope (code: team id regex)  + intent analysis (LLM: sub-parts + search queries)
  -> [2] hybrid retrieval per query, team-filtered, per-meeting coverage (code)
       + structured memory lookup: relevant records, decision timelines, speaker roles (code)
  -> [3] evidence assessment + draft answer (LLM)  -- returns sufficient? / follow-up queries
  -> [4] if insufficient and iterations remain: follow-up retrieval + neighbour expansion, goto 3
  -> [5] citation snapping + exact validation (code), retry once if no valid citation (LLM)
  -> [6] support check of each citation against the claim (LLM judge, cheap model)
  -> final answer (abstains / marks UNCERTAIN when evidence is missing)
Every stage appends to `trace`, which the CLI saves and the Streamlit app displays.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field

import config
from src.citations.validator import extend_quote, snap_quote, validate_citation
from src.llm.client import LLMClient, LLMUnavailable, get_client
from src.memory import db
from src.memory.temporal import _sort_key
from src.retrieval.hybrid import Hit, HybridRetriever

log = logging.getLogger(__name__)
TEAM_RE = re.compile(r"\b((?:ES|IS|TS)\d{4})\b")

SYSTEM = """You are a meeting-memory analyst answering questions about real AMI meeting transcripts
(teams of four designing a TV remote over meetings a, b, c, d in that time order).
Rules: answer ONLY from the evidence provided. Quotes must be copied character-for-character from ONE
evidence line (one speaker turn), at least 6 words, keeping fillers like "um"/"uh" exactly.
Later meetings can overturn earlier ones: a proposal is not a decision; prefer the latest confirmed position
and say when something changed. Speaker letters can map to different people in different meetings; use the
role table when giving roles. If the evidence does not support an answer, say so."""

INTENT_PROMPT = """Question about team {team}: {question}

Plan the search. Return JSON:
{{"answer_parts": ["each distinct thing the answer must state"],
  "search_queries": ["5-7 short keyword queries using words people would actually SAY in the meeting
                      (e.g. 'kinetic battery solar', 'titanium rubber case', 'twelve fifty euro price')"],
  "temporal": true/false (does the answer depend on how something changed across meetings?),
  "topics": ["1-3 short topic labels, e.g. 'energy source'"]}}"""

ANSWER_PROMPT = """QUESTION (team {team}): {question}
Parts the answer must cover: {parts}

SPEAKER ROLES (per meeting, from transcript evidence):
{roles}

STRUCTURED MEMORY (extracted at ingest; statuses reconciled over time; use as a map, verify against evidence;
summaries are paraphrases and must NEVER be quoted - quote only transcript lines or a memory line's 'evidence'):
{memory}

TRANSCRIPT EVIDENCE (chronological; each line = one speaker turn: [meeting turn time] Speaker: text):
{evidence}

Round {round} of {max_rounds}. {final_note}
Return JSON:
{{"sufficient": true/false,
  "missing": "what is still missing (empty if sufficient)",
  "follow_up_queries": ["keyword queries to find the missing evidence"],
  "answer": "1-3 short plain sentences answering every part; give speaker letter and role when relevant; NO quotation marks or quoted text (evidence goes only in citations)",
  "confidence": "high|medium|low",
  "citations": [{{"meeting_id": "...", "turn": <turn number>, "quote": "exact words from that turn", "supports": "which claim"}}]}}
Use 1-3 citations, preferring different meetings when the answer spans meetings (e.g. the original choice AND the change)."""

FINAL_NOTE = "This is the FINAL round: answer with what the evidence supports; if a part is unsupported say so explicitly."

SUPPORT_PROMPT = """Answer: {answer}

Citations:
{cites}

For each citation, does the quoted transcript text (in context of its meeting) support part of the answer?
Also list any claims in the answer not supported by any citation. Return JSON:
{{"citations": [{{"index": 1, "supports": true/false, "why": "short"}}], "unsupported_claims": ["..."]}}"""


@dataclass
class AgentResult:
    question_id: str
    question: str
    team_id: str | None
    answer: str
    citations: list[dict]
    confidence: str = "low"
    abstained: bool = False
    trace: list[dict] = field(default_factory=list)
    evidence_meetings: list[str] = field(default_factory=list)
    retrieved_turns: list[tuple[str, int]] = field(default_factory=list)
    citation_checks: list[dict] = field(default_factory=list)
    support: dict = field(default_factory=dict)
    models: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def submission(self) -> dict:
        return {"question_id": self.question_id, "answer": self.answer,
                "citations": [{"meeting_id": c["meeting_id"], "quote": c["quote"]} for c in self.citations]}


class MeetingMemoryAgent:
    def __init__(self, conn=None, retriever: HybridRetriever | None = None, llm: LLMClient | None = None,
                 max_iterations: int = config.MAX_RETRIEVAL_ITERATIONS, check_support: bool = True):
        self.conn = conn or db.connect()
        self.retriever = retriever or HybridRetriever(self.conn)
        self.llm = llm or get_client()
        self.max_iterations = max_iterations
        self.check_support = check_support

    # ---------------------------------------------------------------- helpers
    def _log(self, trace, stage, **kw):
        entry = {"stage": stage, "t": round(time.time(), 2), **kw}
        trace.append(entry)
        log.info("[%s] %s", stage, {k: v for k, v in kw.items() if k not in ("evidence",)})

    def _roles(self, team) -> str:
        rows = self.conn.execute("SELECT r.* FROM speaker_roles r JOIN meetings m USING(meeting_id) "
                                 "WHERE m.team_id=? ORDER BY m.meeting_order, r.speaker", (team,)).fetchall()
        return "\n".join(f"{r['meeting_id']}: Speaker {r['speaker']} = {r['role']}" for r in rows) or "(none extracted)"

    def _memory(self, team, queries: list[str], topics: list[str], limit=40) -> tuple[str, list[dict]]:
        recs = db.records_for_team(self.conn, team)
        words = {w for q in queries + topics for w in re.findall(r"[a-z]{4,}", q.lower())}
        def score(r):
            text = f"{r['topic']} {r['description']}".lower()
            return sum(w in text for w in words) + (0.5 if r["type"] == "decision" else 0)
        scored = sorted((r for r in recs if score(r) > 0), key=lambda r: -score(r))[:limit]
        scored.sort(key=_sort_key)
        lines = []
        for r in scored:
            extra = ""
            if r["superseded_by"]:
                extra += f" (status changed by {r['superseded_by']})"
            if r["supersedes"]:
                extra += f" (replaces {r['supersedes']})"
            owner = f" owner={r['owner']}" if r["owner"] else ""
            ev = (f' | evidence [{r["meeting_id"]} t{r["evidence_turn"]}]: "{r["evidence_quote"]}"'
                  if r.get("evidence_quote") else "")
            lines.append(f"{r['record_id']} [{r['meeting_id']}] {r['type']}/{r['status']}{extra} "
                         f"topic={r['topic']} speaker={r['speaker']}{owner} | summary (NOT quotable): "
                         f"{r['description']}{ev}")
        return "\n".join(lines) or "(no matching records)", scored

    def _pack(self, hits: list[Hit], memory_recs: list[dict]) -> tuple[str, list[tuple[str, int]]]:
        """Merge hits into per-meeting turn sets within the token budget, render chronologically."""
        budget_words = int(config.EVIDENCE_TOKEN_BUDGET / 1.35)
        chosen: dict[str, set[int]] = {}
        used = 0
        # memory evidence turns first (small, high precision): turn +/- 2
        ranges = [(r["meeting_id"], r["evidence_turn"] - 2, r["evidence_turn"] + 2)
                  for r in memory_recs if r["evidence_turn"] is not None][:15]
        ranges += [(h.meeting_id, h.turn_start, h.turn_end) for h in sorted(hits, key=lambda h: -h.score)]
        for mid, s, e in ranges:
            rows = db.get_turns(self.conn, mid, max(0, s), e)
            new = [r for r in rows if r["turn_idx"] not in chosen.get(mid, set())]
            cost = sum(len(r["text"].split()) for r in new)
            if used + cost > budget_words and used > 0:
                continue
            chosen.setdefault(mid, set()).update(r["turn_idx"] for r in new)
            used += cost
        order = {r["meeting_id"]: r["meeting_order"] for r in self.conn.execute("SELECT meeting_id, meeting_order FROM meetings")}
        lines, turns = [], []
        for mid in sorted(chosen, key=lambda m: order.get(m, 9)):
            idxs = sorted(chosen[mid])
            rows = {r["turn_idx"]: r for r in db.get_turns(self.conn, mid, idxs[0], idxs[-1])}
            prev = None
            lines.append(f"=== {mid} (meeting {mid[-1]}) ===")
            for i in idxs:
                if prev is not None and i != prev + 1:
                    lines.append("   ...")
                r = rows[i]
                lines.append(f"[{mid} t{i} {r['time']}] Speaker {r['speaker']}: {r['text']}")
                turns.append((mid, i))
                prev = i
        return "\n".join(lines), turns

    # ------------------------------------------------------------------- main
    def answer(self, question: str, team_id: str | None = None, question_id: str = "adhoc") -> AgentResult:
        t0 = time.time()
        trace: list[dict] = []
        models = set()
        m = TEAM_RE.search(question)
        team = team_id or (m.group(1) if m else None)
        if team and not db.team_meetings(self.conn, team):
            team = None
        self._log(trace, "scope", team_id=team, meetings=[r["meeting_id"] for r in db.team_meetings(self.conn, team)] if team else [])
        scope_note = self._scope_note(question, team) if team else ""
        if scope_note:
            self._log(trace, "scope_warning", note=scope_note)
        if not team:
            return AgentResult(question_id, question, None,
                               "Insufficient evidence: no known team id (e.g. ES2008) in the question.", [],
                               abstained=True, trace=trace, seconds=time.time() - t0)

        # [1] intent analysis
        try:
            res = self.llm.complete(INTENT_PROMPT.format(team=team, question=question), SYSTEM,
                                    chain=config.EXTRACTION_CHAIN, max_tokens=1500, task="intent")
            models.add(f"{res.provider}/{res.model}")
            intent = res.data if isinstance(res.data, dict) else {}
        except LLMUnavailable as e:
            intent = {}
            self._log(trace, "intent_failed", error=str(e)[:200])
        queries = [q for q in (intent.get("search_queries") or []) if isinstance(q, str)][:7] or [question]
        queries = [question] + queries
        parts = intent.get("answer_parts") or [question]
        topics = intent.get("topics") or []
        self._log(trace, "intent", answer_parts=parts, queries=queries, temporal=intent.get("temporal"), topics=topics)

        hits: dict[str, Hit] = {}
        memory_text, memory_recs = "", []
        draft: dict = {}
        for rnd in range(1, self.max_iterations + 1):
            # [2]/[4] retrieval
            new = 0
            for q in queries:
                for h in self.retriever.search(q, team_id=team, k=6, per_meeting=1 if rnd == 1 else 0):
                    if h.chunk_id in hits:
                        hits[h.chunk_id].score += h.score
                        hits[h.chunk_id].queries |= h.queries
                    else:
                        hits[h.chunk_id] = h
                        new += 1
            if rnd > 1:  # expand context around the strongest hits
                for h in sorted(hits.values(), key=lambda h: -h.score)[:3]:
                    for nb in self.retriever.neighbors(h):
                        if nb.chunk_id not in hits:
                            nb.score = h.score * 0.5
                            hits[nb.chunk_id] = nb
                            new += 1
            memory_text, memory_recs = self._memory(team, queries, topics)
            evidence, turns = self._pack(list(hits.values()), memory_recs)
            self._log(trace, "retrieval", round=rnd, queries=queries, new_chunks=new, total_chunks=len(hits),
                      meetings=sorted({h.meeting_id for h in hits.values()}), memory_records=len(memory_recs),
                      evidence_turns=len(turns),
                      top_chunks=[(h.chunk_id, round(h.score, 4), sorted(h.sources))
                                  for h in sorted(hits.values(), key=lambda h: -h.score)[:8]])
            # [3] assess + draft
            scoped_q = question + (f"\n[SCOPE NOTE from the store: {scope_note}]" if scope_note else "")
            prompt = ANSWER_PROMPT.format(team=team, question=scoped_q,
                                          parts="; ".join(map(str, parts)),
                                          roles=self._roles(team), memory=memory_text, evidence=evidence,
                                          round=rnd, max_rounds=self.max_iterations,
                                          final_note=FINAL_NOTE if rnd == self.max_iterations else "")
            res = None
            for wait_round in range(3):  # all providers briefly down (503 burst): wait, don't fail the question
                try:
                    res = self.llm.complete(prompt, SYSTEM, max_tokens=3000, task="answer")
                    break
                except LLMUnavailable as e:
                    self._log(trace, "answer_failed", error=str(e)[:300], wait_round=wait_round)
                    if wait_round < 2:
                        time.sleep(60)
            if res is None:
                break
            models.add(f"{res.provider}/{res.model}")
            draft = res.data if isinstance(res.data, dict) else {}
            self._log(trace, "assessment", round=rnd, sufficient=draft.get("sufficient"),
                      missing=draft.get("missing"), follow_up=draft.get("follow_up_queries"),
                      draft_answer=draft.get("answer"), model=res.model)
            if draft.get("sufficient") or rnd == self.max_iterations:
                break
            fq = [q for q in (draft.get("follow_up_queries") or []) if isinstance(q, str) and q not in queries][:4]
            if not fq:
                break
            queries = fq

        result = AgentResult(question_id, question, team, (draft.get("answer") or "").strip(), [],
                             confidence=draft.get("confidence", "low"), trace=trace,
                             evidence_meetings=sorted({h.meeting_id for h in hits.values()}))
        result.retrieved_turns = turns if hits else []
        self._finalise_citations(result, draft.get("citations") or [], team, evidence if hits else "")
        if self.check_support and result.citations:
            self._support_check(result, evidence if hits else "")
        if not result.answer:
            result.answer = "Insufficient evidence: the agent could not produce a supported answer."
            result.abstained = True
        elif not result.citations:
            result.answer = "UNCERTAIN (no verifiable citation): " + result.answer
            result.abstained = True
        result.answer = self._guard_inline_quotes(result.answer, team, trace)
        result.models = sorted(models)
        result.seconds = round(time.time() - t0, 1)
        self._log(trace, "final", answer=result.answer, citations=result.citations, seconds=result.seconds)
        return result

    def _scope_note(self, question: str, team: str) -> str:
        """Deterministic: does the question refer to a meeting stage this team does not have in the store?"""
        have = {r["stage"] for r in db.team_meetings(self.conn, team)}
        asked = set(re.findall(r"\bmeeting\s+([a-dA-D])\b", question))
        asked |= {"abcd"[["first", "second", "third", "fourth"].index(w.lower())]
                  for w in re.findall(r"\b(first|second|third|fourth)\s+meeting", question, re.I)}
        missing = sorted({a.lower() for a in asked} - have)
        if missing:
            return (f"team {team} has no meeting {', '.join(missing)} in the corpus (available: {', '.join(sorted(have))}); "
                    f"say that this evidence does not exist rather than answering from other meetings")
        return ""

    # ------------------------------------------------------------ citations
    def _guard_inline_quotes(self, answer: str, team: str, trace) -> str:
        """Deterministic: any quoted span (>= 4 words) left in the answer text must be verbatim from one of the
        team's transcripts; otherwise the quotation marks are removed so nothing reads as a fake quote."""
        def check(m):
            span = m.group(1)
            if len(span.split()) < 4:
                return m.group(0)
            for (mid,) in self.conn.execute("SELECT meeting_id FROM meetings WHERE team_id=?", (team,)):
                if validate_citation(self.conn, mid, span, team).exact_match:
                    return m.group(0)
            self._log(trace, "inline_quote_unverified", removed_quotes_from=span[:120])
            return span
        return re.sub(r"[\"“]([^\"”]+)[\"”]", check, answer)

    def _snap_all(self, cites, team) -> list[dict]:
        out, checks = [], []
        for c in cites:
            if not isinstance(c, dict):
                continue
            mid, quote = str(c.get("meeting_id", "")).strip(), str(c.get("quote", "")).strip().strip('"')
            try:
                turn = int(str(c.get("turn")).lstrip("t"))
            except (TypeError, ValueError):
                turn = None
            snapped, sturn, ratio = (None, None, 0.0)
            if mid:
                snapped, sturn, ratio = snap_quote(self.conn, mid, quote, turn)
            chk = validate_citation(self.conn, mid, snapped or quote, team)
            extended = False
            if not chk.valid and chk.exact_match and chk.single_turn and not chk.min_words_ok:
                longer = extend_quote(self.conn, mid, snapped or quote)  # widen inside the same turn
                if longer:
                    chk = validate_citation(self.conn, mid, longer, team)
                    extended = chk.valid
            d = chk.to_dict()
            d["extended"] = extended
            d.update(original_quote=quote, snapped=bool(snapped and snapped != quote), similarity=round(ratio, 3))
            checks.append(d)
            if chk.valid and not any(o["meeting_id"] == mid and o["quote"] == chk.quote for o in out):
                out.append({"meeting_id": mid, "quote": chk.quote, "turn": chk.turn_idx, "speaker": chk.speaker,
                            "supports": c.get("supports", "")})
        return out, checks

    def _finalise_citations(self, result: AgentResult, cites, team, evidence):
        valid, checks = self._snap_all(cites, team)
        result.citation_checks = checks
        self._log(result.trace, "citation_validation", proposed=len(cites), valid=len(valid),
                  checks=[{k: c[k] for k in ("meeting_id", "valid", "error", "snapped", "similarity")} for c in checks])
        if not valid and evidence and result.answer:
            # one repair round: ask for quotes again, strictly from the evidence lines
            prompt = (f"Answer: {result.answer}\n\nEVIDENCE:\n{evidence}\n\nPick 1-3 quotes (>=6 words, copied exactly "
                      f"from ONE evidence line each) that support the answer. Return JSON "
                      f'{{"citations": [{{"meeting_id": "...", "turn": <n>, "quote": "..."}}]}}')
            try:
                res = self.llm.complete(prompt, SYSTEM, max_tokens=1500, task="citation_repair")
                valid, checks2 = self._snap_all((res.data or {}).get("citations", []) if isinstance(res.data, dict) else [], team)
                result.citation_checks += checks2
                self._log(result.trace, "citation_repair", valid=len(valid))
            except LLMUnavailable as e:
                self._log(result.trace, "citation_repair_failed", error=str(e)[:200])
        result.citations = valid[:3]

    def _support_check(self, result: AgentResult, evidence: str = "", allow_more: bool = True):
        cites = "\n".join(f"{i}. [{c['meeting_id']}, Speaker {c['speaker']}] \"{c['quote']}\""
                          for i, c in enumerate(result.citations, 1))
        try:
            res = self.llm.complete(SUPPORT_PROMPT.format(answer=result.answer, cites=cites), SYSTEM,
                                    chain=config.EXTRACTION_CHAIN, max_tokens=1000, task="support_check")
        except LLMUnavailable as e:
            self._log(result.trace, "support_check_failed", error=str(e)[:200])
            return
        data = res.data if isinstance(res.data, dict) else {}
        verdicts = {int(v.get("index", 0)): bool(v.get("supports")) for v in data.get("citations", []) if isinstance(v, dict)}
        for i, c in enumerate(result.citations, 1):
            c["supported"] = verdicts.get(i)
        supported = [c for c in result.citations if c.get("supported") is not False]
        if supported and len(supported) < len(result.citations):
            result.citations = supported  # drop quotes the judge says do not support the claim
        unsupported = [c for c in (data.get("unsupported_claims") or []) if isinstance(c, str) and c.strip()]
        result.support = {"verdicts": verdicts, "unsupported_claims": unsupported, "judge": res.model}
        self._log(result.trace, "support_check", **result.support)
        if unsupported and allow_more and evidence and len(result.citations) < 3 and self._add_evidence(result, unsupported, evidence):
            return self._support_check(result, evidence, allow_more=False)  # re-judge with the added quotes
        if unsupported:
            self._revise(result, unsupported)

    def _add_evidence(self, result: AgentResult, unsupported: list[str], evidence: str) -> bool:
        """Before weakening an answer, look for verbatim support for the flagged claims in the evidence."""
        prompt = (f"Answer: {result.answer}\nClaims that still need a supporting quote: {unsupported}\n\n"
                  f"EVIDENCE:\n{evidence}\n\nFor each claim, pick a quote (>= 6 words, copied exactly from ONE evidence "
                  f"line) that directly supports it, if one exists. Return JSON "
                  f'{{"citations": [{{"meeting_id": "...", "turn": <n>, "quote": "...", "supports": "which claim"}}]}}')
        try:
            res = self.llm.complete(prompt, SYSTEM, max_tokens=1200, task="add_evidence")
        except LLMUnavailable as e:
            self._log(result.trace, "add_evidence_failed", error=str(e)[:200])
            return False
        cands = (res.data or {}).get("citations", []) if isinstance(res.data, dict) else []
        new, checks = self._snap_all(cands, result.team_id)
        result.citation_checks += checks
        def overlaps(a, b):  # same meeting and one quote contains the other (case/space-insensitive)
            na, nb = " ".join(a["quote"].lower().split()), " ".join(b["quote"].lower().split())
            return a["meeting_id"] == b["meeting_id"] and (na in nb or nb in na)
        added = []
        for c in new:
            if any(overlaps(c, o) for o in result.citations + added):
                continue
            added.append(c)
        added = added[: 3 - len(result.citations)]
        result.citations += added
        self._log(result.trace, "add_evidence", proposed=len(cands), added=len(added), model=res.model)
        return bool(added)

    def _revise(self, result: AgentResult, unsupported: list[str]):
        """Self-correction: rewrite the answer so it only claims what the verified quotes support."""
        cites = "\n".join(f"[{c['meeting_id']}, Speaker {c['speaker']}] \"{c['quote']}\"" for c in result.citations)
        prompt = (f"Question: {result.question}\nDraft answer: {result.answer}\nVerified quotes:\n{cites}\n"
                  f"A checker found these claims unsupported by the quotes: {unsupported}\n"
                  "Rewrite the answer as 1-3 short plain sentences with no quotation marks. It must still directly "
                  "answer every part of the question. Keep supported facts; for a claim with no supporting quote, "
                  "either drop the detail if it is not needed to answer, or hedge it briefly with one word such as "
                  "'apparently'. Never drop the direct answer itself. Do not add new facts. Return JSON {\"answer\": \"...\"}")
        try:
            res = self.llm.complete(prompt, SYSTEM, chain=config.EXTRACTION_CHAIN, max_tokens=600, task="revise")
        except LLMUnavailable as e:
            self._log(result.trace, "revise_failed", error=str(e)[:200])
            return
        new = (res.data or {}).get("answer") if isinstance(res.data, dict) else None
        if new and new.strip():
            self._log(result.trace, "revise", before=result.answer, after=new.strip(), model=res.model)
            result.answer = new.strip()
