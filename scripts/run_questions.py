"""Answer questions.json with the agent and write outputs/answers.json (+ traces).

    python scripts/run_questions.py [--only Q01 Q05] [--no-brief]
"""
import _bootstrap  # noqa: F401
import argparse
import json
import time

import config
from src.agents.qa_agent import MeetingMemoryAgent
from src.evaluation.schema import validate_submission
from src.llm.client import get_client

ap = argparse.ArgumentParser()
ap.add_argument("--only", nargs="*")
ap.add_argument("--questions", default=str(config.QUESTIONS_PATH))
a = ap.parse_args()

qs = json.load(open(a.questions, encoding="utf-8"))["questions"]
if a.only:
    qs = [q for q in qs if q["question_id"] in a.only]
agent = MeetingMemoryAgent()
out_path = config.OUTPUTS_DIR / "answers.json"
existing = json.load(open(out_path, encoding="utf-8")) if out_path.exists() else {"answers": [], "brief": ""}
answers = {x["question_id"]: x for x in existing.get("answers", [])}
details_path = config.OUTPUTS_DIR / "answers_detailed.json"
details = json.load(open(details_path, encoding="utf-8")) if details_path.exists() else {}
(config.OUTPUTS_DIR / "traces").mkdir(parents=True, exist_ok=True)
t0 = time.time()
for q in qs:
    r = agent.answer(q["question"], team_id=q.get("team"), question_id=q["question_id"])
    answers[q["question_id"]] = r.submission()
    details[q["question_id"]] = {"question": q["question"], "answer": r.answer, "citations": r.citations,
                                 "confidence": r.confidence, "abstained": r.abstained, "models": r.models,
                                 "evidence_meetings": r.evidence_meetings, "seconds": r.seconds,
                                 "support": r.support}
    (config.OUTPUTS_DIR / "traces" / f"{q['question_id']}.json").write_text(json.dumps(r.trace, indent=2, default=str), encoding="utf-8")
    print(f"\n{q['question_id']} ({r.seconds}s, {r.models}): {r.answer}")
    for c in r.citations:
        print(f"   [{c['meeting_id']}] \"{c['quote']}\"")
    # write after each question so the run is resumable
    ordered = [answers[k] for k in sorted(answers)]
    out_path.write_text(json.dumps({"answers": ordered, "brief": existing.get("brief", "")}, indent=2, ensure_ascii=False), encoding="utf-8")
    details_path.write_text(json.dumps(details, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

sub = json.load(open(out_path, encoding="utf-8"))
allq = json.load(open(a.questions, encoding="utf-8"))["questions"]
problems = validate_submission(sub, expected_ids=[q["question_id"] for q in allq],
                               question_teams={q["question_id"]: q["team"] for q in allq})
print(f"\nDone in {time.time()-t0:.0f}s. Schema/citation problems: {problems or 'none'}")
print(json.dumps(get_client().usage_summary(), indent=2))
