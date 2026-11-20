"""Evaluation against the manually verified set in data/eval_questions.json.

Scoring is deterministic (no LLM grading the LLM):
* correctness: regex key facts found in the answer -> correct (all) / partial (some) / incorrect (none);
  unanswerable items are correct only if the agent abstains / says evidence is missing.
  A human review file (data/eval_manual_review.json) can override verdicts; both are reported.
* citation exact-match accuracy: every returned citation re-validated against the transcript.
* citation support: cited meeting is one of the gold meetings AND the LLM judge did not reject it.
* retrieval recall: share of gold evidence turns present in the evidence the agent retrieved.
* abstention quality: correct abstentions on unanswerable, false abstentions on answerable.
* multi-meeting coverage: |cited meetings ∩ required| / |required|.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import config
from src.citations.validator import find_quote_turn, validate_citation
from src.memory import db


def score_facts(answer: str, key_facts: list[list[str]]) -> tuple[int, int]:
    hit = sum(any(re.search(p, answer, re.I) for p in alts) for alts in key_facts)
    return hit, len(key_facts)


def evaluate(agent, eval_path: Path = config.ROOT / "data" / "eval_questions.json", conn=None,
             only: list[str] | None = None) -> dict:
    conn = conn or db.connect()
    spec = json.loads(Path(eval_path).read_text(encoding="utf-8"))
    review_path = Path(eval_path).with_name("eval_manual_review.json")
    review = json.loads(review_path.read_text(encoding="utf-8")) if review_path.exists() else {}
    rows = []
    for q in spec["questions"]:
        if only and q["id"] not in only:
            continue
        r = agent.answer(q["question"], team_id=q["team"], question_id=q["id"])
        hit, total = score_facts(r.answer, q["key_facts"])
        if q["answerable"]:
            auto = "correct" if hit == total else ("partial" if hit > 0 else "incorrect")
            if r.abstained and hit < total:
                auto = "incorrect" if hit == 0 else auto
        else:
            auto = "correct" if (r.abstained or hit == total) else "incorrect"
        checks = [validate_citation(conn, c["meeting_id"], c["quote"], q["team"]) for c in r.citations]
        req = set(q["required_meetings"])
        cited = {c["meeting_id"] for c in r.citations}
        supported = [c for c in r.citations if (not req or c["meeting_id"] in req) and c.get("supported") is not False]
        gold_turns = []
        for g in q["gold_evidence"]:
            t = find_quote_turn(conn, g["meeting_id"], g["quote"])
            gold_turns.append((g["meeting_id"], t["turn_idx"]) if t else None)
        retrieved = set(map(tuple, r.retrieved_turns))
        recall = (sum(1 for gt in gold_turns if gt and gt in retrieved) / len(gold_turns)) if gold_turns else None
        rows.append({
            "id": q["id"], "team": q["team"], "category": q["category"], "question": q["question"],
            "ground_truth": q["ground_truth"], "answer": r.answer, "answerable": q["answerable"],
            "abstained": r.abstained, "facts_hit": f"{hit}/{total}", "auto_verdict": auto,
            "manual_verdict": review.get(q["id"], {}).get("verdict"),
            "manual_note": review.get(q["id"], {}).get("note"),
            "citations": [{"meeting_id": c["meeting_id"], "quote": c["quote"], "supported": c.get("supported")}
                          for c in r.citations],
            "citations_valid": sum(c.valid for c in checks), "citations_total": len(checks),
            "citations_supported": len(supported),
            "gold_evidence_found_in_corpus": sum(1 for g in gold_turns if g), "gold_evidence_total": len(gold_turns),
            "retrieval_recall": recall,
            "meeting_coverage": (len(cited & req) / len(req)) if req else None,
            "retrieved_meetings": r.evidence_meetings, "models": r.models, "seconds": r.seconds,
            "iterations": sum(1 for t in r.trace if t["stage"] == "retrieval"),
        })
    return {"rows": rows, "summary": summarise(rows)}


def summarise(rows: list[dict]) -> dict:
    def verdict(r):
        return r["manual_verdict"] or r["auto_verdict"]
    ans = [r for r in rows if r["answerable"]]
    unans = [r for r in rows if not r["answerable"]]
    tot_c = sum(r["citations_total"] for r in rows)
    rec = [r["retrieval_recall"] for r in rows if r["retrieval_recall"] is not None]
    cov = [r["meeting_coverage"] for r in rows if r["meeting_coverage"] is not None]
    count = lambda key, rs: {v: sum(1 for r in rs if key(r) == v) for v in ("correct", "partial", "incorrect")}
    return {
        "n_questions": len(rows), "n_answerable": len(ans), "n_unanswerable": len(unans),
        "verdicts_final": count(verdict, rows),
        "verdicts_automatic": count(lambda r: r["auto_verdict"], rows),
        "citation_exact_match_accuracy": round(sum(r["citations_valid"] for r in rows) / tot_c, 3) if tot_c else None,
        "citation_support_accuracy": round(sum(r["citations_supported"] for r in ans) /
                                           max(1, sum(r["citations_total"] for r in ans)), 3),
        "mean_retrieval_recall": round(sum(rec) / len(rec), 3) if rec else None,
        "mean_multi_meeting_coverage": round(sum(cov) / len(cov), 3) if cov else None,
        "correct_abstentions": sum(1 for r in unans if r["abstained"] or r["auto_verdict"] == "correct"),
        "false_abstentions": sum(1 for r in ans if r["abstained"]),
        "mean_iterations": round(sum(r["iterations"] for r in rows) / max(1, len(rows)), 2),
    }


def render_report(res: dict) -> str:
    s = res["summary"]
    v, va = s["verdicts_final"], s["verdicts_automatic"]
    md = ["# Evaluation report", "",
          "Ground truth: 12 questions written and answered by reading the original transcripts (see "
          "`data/eval_questions.json`); 10 answerable + 2 abstention probes. Teams do not overlap with the 25 graded "
          "questions. Scores below are produced by `scripts/evaluate.py`; 'final' verdicts include the human review "
          "in `data/eval_manual_review.json` where present, automatic verdicts are regex key-fact matches.", "",
          "## Summary", "",
          "| Metric | Value |", "|---|---|",
          f"| Final verdicts (correct / partial / incorrect) | {v['correct']} / {v['partial']} / {v['incorrect']} |",
          f"| Automatic verdicts (correct / partial / incorrect) | {va['correct']} / {va['partial']} / {va['incorrect']} |",
          f"| Citation exact-match accuracy (independent re-validation) | {s['citation_exact_match_accuracy']} |",
          f"| Citation support accuracy (gold meeting + judge) | {s['citation_support_accuracy']} |",
          f"| Mean retrieval recall of gold evidence turns | {s['mean_retrieval_recall']} |",
          f"| Mean multi-meeting coverage of citations | {s['mean_multi_meeting_coverage']} |",
          f"| Correct abstentions (of {s['n_unanswerable']} unanswerable) | {s['correct_abstentions']} |",
          f"| False abstentions (of {s['n_answerable']} answerable) | {s['false_abstentions']} |",
          f"| Mean retrieval iterations | {s['mean_iterations']} |", "", "## Per question", ""]
    for r in res["rows"]:
        final = r["manual_verdict"] or r["auto_verdict"]
        md += [f"### {r['id']} ({r['team']}; {', '.join(r['category'])}): **{final}**", "",
               f"**Q:** {r['question']}", "", f"**Ground truth:** {r['ground_truth']}", "",
               f"**Agent:** {r['answer']}", "",
               f"facts {r['facts_hit']} · auto={r['auto_verdict']} · citations valid {r['citations_valid']}/{r['citations_total']}"
               f" · supported {r['citations_supported']} · retrieval recall {r['retrieval_recall']} · "
               f"coverage {r['meeting_coverage']} · iterations {r['iterations']}"]
        for c in r["citations"]:
            md.append(f"- [{c['meeting_id']}] \"{c['quote']}\" (judge supports: {c['supported']})")
        if r["manual_note"]:
            md += ["", f"_Reviewer note: {r['manual_note']}_"]
        md.append("")
    return "\n".join(md) + "\n"
