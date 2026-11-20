"""Streamlit demo: streamlit run app.py

Everything here queries the persistent store (store/memory.sqlite + store/chroma);
no transcript is ever loaded wholesale into a prompt.
"""
import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from src.memory import db  # noqa: E402

st.set_page_config(page_title="AMI Meeting Memory Agent", layout="wide")


@st.cache_resource
def resources():
    from src.agents.qa_agent import MeetingMemoryAgent
    from src.retrieval.hybrid import HybridRetriever
    conn = db.connect()
    return conn, MeetingMemoryAgent(conn, HybridRetriever(conn))


conn, agent = resources()
teams = [r[0] for r in conn.execute("SELECT DISTINCT team_id FROM meetings ORDER BY team_id")]

st.title("AMI Meeting Memory Agent")
st.caption("Hybrid retrieval (SQLite FTS5 BM25 + Chroma/MiniLM vectors) over 138 AMI meetings, temporal decision "
           "memory, and programmatically verified verbatim citations.")
tab_ask, tab_hist, tab_brief, tab_stats, tab_eval = st.tabs(
    ["Ask", "Decision history", "TS3012 brief", "Ingestion stats", "Evaluation"])

with tab_ask:
    qs = json.loads(config.QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]
    pick = st.selectbox("Example (from questions.json) or type your own below",
                        ["(custom)"] + [f"{q['question_id']}: {q['question']}" for q in qs])
    default = "" if pick == "(custom)" else pick.split(": ", 1)[1]
    question = st.text_area("Question (mention a team id such as ES2008)", value=default, height=90)
    team = st.selectbox("Team scope", ["(detect from question)"] + teams)
    if st.button("Ask the agent", type="primary") and question.strip():
        with st.spinner("Running agent loop..."):
            r = agent.answer(question, team_id=None if team.startswith("(") else team)
        (st.warning if r.abstained else st.success)(r.answer)
        st.write(f"Team: `{r.team_id}` · confidence: {r.confidence} · models: {', '.join(r.models)} · {r.seconds}s")
        st.subheader("Citations (verified verbatim against the transcript)")
        for c in r.citations:
            st.markdown(f"**{c['meeting_id']}** · Speaker {c['speaker']} · turn {c['turn']} · "
                        f"judge supports: {c.get('supported')}\n> {c['quote']}")
        with st.expander("Citation validation details"):
            st.json(r.citation_checks)
        st.subheader("Agent trace")
        for t in r.trace:
            with st.expander(f"{t['stage']}" + (f" (round {t['round']})" if "round" in t else "")):
                st.json({k: v for k, v in t.items() if k != "t"})
        st.subheader("Retrieved transcript excerpts")
        by_m = {}
        for mid, idx in r.retrieved_turns:
            by_m.setdefault(mid, []).append(idx)
        for mid, idxs in by_m.items():
            with st.expander(f"{mid}: {len(idxs)} turns"):
                for t in db.get_turns(conn, mid, min(idxs), max(idxs)):
                    if t["turn_idx"] in idxs:
                        st.text(f"t{t['turn_idx']} [{t['time']}] Speaker {t['speaker']}: {t['text']}")

with tab_hist:
    tm = st.selectbox("Team", teams, index=teams.index("TS3012") if "TS3012" in teams else 0)
    typ = st.multiselect("Record types", ["decision", "action", "commitment", "disagreement", "open_question", "reference"],
                         default=["decision"])
    topic = st.text_input("Topic filter (e.g. energy, case, LCD)")
    recs = db.records_for_team(conn, tm, typ or None)
    if topic:
        recs = [r for r in recs if topic.lower() in (r["topic"] or "").lower() or topic.lower() in r["description"].lower()]
    if not recs:
        st.info("No memory records yet: run `python scripts/ingest.py` (LLM extraction) first.")
    for r in recs:
        badge = {"accepted": "🟢", "superseded": "🟠", "rejected": "🔴", "proposed": "⚪", "completed": "✅"}.get(r["status"], "▫️")
        cur = " **(current)**" if r["is_current"] else ""
        link = f" → replaced by {r['superseded_by']}" if r["superseded_by"] else ""
        st.markdown(f"{badge} `{r['meeting_id']}` **{r['type']}/{r['status']}**{cur} · _{r['topic']}_ · "
                    f"Speaker {r['speaker'] or '?'}{(' · owner ' + r['owner']) if r['owner'] else ''}{link}  \n"
                    f"{r['description']}" + (f"  \n> {r['evidence_quote']}" if r["evidence_quote"] else ""))

with tab_brief:
    p = config.OUTPUTS_DIR / "ts3012_brief.md"
    if st.button("Regenerate brief (LLM call)"):
        from src.briefing.brief import build_brief, render_markdown
        with st.spinner("Building brief from memory..."):
            p.write_text(render_markdown(build_brief("TS3012", conn)), encoding="utf-8")
    st.markdown(p.read_text(encoding="utf-8") if p.exists() else "Run `python scripts/generate_brief.py` first.")

with tab_stats:
    st.json(db.stats(conn))
    sp = config.OUTPUTS_DIR / "ingestion_stats.json"
    if sp.exists():
        st.json(json.loads(sp.read_text()))
    rows = conn.execute("SELECT team_id, COUNT(*) n, GROUP_CONCAT(stage, '') stages, SUM(n_words) words "
                        "FROM meetings GROUP BY team_id ORDER BY team_id").fetchall()
    st.dataframe([dict(r) for r in rows], width='stretch')

with tab_eval:
    ep = config.OUTPUTS_DIR / "evaluation_report.json"
    if ep.exists():
        res = json.loads(ep.read_text(encoding="utf-8"))
        st.json(res["summary"])
        st.dataframe([{k: r[k] for k in ("id", "team", "auto_verdict", "manual_verdict", "facts_hit",
                                         "citations_valid", "retrieval_recall", "meeting_coverage")}
                      for r in res["rows"]], width='stretch')
        st.markdown((config.OUTPUTS_DIR / "evaluation_report.md").read_text(encoding="utf-8"))
    else:
        st.info("Run `python scripts/evaluate.py` first.")
