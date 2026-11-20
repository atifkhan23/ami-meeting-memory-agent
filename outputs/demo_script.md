# Demo script (3-5 minutes)

Setup before recording: `streamlit run app.py` open in a browser; a terminal in the repo with the venv active;
`outputs/answers.json`, `outputs/ts3012_brief.md` and `outputs/evaluation_report.md` already generated.

## 0:00 - The problem (30 s)
"A founder records every meeting. After months there are hundreds of hours: decisions that changed, promises,
push-back. This corpus is a runnable slice: 138 real AMI meetings, 35 teams, 677k words of messy speech. The
brief says assume 10,000 meetings, so pasting everything into a prompt is the wrong answer. Everything I show
queries a persistent store."

## 0:30 - Ingestion (40 s)
Terminal: `python scripts/ingest.py --no-llm` (re-run: shows *138 skipped unchanged* - sha256 idempotency).
Streamlit, **Ingestion stats** tab: 138 meetings, 48,148 turns, 4,334 speaker-turn chunks; IS1002 has no
meeting *a*, IS1005 no meeting *d* - detected by code.
Say: "Parsing, chunking, hashing, BM25 indexing and embeddings are plain code and a local model - no LLM. The LLM
only does what needs language understanding: extracting decisions/commitments and reconciling them over time."

## 1:10 - How memory and search work (30 s)
Point at the architecture diagram in the README: verbatim turns (SQLite) -> FTS5 BM25 + MiniLM vectors fused
with RRF, filtered by team before ranking -> structured records with verified evidence quotes.

## 1:40 - A multi-meeting question, live (60 s)
**Ask** tab, choose Q03 (TS3009 titanium) or type:
*"Team TS3009 planned a titanium back for their remote. Who first proposed replacing the titanium, what did they
propose instead, and was the titanium kept in the end?"*
Walk the **agent trace** expanders: scope (team TS3009, meetings a-d) -> intent (answer parts + spoken-word search
queries) -> retrieval round(s) with chunk ids from several meetings and their sources (bm25/vector) -> assessment
(sufficient? follow-up queries) -> citation validation -> support check / revision.

## 2:40 - Exact citation verification (30 s)
Open "Citation validation details": each quote shows `exact_match`, `single_turn`, `team_ok`, and whether it was
*snapped* (model near-miss replaced by the transcript's own characters). Say: "Python, not the model, decides
whether a quote is real. A quote that isn't inside one speaker turn of that team's meeting is dropped; with no
valid quote the answer is marked UNCERTAIN."

## 3:10 - A decision that changed over time (30 s)
**Decision history** tab, team TS3012 (or ES2013, topic "energy"): accepted / superseded / rejected badges with
`replaced by ...` links. Say: "The LLM proposes links; code applies the state machine: links only go backwards in
time, must join the same topic, and a later *suggestion* can't overturn an accepted decision."

## 3:40 - The TS3012 brief (30 s)
**TS3012 brief** tab. Point out: built *as of before meeting d* (state replayed at that cutoff, so the final meeting
can't leak in); every bullet carries verified quotes; recommendations are labelled as such.

## 4:10 - Evaluation and honesty (40 s)
**Evaluation** tab: 12 hand-verified questions (10 answerable, 2 abstention traps such as IS1005's non-existent
meeting d). Show the correct/partial/incorrect counts, citation exact-match, retrieval recall, and open
`outputs/failure_analysis.md` for the three real failures and why. Close on cost: `outputs/cost_estimate.md` -
measured tokens per meeting, ~$ for 1,000 meetings, and the real bottleneck at free tier (503s, 20 requests/day on
one model, 8k tokens/minute on Groq).

## Suggested live questions
1. "What did Team TS3012 decide about the energy source, and did it change?" (temporal)
2. "In Team ES2008, who said they would look into whether the remote should only control the TV?" (commitment)
3. "Which age group did Team TS3003 design for and why?" (rationale)
4. "What final production cost did Team IS1005 report in meeting d?" (should abstain - no meeting d)
5. "Why did Team IS1006 choose a wooden case?" (false premise - should say no evidence)

## If asked "why not just RAG?"
RAG = one retrieval + one generation. This agent plans queries, retrieves per meeting, judges sufficiency and
re-retrieves (bounded at 3 rounds), consults a temporal state machine, verifies every quote in code, checks support,
and revises. Each step is in the trace.
