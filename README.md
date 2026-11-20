# AMI Meeting Memory Agent

An agent that turns 138 real meeting transcripts (AMI Meeting Corpus, ~677k words, 35 design teams) into a
**searchable, time-aware team memory**, answers multi-meeting questions with **verbatim, machine-verified
citations**, and writes a **pre-meeting brief** (Team TS3012, before its final meeting).

Built for the Catalist Media *Agentic AI Intern* build test.

---

## 1. Why this problem matters
Recorded meetings pile up faster than anyone can read them. The valuable content - what was decided, what changed,
who promised what, what is still contested - is scattered across hours of messy speech ("um", interruptions,
half-sentences). A useful memory must (a) find the right passages among thousands of meetings without pasting
everything into a prompt, (b) understand that a decision in meeting *c* can replace one from meeting *a*, and
(c) prove every claim with the exact words that were said.

## 2. Architecture

```
transcripts/*.txt
   │  (code) discover → sha256 → parse turns (speaker, time, char offsets) → speaker-turn chunks
   ▼
SQLite  ── meetings, verbatim turns, chunks, FTS5 BM25 index ──┐
Chroma  ── MiniLM-L6 embeddings (local CPU) + team/meeting metadata ┤  persistent memory store
   │  (LLM, cheap)  per-meeting structured extraction: decisions / actions / commitments /
   │                disagreements / open questions / references / speaker roles  (every quote snapped & verified)
   │  (LLM) per-team temporal reconciliation proposes topic + links;  (code) state machine applies them
   ▼
memory_records + memory_links  (history never deleted; statuses replayable at any cutoff)

Question ─► scope (code) ─► intent & search plan (LLM) ─► hybrid retrieval: BM25 + vectors + RRF,
            team-filtered, per-meeting coverage + memory records + roles (code) ─► evidence assessment &
            draft (LLM) ─► [insufficient? follow-up queries + neighbour expansion, ≤3 rounds] ─►
            citation snapping + exact validation (code) ─► support judge (LLM) ─► self-revision (LLM) ─► answer
```

| Component | Module | Model or code? |
|---|---|---|
| File discovery, hashing, incremental/idempotent ingest, failure log | `src/ingestion/pipeline.py` | code |
| Parsing (meeting/team id, speaker, timestamp, char offsets) | `src/parsing/transcript.py` | code |
| Speaker-turn chunking (never splits a turn, keeps questions with answers, 3-turn overlap) | `src/ingestion/chunker.py` | code |
| Embeddings (batched, local) + vector index | `src/retrieval/vector_store.py` | local model, no API |
| BM25 (SQLite FTS5) + RRF fusion + metadata filters | `src/retrieval/hybrid.py` | code |
| Structured memory extraction | `src/memory/extractor.py` | LLM (flash-lite) + code verification |
| Temporal state machine, as-of replay | `src/memory/temporal.py` | LLM proposes links, **code decides state** |
| Agent loop | `src/agents/qa_agent.py` | LLM for language, code for control flow |
| Citation validation + repair | `src/citations/validator.py` | code only |
| Brief | `src/briefing/brief.py` | LLM writes, code verifies every quote |
| Evaluation + schema validation | `src/evaluation/` | code (regex key facts), no LLM grading itself |
| Provider layer (fallback chain, retries, breaker, cache, usage ledger) | `src/llm/client.py` | code |

## 3. Technology choices
* **Python 3.14**, plain functions and dataclasses. No LangChain/LangGraph: the loop is ~100 lines and
  fully visible in the trace; a framework would add indirection without capability.
* **SQLite + FTS5** for the verbatim store and BM25: one file, transactional, filterable. Ports to Postgres
  (`tsvector` + `pgvector`) at 10k+ meetings without changing agent code.
