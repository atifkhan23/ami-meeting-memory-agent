# Submission notes

This is my submission for the Catalist Media Agentic AI Intern build test. Below is where each part of the brief
lives in this repo, so you don't have to dig for it.

| What the brief asked for | Where it is |
|---|---|
| Code and a README on how to run it | `src/`, `scripts/`, `app.py`, `README.md` |
| answers.json made by the agent (25 answers + the TS3012 brief) | `outputs/answers.json` |
| About a one-page write-up | `outputs/technical_writeup.md` |
| My own 10+ questions, checked against the transcripts, and the scores | `data/eval_questions.json`, `outputs/evaluation_report.md` |
| Three questions the agent got wrong, and why | `outputs/failure_analysis.md` |
| Cost and time for 1,000 meetings | `outputs/cost_estimate.md` |
| Walkthrough | `outputs/demo_script.md` (I'm also happy to demo live) |

I also wrote a longer report with the architecture diagrams, the LLMs I used and why, and a walkthrough of
the results: `outputs/AMI_Meeting_Memory_Agent_Report.pdf`. The full step-by-step log of what the agent did for
each question is in `outputs/traces/`.

## Where things stand

- All 138 meetings are ingested. The 25 questions are answered with 58 quotes, and every quote was checked word
  for word against the transcripts.
- On the 12 questions I wrote and checked myself, the agent got 8 right, 3 partly right and 1 wrong.
- The best Gemini models were unavailable or rate-limited for most of the day I built this, so the answers were
  written by the lighter flash-lite models. I've explained the effect of that in the failure analysis.

## Running it

The commands are in `README.md`. The short version:

```bash
pip install -r requirements.txt
python -m pytest -q          # tests run offline
streamlit run app.py         # demo
```

The memory store isn't committed to git because it's a generated 43 MB folder. You can rebuild it with
`python scripts/ingest.py`, or use the zip I sent by email, which includes it so the demo works straight away.

Transcripts are from the AMI Meeting Corpus (University of Edinburgh and partners), CC BY 4.0.
