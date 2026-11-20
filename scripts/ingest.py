"""Ingest transcripts -> SQLite/FTS5 + Chroma, then (optionally) LLM memory extraction + temporal reconciliation.

    python scripts/ingest.py                 # parse/chunk/embed (no LLM) + extract + reconcile
    python scripts/ingest.py --no-llm        # only the deterministic part
    python scripts/ingest.py --teams TS3012 ES2008
"""
import _bootstrap  # noqa: F401
import argparse
import json
import time

import config
from src.ingestion.pipeline import ingest
from src.llm.client import get_client
from src.memory import db
from src.memory.extractor import extract_all
from src.memory.temporal import reapply_team, reconcile_team

ap = argparse.ArgumentParser()
ap.add_argument("--dir", default=str(config.TRANSCRIPTS_DIR))
ap.add_argument("--no-llm", action="store_true")
ap.add_argument("--teams", nargs="*")
ap.add_argument("--workers", type=int, default=4)
a = ap.parse_args()

conn = db.connect()
t0 = time.time()
rep = ingest(a.dir, conn)
timings = {"deterministic_ingest_s": round(time.time() - t0, 1)}
print(json.dumps(rep.summary(), indent=2))
if not a.no_llm:
    t1 = time.time()
    ex = extract_all(conn, team_ids=a.teams, workers=a.workers)
    timings["extraction_s"] = round(time.time() - t1, 1)
    print("extraction:", json.dumps(ex, indent=2))
    t2 = time.time()
    teams = a.teams or sorted({r[0] for r in conn.execute("SELECT DISTINCT team_id FROM meetings")})
    from concurrent.futures import ThreadPoolExecutor

    def _rec(t):
        c = db.connect()
        try:
            for attempt in range(3):  # providers briefly saturated: wait and retry, then give up (resumable)
                try:
                    return reconcile_team(c, t)
                except Exception as e:
                    if attempt == 2:
                        return {"team": t, "failed": str(e)[:200]}
                    time.sleep(90)
        finally:
            c.close()
    with ThreadPoolExecutor(max_workers=2) as ex:
        for res in ex.map(_rec, teams):
            print("reconcile:", res, flush=True)
    for t in teams:  # deterministic re-application of the state machine (no LLM) keeps rules consistent
        reapply_team(conn, t)
    timings["reconcile_s"] = round(time.time() - t2, 1)
    print("llm usage:", json.dumps(get_client().usage_summary(), indent=2))
stats = db.stats(conn)
print(json.dumps(stats, indent=2))
config.OUTPUTS_DIR.mkdir(exist_ok=True)
(config.OUTPUTS_DIR / "ingestion_stats.json").write_text(json.dumps(
    {"report": rep.summary(), "store": stats, "timings": timings,
     "llm_usage": get_client().usage_summary() if not a.no_llm else None}, indent=2), encoding="utf-8")