* **ChromaDB + `all-MiniLM-L6-v2`** (384-d, CPU, free) for dense retrieval. NumPy fallback built in.
* **LLMs:** Google Gemini (primary) and Groq (fallback) via REST, routed per task (`config.py`):
  * *Reasoning* (answer/assess, reconcile, brief): `gemini-3.6-flash` → `gemini-3-flash-preview` →
    `gemini-3.5-flash-lite` → `gemini-3.1-flash-lite` → Groq `openai/gpt-oss-120b`.
  * *Cheap/bulk* (extraction, intent planning, support judge, revision): `gemini-3.1-flash-lite` →
    `gemini-3.5-flash-lite` → Groq `openai/gpt-oss-20b` → `openai/gpt-oss-120b`.
  The requested `gemini-3.6-flash` was unavailable (503/timeouts) for most of the run and is capped at 20 requests/day
  on the free tier, so in practice **all graded answers were produced by `gemini-3.5-flash-lite` / `3.1-flash-lite`**.
  Fallbacks are never silent: every call is logged with provider, model, tokens, latency and retries
  (`logs/llm_usage.jsonl`) and every answer records its models (`outputs/answers_detailed.json`).
* **Streamlit** demo, **pytest** tests.

## 4. How memory works
1. **Verbatim layer** - every turn stored with meeting id, speaker letter, timestamp and character offsets into
   the original file. Chunks are rendered from whole turns, so any quote lies inside exactly one turn.
2. **Search layer** - BM25 catches exact spoken tokens ("titanium", "twelve fifty"); vectors catch paraphrase
   ("stop it getting lost"). Reciprocal-rank fusion combines them; `team_id` filtering happens before ranking;
   a per-meeting pass guarantees each of the team's meetings contributes candidates for "how did it change" questions.
3. **Structured layer** - LLM-extracted records (decision / action / commitment / disagreement / open question /
   reference) each carry team, meeting, meeting order, speaker, owner, deadline, status, an **evidence quote that
   code has verified against the transcript**, the source chunk and links. Speaker roles are stored *per meeting*
   with evidence, because AMI speaker letters are not guaranteed to be the same person across a team's meetings.

## 5. How temporal decisions are tracked
* Time = `(meeting_order, turn_idx)` - computed by code, never by the model.
* The reconciler LLM sees only the compact record list (never transcripts) and proposes canonical topics and links:
  `supersedes | rejects | confirms | completes | refers_to`.
* `apply_links` (pure, unit-tested) enforces the rules: links only point backwards in time; a `supersedes`/`confirms`
  link must join records of the same topic (otherwise downgraded to `refers_to`); **a later proposal never overrides
  an accepted decision** - only a later *accepted* decision or an explicit rejection changes state; superseded records
  keep their evidence and a `superseded_by` pointer.
* `state_as_of(team, before_order)` replays the state machine with only earlier meetings - used for the TS3012 brief,
  which is written *as of the start of meeting d* so nothing from the final meeting leaks into it.

## 6. How citations are validated
`src/citations/validator.py` (no LLM): meeting id must be well-formed and exist; meeting must belong to the
question's team; the quote must occur **inside one speaker turn** after normalising only case and whitespace
(the same rule as the assessment checker); ≥ 6 words. The LLM is asked for (meeting, turn, quote); if its quote is a
near-miss (dropped "um", fixed grammar), `snap_quote` aligns it to the most similar span of the cited turn and
**substitutes the transcript's own characters** (similarity ≥ 0.8, else rejected). Invalid citations are dropped;
an answer left with none is marked `UNCERTAIN`. A cheap LLM judge then checks each quote supports the claim, and a
revision step removes claims the judge says are unsupported. `scripts/run_questions.py` re-validates the final
`answers.json` independently.

