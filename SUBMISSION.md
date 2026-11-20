# Submission: AMI Meeting Memory Agent

Catalist Media - Agentic AI Intern build test.

## Where to find each deliverable

| Requirement (from the brief) | File |
|---|---|
| Code + README on how to run it | `src/`, `scripts/`, `app.py`, `config.py`, `README.md` |
| `answers.json` made by the agent (25 answers + TS3012 brief) | `answers.json` (copy of `outputs/answers.json`) |
| One-page write-up (architecture, model vs code, tools and where they broke, production) | `outputs/technical_writeup.md` |
| Full technical report with diagrams, LLM usage, workflow, results | `outputs/AMI_Meeting_Memory_Agent_Report.pdf` (12 pages) |
| TS3012 pre-meeting brief (also inside answers.json) | `outputs/ts3012_brief.md` |
| 10+ own questions with transcript-verified answers, scored | `data/eval_questions.json`, `data/eval_manual_review.json`, `outputs/evaluation_report.md` |
| Three questions the agent got wrong, and why | `outputs/failure_analysis.md` |
| Cost and time to ingest 1,000 meetings | `outputs/cost_estimate.md` |
| Walkthrough / live demo plan | `outputs/demo_script.md`; run `streamlit run app.py` |
| Evidence of agent behaviour (every step per question) | `outputs/traces/Q01.json` ... `Q25.json` |
| Measured LLM usage (provider, model, tokens, latency) | `logs/llm_usage.jsonl` |

## Results in brief

- 138/138 meetings ingested (676,745 words, 35 teams), 0 errors; 4,334 chunks; 3,412 memory records.
- 25/25 questions answered with 58 citations; all quotes re-validated verbatim (0 problems).
- TS3012 brief built as of before meeting d; 11/11 citations valid.
- Own evaluation (12 questions): 8 correct, 3 partial, 1 incorrect; citation exact-match 100%.
- 7 LLMs used across Gemini and Groq with logged fallback; actual cost $0 (free tiers); ~$16 per 1,000 meetings at list prices.
- 32 automated tests passing.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python -m pytest -q               # 32 tests, offline
streamlit run app.py              # demo UI on the included, pre-built memory store
```

The package includes the pre-built memory store (`store/`) and the LLM response cache, so the demo and
`python scripts/run_questions.py` work immediately: cached answers replay without API keys. To call the LLMs
again (new questions, re-ingestion), copy `.env.example` to `.env` and add `GEMINI_API_KEY` / `GROQ_API_KEY`.
All commands are in `README.md`.

## Data and licence

The transcripts in `data/transcripts/` are from the AMI Meeting Corpus (University of Edinburgh and partners),
CC BY 4.0, as reformatted by Catalist (see `data/CREDITS.txt`).
