"""Run the agent on the manually verified evaluation set and write the report.

    python scripts/evaluate.py [--only E01 E05] [--questions data/failure_probes.json --tag probes]
"""
import _bootstrap  # noqa: F401
import argparse
import json

import config
from src.agents.qa_agent import MeetingMemoryAgent
from src.evaluation.evaluate import evaluate, render_report
from src.llm.client import get_client

ap = argparse.ArgumentParser()
ap.add_argument("--only", nargs="*")
ap.add_argument("--questions", default=str(config.ROOT / "data" / "eval_questions.json"))
ap.add_argument("--tag", default="evaluation")
a = ap.parse_args()

res = evaluate(MeetingMemoryAgent(), a.questions, only=a.only)
res["llm_usage"] = get_client().usage_summary()
config.OUTPUTS_DIR.mkdir(exist_ok=True)
(config.OUTPUTS_DIR / f"{a.tag}_report.json").write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
(config.OUTPUTS_DIR / f"{a.tag}_report.md").write_text(render_report(res), encoding="utf-8")
print(json.dumps(res["summary"], indent=2))