## 7. Install
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU wheel, smaller
pip install -r requirements.txt
```
If the embedding-model download stalls (seen on a flaky connection), set `HF_HUB_DISABLE_XET=1` and retry.

## 8. API keys
```bash
cp .env.example .env      # then fill GEMINI_API_KEY and GROQ_API_KEY
```
Keys are read from the environment only, never logged or committed (`.env` is git-ignored). Free tiers suffice;
nothing enables paid billing.

## 9. Data
Place the Catalist reformatted AMI transcripts in `data/transcripts/` (`ES2002a.txt` …) and `questions.json` in
`data/`. The dataset is excluded from git by `.gitignore`; obtain it from the assessment pack or the
[AMI corpus](https://groups.inf.ed.ac.uk/ami/corpus/). Inspection: 138 files, 35 teams, 48,148 turns, 676,745 words,
0 malformed files; IS1002 has no meeting *a* and IS1005 has no meeting *d*.

## 10. Run
```bash
python scripts/ingest.py --no-llm        # parse, chunk, FTS5, embeddings (deterministic, no API)
python scripts/ingest.py                 # + LLM extraction + temporal reconciliation (resumable; re-run to fill gaps)
python scripts/run_questions.py          # answers all 25 questions -> outputs/answers.json (+ traces/)
python scripts/generate_brief.py         # TS3012 brief -> outputs/ts3012_brief.md and answers.json["brief"]
python scripts/evaluate.py               # independent eval -> outputs/evaluation_report.{md,json}
python scripts/cost_estimate.py          # -> outputs/cost_estimate.md
python scripts/build_report_pdf.py       # -> outputs/AMI_Meeting_Memory_Agent_Report.pdf (9-page report)
streamlit run app.py                     # demo UI
python -m pytest -q                      # tests (offline; no model download or API needed)
```
Every LLM response is cached in `store/llm_cache.sqlite`, so re-runs are free and reproducible; delete it to force
fresh calls. Usage (provider, model, tokens, latency, retries, est. cost) is appended to `logs/llm_usage.jsonl`.

## 11. Outputs
`outputs/answers.json` (submission), `answers_detailed.json`, `traces/Qxx.json` (full agent trace per question),
`ts3012_brief.md`, `evaluation_report.md`, `failure_analysis.md`, `cost_estimate.md`, `technical_writeup.md`,
`demo_script.md`, `ingestion_stats.json`.

## 12. Results (this run)
| | |
|---|---|
| Ingestion | 138/138 meetings, 0 errors, 4,334 chunks; 3,412 memory records (96% with verified evidence quotes); 35/35 teams reconciled |
| Graded questions | 25/25 answered, 58 citations, **0 validation problems** (independent re-check), 16/25 cite >1 meeting |
| TS3012 brief | built from meetings a-c only; 11/11 citations valid |
| Independent eval (12 Q, human-reviewed) | **8 correct / 3 partial / 1 incorrect**; citation exact-match 1.00, support 0.96, retrieval recall 0.90 |
| Tests | 32 passing (`python -m pytest -q`) |

Reproducibility note: `answers.json` was generated before the last two prompt-level changes (labelling memory
summaries as "not quotable", and the missing-meeting scope note added after the evaluation). Re-running
`scripts/run_questions.py` uses the current code; responses for unchanged prompts come from the cache, changed ones
are fresh calls and may differ.

## 13. Known limitations
See `outputs/failure_analysis.md` and `outputs/technical_writeup.md`. In short: extraction quality depends on a
lite model; speaker roles are only as good as introductions in the transcripts; keyword-based evaluation scoring is
strict and was complemented by a manual review; the agent rarely re-retrieves (lite-model self-assessment is overconfident); speaker roles extracted per meeting can conflict; free-tier availability (503s, 20-500 requests/day per model, 8k TPM on Groq) dominated runtime.

## 14. Scale and cost
See `outputs/cost_estimate.md` (generated from measured token usage and timings).

## Attribution and licence
Transcripts: **AMI Meeting Corpus**, University of Edinburgh and partners, released under
[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/);
reformatted (one file per meeting, speaker letter and start time per turn) by Catalist; words as transcribed.
